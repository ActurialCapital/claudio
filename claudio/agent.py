"""The voice loop: Deepgram Flux ears (eager end of turn, preemptive generation, barge-in),
one long-lived `claude` brain through the Agent SDK, Deepgram Aura mouth sentence by sentence, and a socket where
the Claude Code hooks (`claudio hook ...`) report what sessions did.

Robustness: the ears reconnect with backoff, the brain restarts if it dies (and resumes its last
session, so it remembers), the mouth retries once. An interruption first pauses the reply; a real
turn then cuts it, a backchannel ("mm-hm") or noise lets it carry on from a sentence back."""
import array, asyncio, contextlib, difflib, glob, json, os, re, shutil, signal, subprocess, sys, termios, threading, time, tty, unicodedata, urllib.parse, warnings
import sounddevice as sd, websockets
os.environ.setdefault("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")   # it would run `claude -v` before every start
from claude_agent_sdk import (AssistantMessage, CanUseToolShadowedWarning, ClaudeAgentOptions, ClaudeSDKClient,
                              PermissionResultAllow, PermissionResultDeny, PermissionUpdate,
                              ResultMessage, StreamEvent, SystemMessage, TextBlock, ToolUseBlock)
from claude_agent_sdk.types import PermissionRuleValue
from rich.spinner import SPINNERS
from . import config, ui
from .ui import console
warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)   # whole tools allowed (Read…) never ask: on purpose
IN_RATE, OUT_RATE = 16000, 24000    # the plain path; the echo-cancelling helper runs both ways at 24000
SENTENCE = re.compile(r"[.!?]['\")]?\s|\n")   # a newline ends one too: list items often have no full stop
def closed(text):
    """No **bold** or `code` left open: a sentence may end here. (A stray marker gives up after 400 characters.)"""
    return text.count("**") % 2 == 0 and text.replace("```", "").count("`") % 2 == 0


def shown_block(buf, final=False):
    """Length of the table or code fence that buf starts with, once it is complete; 0 when buf starts no such block;
    None while it can't tell yet. These are shown, never spoken."""
    if not buf or (not final and len(buf) < 3 and "```".startswith(buf)):
        return None if not final else 0
    if buf.startswith("```"):
        close = buf.find("\n```", 3)
        end = buf.find("\n", close + 4) if close >= 0 else -1
        return end + 1 if end >= 0 else (len(buf) if final else None)
    if buf.startswith("|"):
        m = re.search(r"\n[^|]", buf)
        return m.start() + 1 if m else (len(buf) if final else None)
    head = buf.split("\n", 1)[0]
    if bars(head) and loose_row(head):         # maybe a loose table, "Change | Type": decided by the lines after it
        lines, at = buf.split("\n"), 0
        for i, line in enumerate(lines):
            if i == len(lines) - 1 and not final:     # unfinished: wait while it could still be a row
                if not re.match(r"\s*[-*•]\s", line) and not re.search(r"[.!?]\s", line):
                    return None
                return at if i > 1 else 0
            delimiter = i == 1 and re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", line)
            if not (delimiter or (loose_row(line) and bars(line) == bars(head))):
                return at if i > 1 else 0      # one line alone is a sentence with a bar in it
            at += len(line) + 1
        return min(at, len(buf)) if len(lines) > 1 else 0
    return 0


def bars(line):
    """The cell bars in a line: " | " outside `code`, where "ls | grep" is a pipe, not a cell boundary."""
    return re.sub(r"`[^`]*`", "", line).count(" | ")


def loose_row(line):
    """Could be a row of a table written without its outer bars: a bar outside code, not a bullet, no sentence
    ending inside it. "- Option A | fast" and "Run `ls | grep x` to list them." are spoken, not shown."""
    return bars(line) > 0 and not re.match(r"\s*[-*•]\s", line) and not re.search(r"[.!?]\s", line)


BLOCK_END = object()          # a text block ended (a tool runs next): speak what is buffered, new transcript line


KOKORO = threading.Lock()     # a cut leaves its synthesis running in its thread: the next waits, one model, one at a time


def synth(tts, text, voice, speed):
    with KOKORO:
        return tts.create(text, voice=voice, speed=speed)


class Question(str):
    """claudio's own permission question, in the turn whose tool waits on it: said as one sentence of its own."""
YES, NO = (("yes", "yeah", "yep", "y", "sure", "ok", "okay", "allow", "allowed", "fine", "alright"),   # not go, do, please: "go away", "please don't"
           ("no", "nope", "n", "dont", "deny", "never", "not", "stop"))
BACKCHANNEL = {"yeah", "yes", "yep", "ok", "okay", "mm", "mhm", "hmm", "uh", "huh", "um", "right", "sure", "oh", "ah", "no"}
CMUX, SESSION = config.CMUX, config.SESSION
cfg, surfaces = {}, {}
current = {"task": None, "text": "", "commit": None, "ctl": None}   # the reply that holds the mouth, set by reply()
out = bytearray()             # audio waiting for the speaker
audio = {"fed": 0, "played": 0, "marks": []}   # bytes in and out of `out`, and (offset, sentences, k, shown, secs) still to show


OUT = threading.Lock()        # `out` and its counts, between the loop and the speaker's callback thread


def feed(m):
    with OUT:
        out.extend(m)
        audio["fed"] += len(m)
    status["last_audio"] = time.monotonic()


def drained(n):
    """n bytes left `out` for the speaker: show every sentence whose audio has now started playing."""
    audio["played"] += n
    while audio["marks"] and audio["marks"][0][0] <= audio["played"]:
        _, sentences, k, shown, secs = audio["marks"].pop(0)
        show(sentences, k, shown, secs)


def mark(sentences, k, shown, secs=None):
    """Sentence k's audio starts at the current end of `out`."""
    audio["marks"].append((audio["fed"], sentences, k, shown, secs))


def clear_audio():
    """A cut: drop what is queued, and the sentences that would have shown with it."""
    with OUT:
        out.clear()
        audio["fed"] = audio["played"]
    audio["marks"].clear()
speaking = asyncio.Lock()     # one reply at a time, mouth included; later ones queue
status = {"live": None, "muted": False, "ears": True, "last_audio": 0.0, "reply": None, "orch": "", "gate_open": True,
          "level": 0, "latency": None, "skip": False}
pending = {"rule": None, "ask": "", "options": "", "ready": False, "future": None, "press": None}   # the skip question, a session's permission prompt (press), or a tool waiting on one: answerable once shown   # skip: no permission checks, this run only, never saved
BARS = " ▁▂▃▄▅▆▇"
SPIN, MUTED = SPINNERS["dots"]["frames"], ["■"]
SLASH_HELP = ("Slash commands:\n"
              "- `/clear` starts a fresh conversation.\n"
              "- `/model` default, sonnet, opus or haiku.\n"
              "- `/effort` low, medium or high.\n"
              "- `/voice` and a name, such as zeus; alone, it lists them.\n"
              "- `/style` plain, brief or caveman.\n"
              "- `/colors` on or off, for code.\n"
              "- `/layout` inline or split.\n"
              "- `/name` and a new one, such as Roger: what I answer to.\n"
              "- `/address me` on or off: only turns that start with my name count.\n"
              "- `/` and any other setting, as it reads, then a value: `/barge in off`, `/push to talk on`, "
              "`/narrate all`, `/eot 0.8`. A setting alone says what it is; one that is on or off flips.\n"
              "- `/status` says the settings.\n"
              "- `/mute` and `/unmute`.\n"
              "- `/stop` cuts a reply.\n"
              "- `/permissions skip` or `ask`: no checks until you quit, or checks again.\n"
              "- `/restart` starts me over, same conversation.\n"
              "- `/quit` or `/exit` says bye and quits.\n"
              "- `/help` says this list.")
COMMANDS = {"clear", "mute", "unmute", "stop", "style", "model", "effort", "voice", "status", "help", "colors", "colours", "layout",
            "name", "address", "permissions", "quit", "exit", "restart"}
SETTINGS = sorted((k for k in config.DEFAULTS if k not in config.SECRETS), key=lambda k: -k.count("_"))   # longest first
SKIP = "every permission check"   # what a yes turns off, when claudio asked about skipping them
STYLES = {
    "plain": "",
    "brief": "\n\nSTYLE OVERRIDE, brief: this replaces every rule above about length and format. Speak one sentence "
             "per reply, two at most when the answer has two parts. No lead-in before a tool, no question back unless "
             "the next step is truly the user's call. Whenever the answer names several things, sums up or compares, "
             "the screen carries it: a Markdown table when the things have two or more factors (shown, never read), "
             "else bullets of a few words each. Order: one short spoken sentence saying what it is, then the table "
             "or bullets, then at most one sentence on what stands out, and nothing at all after a table the user asked "
             "for. Never open a reply with a table or bullets.",
    "caveman": "\n\nSTYLE OVERRIDE, caveman: this replaces every rule above about sentences. Speak like a caveman: "
               "at most six words per sentence, drop articles, auxiliaries and connectors, fragments are the norm. "
               "Facts, names and numbers stay exact. Example: \"Next: Sales. File fields still open. Main clean. "
               "Want Sales started?\" Never a full polite sentence.",
}
LEAD = "|".join(["um", "uh", "ok", "okay", "so", "hey", "and", "well", "please", "yeah", "right", "now", "slash", *COMMANDS])   # what may come before "slash"
SLASH = re.compile(rf"^(?:(?:{LEAD})\s+){{0,2}}slash\s+(\w+)\s*(.*)$")   # "um slash mute", an echoed "mute slash mute"; not "add a slash command"


def slash_words(said):
    """norm, but a decimal point kept: "Slash EOT 0.8." is "slash eot 0.8"."""
    return " ".join(re.sub(r"(?<!\d)\.|\.(?!\d)|[^a-z0-9. ]", "", said.lower()).split())


def parse_slash(words):
    """("style", "caveman") from "slash um i want a caveman"; None when it is no command."""
    m = SLASH.search(words)
    if not m:
        return None
    rest = f"{m.group(1)} {m.group(2)}".split()
    for i in range(len(rest)):                 # a setting as it reads, past "um": "slash barge in off", "slash eot 0.8"
        if rest[i] in COMMANDS:
            break                              # its own command: "slash voice zeus"
        if k := next((k for k in SETTINGS if rest[i:i + k.count("_") + 1] == k.split("_")), None):
            return k, " ".join(rest[i + k.count("_") + 1:])
    if rest[0] not in COMMANDS:                # misheard: "slash e fort", "slash efort", "slash colours" spelt oddly
        for n in (1, 2):                      # one word first: "permission skip" keeps its "skip"
            near = difflib.get_close_matches("".join(rest[:n]), COMMANDS, 1, 0.75)
            if near and len(rest) >= n:
                rest = [near[0], *rest[n:]]
                break
    at = next((i for i, w in enumerate(rest) if w in COMMANDS or w in STYLES or w in config.AURA), 0)   # past "um, I want a"
    cmd, arg = rest[at], " ".join(rest[at + 1:])
    if cmd in STYLES:                          # "slash caveman"
        cmd, arg = "style", cmd
    elif cmd in config.AURA:                   # "slash pandora"
        cmd, arg = "voice", cmd
    if cmd == "style":                         # misheard: "pavement" is caveman
        arg = next((c[0] for w in arg.split() if (c := difflib.get_close_matches(w, STYLES, 1, 0.6))), arg)
    return cmd, arg


def state_text():
    """Derived, never set: so a reply ending can't overwrite the one that replaced it."""
    if status.get("warming"):
        return "warming up the brain…"
    if status.get("typed"):
        return f"› {status['typed']}▏"         # typed: unechoed, so shown here
    r = status["reply"]
    if status["muted"]:
        return "muted · say /unmute"
    if not status["ears"]:
        return "ears lost · reconnecting"
    if r and r["task"].done():
        r = None
    if r and r["paused"].is_set():
        return "paused"
    mine = "listening"
    if r and r["commit"].is_set():
        mine = "speaking" if time.monotonic() - status["last_audio"] < 0.4 or out else "thinking"
    elif cfg.get("push_to_talk") and not status["gate_open"]:
        mine = "push to talk · Enter opens the mic"
    lat = status["latency"]
    if lat and time.monotonic() < lat[1]:
        mine += f"  ·  {lat[0]} to first word"
    return f"{mine}  ·  {cfg['orchestrator']} {status['orch']}" if status["orch"] else mine


def refresh():
    if status["live"]:
        bar = BARS[min(7, int(status["level"] / 1200))]       # ~0 to 8400 peak over the eight bars
        status["live"].update(f"[cyan]{bar}[/] [dim]{state_text()}[/]"
                              + ("  [bold red]· no permission checks[/]" if status["skip"] else ""))
        status["live"].renderable.frames = MUTED if status["muted"] else SPIN     # muted: a still square, no spin


parse_surfaces, sessions = config.parse_surfaces, config.surfaces
SESSION = f"claude --append-system-prompt-file {os.path.join(os.path.dirname(__file__), 'session.md')}"   # sessions it opens take its marker as the user's words


def system_prompt():
    lines = [f"- {w}: surface {full} ({t}), in {c}" for sid, (w, t, c, full) in surfaces.items() if w]
    keys = [k for k in config.DEFAULTS if k not in config.SECRETS]
    settings = ", ".join(f"{k}={cfg[k]}" for k in keys)
    persona = (config.persona()
               .replace("{TRANSCRIPTS}", ui.TRANSCRIPTS)
               .replace("{SESSION}", SESSION)
               .replace("{FROM}", "Voice" if cfg["name"].lower() == "claudio" else cfg["name"])   # who relayed it, in the session's inbox
               .replace("{KEYS}", ", ".join(f"{k} ({'|'.join(config.CHOICES[k])})" if k in config.CHOICES else k
                                            for k in keys)))
    commands = SLASH_HELP.split("\n", 1)[1]
    try:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        remote = ""
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    owner, repo = m.groups() if m else ("", "")
    return (STYLES.get(cfg["style"], "").strip() + "\n\n" + persona
            + "\n\nclaudio's own slash commands, the only ones there are here. The user says \"slash\" and the name "
            + "(or types /name), and claudio runs it before you hear anything; you can't run them:\n" + commands
            + f"\n\nOrchestrator: {cfg['orchestrator'] or 'none set'}.\nYour settings now: {settings}.\n"
            + "Sessions now (to see one, run cmux read-screen --surface <its id> --lines 60):\n"
            + (config.layout(surfaces) or "\n".join(lines))
            + (f"\nYour name is {cfg['name']}: the user may call you by it, and you call yourself by it.\n"
               if cfg["name"].lower() != "claudio" else "")
            + "\n\nRules that matter most, last so they stay in mind:\n"
            + "- A turn not meant for you (talk to someone else, a TV, a name, one stray word) or cut off mid-thought "
              "(\"Can you tell me\") gets exactly [skip] as your whole reply. Nothing else.\n"
            + (f"- GitHub here is {owner}/{repo}. A repo named without its owner, such as \"{repo}-app\", is {owner}/<that name>: "
               f"gh ... -R {owner}/<name>.\n" if owner else "")
            + (f"- The voice is {cfg['mouth']}: local_voice, local_speed and local_model do nothing, and it has no speed "
               "setting. Say so rather than suggest them.\n" if cfg["mouth"] != "local" else "")
            + "- Asked for a table: \"Here it is.\", then the table, and nothing after it: no summary, no take.\n"
            + "- Notes, lookups and opening the browser are your own jobs: never hand them to a session. "
              "\"In the browser\" means open it there and say only \"Opening it.\", no answer.\n"
            + "- What you hear is speech to text and can be misheard: read an odd word as what was likely said "
              "(\"seven notes saying hello\" is \"save a note saying hello\"), and never multiply work on a number "
              "that may be a mishearing: ask.\n"
            + "- Never say a setting changed unless `claudio set` succeeded, and never send work after a no."
            + ("\n- Permission checks are off for this run, at the user's word: nothing you run is refused. Hand work "
               "to a session when the user's words say to, with no yes or no from claudio: say what you handed over "
               "and to whom. A question or an unclear turn is no order: answer it, or ask. Run "
               "nothing that deletes, overwrites or pushes without the user's plain yes."
               if status["skip"] else ""))


def real_claude():
    """The claude binary itself. In a cmux pane, a cmux wrapper comes first on PATH and adds cmux's hooks, among them
    an inbox one that hands the brain messages meant for claudio and ends its turn twice: every reply a turn late."""
    for d in os.environ.get("PATH", "").split(os.pathsep):
        path = os.path.join(d, "claude")
        if os.access(path, os.X_OK) and "cmux" not in os.path.realpath(path) and ".cmuxterm" not in path:
            return path
    return shutil.which("claude") or "claude"


def remembered_session():
    """The last brain session's id, if memory is on and it is recent enough to be worth resuming."""
    if not cfg.get("memory", True) or not os.path.exists(SESSION):
        return None
    try:
        sid, when = open(SESSION).read().split()
        return sid if time.time() - float(when) < 7 * 86400 else None
    except ValueError:
        return None


class Brain:
    """One claude process, through the Agent SDK. A turn is a user line; its text deltas stream back."""
    def __init__(self):
        self.client, self.session_id, self.busy = None, None, False
        self.inbox, self.dead = asyncio.Queue(), asyncio.Event()   # what the CLI sends; set when it is gone
        self.lock = asyncio.Lock()
        self.handoffs = {}             # workspace title -> time of the last `cmux agent message` to it, till answered
        self.answered = {}             # workspace title -> (time, kind) of the last report narrated, for echoed()
        self.on_ask = None             # (tool, input) -> a permission result: claudio asks the user; None denies
        self.q, self.text = None, ""   # the turn running now, if any: where a question goes, and what was asked
        self.changed = asyncio.Event() # set when it ran `claudio set`, so the watcher reloads at once
        self.expected_exit = False     # a restart on purpose, not a death
        self.transport = None          # tests: a factory for a fake CLI
        self.log = None

    def options(self, resume):
        me = os.path.dirname(os.path.abspath(sys.argv[0]))      # so the brain can run `claudio set`
        env = {k: "" for k in os.environ if k.lower() in config.SECRETS}   # the SDK merges os.environ: blank the keys
        env["PATH"] = f"{me}:{os.path.dirname(CMUX)}:{os.environ.get('PATH', '')}"
        mcp = config.mcp_servers()
        notes = [d for d in map(os.path.expanduser, config.NOTES) if os.path.isdir(d)]
        self.log = self.log or open(os.path.join(config.DIR, "brain.log"), "a")
        return ClaudeAgentOptions(
            cli_path=real_claude(),
            permission_mode=None if status["skip"] else "default",   # never a mode from elsewhere ("auto" asks no one)
            system_prompt={"type": "preset", "preset": "claude_code", "append": system_prompt()},
            setting_sources=[],
            strict_mcp_config=True,           # never the desktop's MCP servers: only those in mcp.json, if any
            mcp_servers=config.MCP if mcp else {},
            extra_args={"disable-slash-commands": None,      # nor its skills and /commands: the brain took them for claudio's
                        **({"dangerously-skip-permissions": None} if status["skip"] else {})},   # the user's choice, this run only
            disallowed_tools=[f"Read(//{config.SECRETS_FILE.lstrip('/')})", "Bash(*secret*)",   # the keys, by a command that names them
                              *(f"{t}(//{config.DIR.lstrip('/')}/**)" for t in ("Edit", "Write")),   # nor grant itself rules
                              *(f"Bash(cmux {c} *--{f}*)" for c in ("new-workspace", "workspace create", "new-split", "new-surface")
                                for f in ("layout", "env")),   # their own commands
                              *(f"Bash(cmux {c} *--command*--command*)" for c in ("new-workspace", "workspace create", "new-split", "new-surface")),
                              *(f"Bash(git {c} *--{f}*)" for c in ("diff", "log") for f in ("no-index", "output", "ext-diff")),   # any file, read or written
                              "Bash(claudio choose *--other*)"],   # words typed into a pane: asked, so you see them
            allowed_tools=[
                "Read", "Grep", "Glob",
                "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)",
                *(f"Bash(git branch{f})" for f in ("", " -a", " -r", " -v", " -vv", " --show-current")), "Bash(git branch --list:*)",
                                              # listing only: -D, -m, -f and the rest change branches, so they are asked
                "Bash(gh issue view:*)", "Bash(gh issue list:*)", "Bash(gh pr view:*)", "Bash(gh pr list:*)",   # GitHub, read only
                "Bash(gh pr diff:*)", "Bash(gh pr checks:*)", "Bash(gh repo view:*)", "Bash(gh repo list:*)", "Bash(gh search:*)",
                "Bash(cmux surface list:*)", "Bash(cmux tree:*)", "Bash(cmux read-screen:*)",
                *(f"Bash(cmux {c} * --command {cmd})" for c in ("workspace create", "new-workspace", "new-split", "new-surface")
                  for cmd in ("claude", f'"{SESSION}"')),   # any other: asked
                # not cmux agent message: claudio asks the user before each send, a yes or no the brain can't give
                "Bash(claudio choose:*)",          # to pick the option the user chose in a session's question
                "Bash(claudio set:*)", "Bash(claudio unlearn:*)", "Bash(claudio restart)",   # not learn: a rule for every later run is asked
                *(f"mcp__{name}" for name in mcp),
                "WebSearch", "WebFetch", "Bash(claudio open:*)", "Bash(claudio close:*)", "Bash(test:*)",   # looking things up; opening a link or a note
                *(f"{tool}(/{d}/*.{ext})" for d in notes for tool in ("Write", "Edit") for ext in ("md", "txt"))],   # notes only, at the top:
                                              # deeper, a repo's CLAUDE.md or .claude/ would be one
            settings=json.dumps({**config._read(config.SETTINGS), "disableAllHooks": True}),   # the user's own rules;
                                              # no hooks, theirs or cmux's: those are for sessions, not the brain
            add_dirs=[*notes, *config.allowed_dirs()],             # and folders
            can_use_tool=self.can_use,
            model=None if cfg["model"] == "default" else cfg["model"],
            effort=cfg["effort"] or None,
            resume=resume,
            include_partial_messages=True,
            env=env,
            stderr=lambda line: (self.log.write(line + "\n"), self.log.flush()),
            max_buffer_size=16 * 1024 * 1024)  # a Read of a big file is one message; a small buffer fails the turn

    async def start(self):
        resume = remembered_session()
        self.client = ClaudeSDKClient(self.options(resume), transport=self.transport and self.transport())
        try:
            await self.client.connect()
        except Exception:
            if not resume:
                raise
            with contextlib.suppress(OSError):
                os.unlink(SESSION)             # that session is gone: forget it and start fresh
            ui.note("the remembered conversation is gone; starting fresh")
            return await self.start()
        self.inbox, self.dead = asyncio.Queue(), asyncio.Event()
        asyncio.create_task(self.read(self.inbox, self.dead))

    async def read(self, inbox, dead):
        """The one reader: everything the CLI sends, into the inbox; None and `dead` when it ends."""
        try:
            async for m in self.client.receive_messages():
                self.saw(m)
                inbox.put_nowait(m)
        except Exception as e:
            self.log.write(f"reader: {type(e).__name__}: {e}\n")
        finally:
            dead.set()
            inbox.put_nowait(None)

    async def stop(self):
        with contextlib.suppress(Exception):
            await self.client.disconnect()

    async def restart(self):
        async with self.lock:
            self.expected_exit = True
            try:
                await self.stop()
                await self.start()
            except Exception as e:             # it would not start: brain_watch tries again
                ui.warn(f"the brain didn't restart ({type(e).__name__}: {str(e)[:120]})")
            finally:
                self.expected_exit = False

    async def can_use(self, tool, tool_input, context):
        """A tool use the rules don't cover. In a reply to the user, claudio asks them and the call waits; an event,
        the warm-up or a typed doctor turn has nobody to ask."""
        if not self.on_ask or not self.q or self.text.startswith("[event]"):
            return PermissionResultDeny(message="Not allowed. Say in a few words that you couldn't do it.")
        return await self.on_ask(tool, tool_input)

    def say(self, text):
        """Put a question into the reply speaking now, after what the brain said so far."""
        if self.q:
            self.q.put_nowait(Question(text))

    async def interrupt(self):
        if pending["future"] and not pending["future"].done():
            pending["future"].set_result(None)     # a cut answers the question: no
        if self.busy and not self.dead.is_set():
            await self.client.interrupt()

    def saw(self, m):
        """Side channel: the brain's own session id, and which sessions it handed work to."""
        if isinstance(m, SystemMessage) and m.subtype == "init":
            self.session_id = m.data.get("session_id")
            if cfg.get("memory", True):
                with contextlib.suppress(OSError):
                    open(SESSION, "w").write(f"{self.session_id} {time.time()}")
        if isinstance(m, AssistantMessage):
            for c in m.content:
                if isinstance(c, ToolUseBlock):
                    ui.tool(c.name, c.input or {})
                if isinstance(c, ToolUseBlock) and c.name == "Bash":
                    cmd = c.input.get("command", "")
                    if m_ := re.search(r'cmux agent message\s+(?:"([^"]+)"|(\S+))', cmd):
                        asked = re.findall(r'"((?:[^"\\]|\\.)*)"', cmd)
                        to = m_.group(1) or m_.group(2)      # a surface id: the workspace it is in, which events carry
                        to = next((w for sid, (w, _, _, full) in surfaces.items() if to.upper() in (sid, full.upper())), to.upper())
                        self.handoffs[to] = (time.time(), asked[-1] if asked else "")
                    if re.search(r"(^|[;&|]\s*)claudio restart\s*$", cmd):
                        status["restart_asked"] = True     # once this reply is said (watch_config)
                    if "claudio set" in cmd or "claudio unlearn" in cmd:
                        self.changed.set()

    async def turn(self, text):
        async with self.lock:
            self.busy = True
            tag = "" if cfg["style"] == "plain" or text.startswith("[event]") else f"({cfg['style']} style) "
            inbox, q = self.inbox, asyncio.Queue()
            while not inbox.empty():           # left from an earlier turn (one that ended twice): never this reply
                if (m := inbox.get_nowait()) is None:
                    inbox.put_nowait(None)     # but a death stays news
                    break
            self.q, self.text = q, text
            await self.client.query(tag + text)

            async def pump():
                spoke, last_text = False, ""
                try:
                    while (m := await inbox.get()) is not None:   # None: it died; the watchdog restarts it
                        if isinstance(m, StreamEvent):
                            e = m.event
                            if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta":
                                spoke = True
                                q.put_nowait(e["delta"]["text"])
                            elif e.get("type") == "content_block_stop" and spoke:
                                q.put_nowait(BLOCK_END)   # a text block ended: speak its tail now, new line
                            elif e.get("type") == "content_block_start" and e["content_block"].get("type") == "tool_use" and not spoke:
                                spoke = True          # it skipped its lead-in: a word by tool kind, so the tool run is not silence
                                q.put_nowait("Looking. " if e["content_block"].get("name") in ("Read", "Grep", "Glob") else "Checking. ")
                        elif isinstance(m, AssistantMessage):
                            last_text = " ".join(c.text for c in m.content if isinstance(c, TextBlock))
                        elif isinstance(m, ResultMessage):
                            if m.is_error and not spoke and last_text:
                                q.put_nowait(last_text)   # an error with no streamed text (a bad model name): say it
                            return
                finally:
                    q.put_nowait(None)                 # whatever happened, the turn ends

            task = asyncio.create_task(pump())
            try:
                while (d := await q.get()) is not None:
                    yield d
            finally:
                if not task.done():
                    with contextlib.suppress(Exception):
                        await asyncio.shield(self.interrupt())   # a cut: stop Claude, then drain to its result
                while not task.done():         # whatever cancels us again, the drain finishes: the stream stays in step
                    with contextlib.suppress(asyncio.CancelledError):
                        await asyncio.shield(task)
                if pending["future"] and not pending["future"].done():
                    pending["future"].set_result(None)   # a question never outlives its turn (a brain that died)
                self.busy, self.q = False, None


brain = Brain()


def helper():
    """The echo-cancelling audio helper (audio.swift), built once with swiftc. None when it cannot be."""
    src = os.path.join(os.path.dirname(__file__), "audio.swift")
    exe = config.HELPER
    if os.path.exists(exe) and os.path.getmtime(exe) >= os.path.getmtime(src):
        return exe
    if sys.platform != "darwin" or not shutil.which("swiftc"):
        return None
    os.makedirs(os.path.dirname(exe), exist_ok=True)
    with console.status("[dim]building the echo canceller, once…[/]"):
        r = subprocess.run(["swiftc", "-O", src, "-o", exe], capture_output=True, text=True)
    if r.returncode:
        ui.warn(f"echo canceller did not build; using the plain mic (headphones for barge-in)\n[dim]{r.stderr[-300:]}[/]")
        return None
    return exe


async def first_of(*coros):
    tasks = [asyncio.ensure_future(c) for c in coros]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()


def new_ctl():
    return {"paused": asyncio.Event(), "resume": asyncio.Event()}


class DeepgramMouth:
    """Deepgram Aura over one Speak socket: Speak + Flush per sentence, a Flushed message per sentence back."""
    def __init__(self):
        self.ws, self.sent, self.got = None, 0, 0

    async def open(self):
        url = f"wss://api.deepgram.com/v1/speak?model={cfg['voice']}&encoding=linear16&sample_rate={OUT_RATE}"
        self.ws = await websockets.connect(url, additional_headers={"Authorization": f"Token {cfg['deepgram_api_key']}"})

    async def receive(self, on_audio):
        try:
            async for m in self.ws:
                if isinstance(m, bytes):
                    on_audio(m)
                elif json.loads(m).get("type") == "Flushed":
                    self.got += 1
        except websockets.ConnectionClosed:
            pass

    async def say(self, text):
        await self.ws.send(json.dumps({"type": "Speak", "text": text}))
        await self.ws.send(json.dumps({"type": "Flush"}))
        self.sent += 1

    def done(self):
        return self.got >= self.sent

    async def finish(self):
        pass

    async def close(self):
        with contextlib.suppress(Exception):
            await self.ws.close()


class ElevenMouth:
    """ElevenLabs over its stream-input socket: text + flush per sentence, base64 PCM back, isFinal at the end.
    Checked against the live API (eleven_flash_v2_5, 2026-10-25): audio per sentence, isFinal at the end."""
    def __init__(self):
        self.ws, self.sent, self.final = None, 0, False
        self.ends, self.chars, self.current = [], 0, 0   # cumulative text ends per sentence; chars heard so far

    async def open(self):
        url = (f"wss://api.elevenlabs.io/v1/text-to-speech/{cfg['elevenlabs_voice']}/stream-input"
               f"?model_id=eleven_flash_v2_5&output_format=pcm_24000&inactivity_timeout=180")
        self.ws = await websockets.connect(url, additional_headers={"xi-api-key": cfg["elevenlabs_api_key"]})
        await self.ws.send(json.dumps({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}}))

    async def receive(self, on_audio):
        import base64
        try:
            async for m in self.ws:
                ev = json.loads(m)
                align = ev.get("alignment") or ev.get("normalizedAlignment") or {}
                if align.get("chars"):                  # which sentence this audio belongs to, by character position
                    start = self.chars
                    self.chars += len(align["chars"])
                    self.current = next((n for n, end in enumerate(self.ends) if start < end), max(0, len(self.ends) - 1))
                if ev.get("audio"):
                    on_audio(base64.b64decode(ev["audio"]))
                if ev.get("isFinal"):
                    self.final = True
        except websockets.ConnectionClosed:
            self.final = True

    async def say(self, text):
        text = text if text.endswith(" ") else text + " "
        await self.ws.send(json.dumps({"text": text, "flush": True}))
        self.sent += 1
        self.ends.append((self.ends[-1] if self.ends else 0) + len(text))

    @property
    def got(self):
        return self.current

    def done(self):
        return self.final

    async def finish(self):
        await self.ws.send(json.dumps({"text": ""}))      # end of input: the last audio, then isFinal

    async def close(self):
        with contextlib.suppress(Exception):
            await self.ws.close()


KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_MODELS = {"compressed": "kokoro-v1.0.int8.onnx", "full": "kokoro-v1.0.onnx"}   # 88 MB, 325 MB
KOKORO_VOICES = "voices-v1.0.bin"                                                         # 27 MB, shared
ESPEAK = ("/opt/homebrew/lib/libespeak-ng.dylib", "/usr/local/lib/libespeak-ng.dylib")
_kokoro = {}                   # local_model → loaded Kokoro


def kokoro(model):
    """Kokoro-82M on the CPU, `model` being a local_model value, loaded once, its files downloaded on first use. OSError says what is missing.
    Phonemes come from Homebrew's espeak-ng: the copy bundled with kokoro-onnx ignores its data path on macOS."""
    if model not in _kokoro:
        if not os.environ.get("PHONEMIZER_ESPEAK_LIBRARY"):
            lib = next((p for p in ESPEAK if os.path.exists(p)), None)
            if not lib:
                raise OSError("the local mouth needs espeak-ng: brew install espeak-ng")
            os.environ["PHONEMIZER_ESPEAK_LIBRARY"] = lib
        try:
            from kokoro_onnx import Kokoro
        except ImportError:
            raise OSError("the local mouth needs Kokoro: uv tool install --reinstall "
                          "'claudio[local] @ git+https://github.com/ActurialCapital/claudio'") from None
        import urllib.request
        os.makedirs(config.VOICE_MODELS, exist_ok=True)
        names = (KOKORO_MODELS[model], KOKORO_VOICES)
        paths = [os.path.join(config.VOICE_MODELS, f) for f in names]
        for name, path in zip(names, paths):
            if not os.path.exists(path):
                with console.status(f"[dim]downloading the local voice, {name}, once…[/]"):
                    urllib.request.urlretrieve(KOKORO_URL + name, path + ".part")
                os.replace(path + ".part", path)
        _kokoro[model] = Kokoro(*paths)
    return _kokoro[model]


class LocalMouth:
    """Kokoro on this Mac, no key and no network: one sentence at a time, synthesized in a thread.
    Measured on an M4 (2026-10-26), short sentence / 70 characters: compressed 0.2 s / 0.5 s, full 0.5 s / 1.0 s."""
    def __init__(self):
        self.queue, self.sent, self.got = asyncio.Queue(), 0, 0

    async def open(self):
        self.tts = await asyncio.to_thread(kokoro, cfg["local_model"])

    async def receive(self, on_audio):
        while True:
            text = (await self.queue.get()).strip()
            if text:
                try:
                    samples, _ = await asyncio.to_thread(synth, self.tts, text, cfg["local_voice"], cfg["local_speed"])
                except Exception as e:          # a voice name Kokoro does not know, say: the rest is text only
                    ui.warn(f"local mouth: {e}")
                    return
                on_audio((samples.clip(-1, 1) * 32767).astype("<i2").tobytes())
            self.got += 1

    async def say(self, text):
        self.queue.put_nowait(text)
        self.sent += 1

    def done(self):
        return self.got >= self.sent

    async def finish(self):
        pass

    async def close(self):
        pass


def new_mouth():
    if cfg["mouth"] == "local":
        return LocalMouth()
    return ElevenMouth() if cfg["mouth"] == "elevenlabs" and cfg["elevenlabs_api_key"] else DeepgramMouth()


async def speak_from(sentences, i, new, gen_done, ctl, commit, shown):
    """Speak sentences[i:] over one mouth socket until done or paused. Returns (next index, finished).
    A sentence is printed when its audio starts playing, so the transcript keeps time with the voice."""
    async def open_mouth():
        for attempt in (1, 2):
            try:
                m = new_mouth()
                await m.open()
                return m
            except (OSError, websockets.exceptions.WebSocketException):
                if attempt == 1:
                    await asyncio.sleep(1)
        return None

    mouth = await open_mouth()
    if mouth is None:
        ui.warn("mouth lost: the speech service is unreachable; text only")
        await gen_done.wait()
        await commit.wait()                    # an early guess shows only once your turn is final, as with audio
        for k in range(i, len(sentences)):
            show(sentences, k, shown)
        return len(sentences), True
    first = i
    order = []                    # the sentences this mouth was given, in order: its nth audio is sentence order[n]
    held = bytearray()
    held_marks = []               # (offset within held, k): sentence starts inside the held audio
    marked = set()
    sizes = {}                    # k: bytes of sentence k's audio so far, from this mouth
    rx = {"at": 0.0}              # when audio last came in
    waiters = []

    def secs(k):
        """Sentence k's audio length, once all of it is in (a later one has started, or the mouth is done)."""
        return sizes[k] / (OUT_RATE * 2) if k in sizes and (any(j > k for j in sizes) or mouth.done()) else None

    def place(k):
        """Sentence k (blocks only, nothing to say) shows where the audio queued so far ends."""
        if k in marked:
            return
        marked.add(k)
        if not commit.is_set():
            held_marks.append((len(held), k))
        elif audio["fed"] <= audio["played"]:
            show(sentences, k, shown)          # nothing left to play: now
        else:
            mark(sentences, k, shown)

    async def place_when_quiet(k):
        """A table or code with nothing said after it yet (a tool runs next, or the reply ends): it shows once the
        sentence before it has all its audio, rather than with the next sentence, which may be far off."""
        while not all(j in sizes for j in order) or time.monotonic() - rx["at"] < 0.3:
            await asyncio.sleep(0.05)
        place(k)

    def release():
        """Held audio (synthesized before the final transcript) goes to the speaker, marks and all."""
        for off, k in held_marks:
            audio["marks"].append((audio["fed"] + off, sentences, k, shown, lambda k=k: secs(k)))
        held_marks.clear()
        feed(bytes(held)); held.clear()
        r = status["reply"]
        if r and r.get("committed_at") and not r.get("first_word"):
            r["first_word"] = time.monotonic() - r["committed_at"]

    def on_audio(m):
        k = order[min(mouth.got, len(order) - 1)]
        sizes[k] = sizes.get(k, 0) + len(m)
        rx["at"] = time.monotonic()
        for j in range(first, k):              # blocks-only sentences before this one show first
            if j not in marked and j not in order:
                place(j)
        if commit.is_set():
            if held:
                release()
            if k not in marked:
                marked.add(k); mark(sentences, k, shown, lambda k=k: secs(k))
            feed(m)
            r = status["reply"]
            if r and r.get("committed_at") and not r.get("first_word"):
                r["first_word"] = time.monotonic() - r["committed_at"]
        else:
            if k not in marked:
                marked.add(k); held_marks.append((len(held), k))
            held.extend(m)
    player = asyncio.create_task(mouth.receive(on_audio))

    async def on_commit():                     # an eager start: release what was synthesized before the final transcript
        await commit.wait()
        if held:
            release()
    committer = asyncio.create_task(on_commit())
    try:
        while True:
            while i >= len(sentences) and not gen_done.is_set() and not ctl["paused"].is_set():
                new.clear()
                await first_of(new.wait(), ctl["paused"].wait())
            if ctl["paused"].is_set():
                return i, False
            if i >= len(sentences):
                break
            try:
                said = ui.spoken(sentences[i][0])
                if not ui.sayable(said):       # only blocks to show: nothing for the mouth
                    waiters.append(asyncio.create_task(place_when_quiet(i)))
                    i += 1
                    continue
                order.append(i)
                await mouth.say(said)
            except (websockets.ConnectionClosed, OSError):      # the socket dropped mid-reply: one new mouth, carry on
                player.cancel()
                with contextlib.suppress(Exception):
                    await mouth.close()        # the dropped one
                mouth = await open_mouth()
                if mouth is None:
                    ui.warn("mouth lost mid-reply; the rest is text only")
                    await gen_done.wait()
                    await commit.wait()
                    for k in range(i, len(sentences)):
                        show(sentences, k, shown)
                    return len(sentences), True
                first, order = i, []           # the new mouth counts from here
                player = asyncio.create_task(mouth.receive(on_audio))
                continue
            i += 1
        with contextlib.suppress(websockets.ConnectionClosed, OSError):
            await mouth.finish()
        while not mouth.done() and not ctl["paused"].is_set() and not player.done():
            await asyncio.sleep(0.02)
        if ctl["paused"].is_set():
            return i, False
        await commit.wait()
        if held:
            release()
        for k in range(first, i):
            if k not in marked:                # no audio came for it (blocks only, or an empty sentence): at the end
                place(k)
        return i, True
    finally:
        player.cancel()
        committer.cancel()
        for w in waiters:
            w.cancel()
        if mouth:                              # None: lost mid-reply, and no new one
            await mouth.close()


def show(sentences, k, shown, secs=None):
    if k < len(sentences) and k not in shown:
        shown.add(k)
        text, first_of_block, blocks = sentences[k]
        asking = (pending["rule"] or pending["future"]) and pending["ask"] and text.strip() == pending["ask"]
        if asking:
            pending["ready"] = True            # the question is being asked: now a yes answers it
        for b in blocks:
            ui.block(b, colors=cfg.get("code_colors", True))
        if text:
            ui.me_line(text, first_of_block, live=bool(status["live"]), secs=secs)
        if asking and pending.get("options"):
            ui.choices(pending["options"])     # its answers, one per line under it: on screen, not said


async def reply(text, commit, ctl, fixed=False, handle=None, screen=None):
    """One spoken reply. Text streams from the brain into sentences; the mouth follows, and can be
    paused (a possible interruption) and resumed a sentence or two back. screen: Markdown for the screen
    only, after a fixed reply's words."""
    async with speaking:
        if handle:                             # now it is the one speaking: cut, pause and the state line follow it
            current.update(handle)
            status["reply"] = handle
        refresh()
        sentences, new, gen_done, shown = [], asyncio.Event(), asyncio.Event(), set()

        async def generate():
            buf, first, bol, pre = "", True, True, []    # bol: buf starts a line; pre: blocks shown before the next sentence

            def emit(sentence):
                nonlocal first, bol
                bol = sentence.endswith("\n")
                if sentence.strip() == "[skip]":       # not for claudio, or cut off mid-thought: say nothing
                    return
                if not ui.sayable(sentence):   # a blank line, or markup alone: nothing to say
                    return
                sentences.append((sentence, first, pre[:]))
                pre.clear()
                new.set()
                first = False

            def flush():
                """Blocks with nothing said after them: an item of their own, shown once the voice before them ends."""
                if pre:
                    sentences.append(("", first, pre[:]))
                    pre.clear()
                    new.set()

            def split(final=False):
                nonlocal buf, bol
                while True:
                    n = shown_block(buf, final) if bol else 0
                    if n is None:
                        return                 # maybe a table or a fence: wait for more
                    if n:
                        pre.append(buf[:n])
                        buf, bol = buf[n:], True
                        continue
                    m = next((m for m in SENTENCE.finditer(buf) if closed(buf[:m.end()]) or len(buf) > 400), None)
                    if not m:
                        break
                    emit(buf[:m.end()])
                    buf = buf[m.end():]
                if final and buf.strip():
                    emit(buf)
                    buf = ""
            try:
                if fixed:
                    for line in text.split("\n"):    # a list: one line, one sentence, each its own bullet
                        emit(line + "\n")
                    if screen:
                        pre.append(screen)
                        flush()
                    return
                async for d in brain.turn(text):
                    if isinstance(d, Question):
                        split(final=True)
                        flush()
                        first = True
                        emit(d.split("\n")[0] + "\n")     # said; show() knows it by its text and adds the answers
                        buf, first, bol = "", True, True
                        continue
                    if d is BLOCK_END:
                        split(final=True)
                        flush()                # a tool runs next: its table or code shouldn't wait for it
                        buf, first, bol = "", True, True
                        continue
                    buf += d
                    split()
                split(final=True)
                flush()
            finally:
                gen_done.set()
                new.set()

        gen = asyncio.create_task(generate())
        i = 0
        try:
            while True:
                if ctl["paused"].is_set():
                    refresh()
                    await ctl["resume"].wait()
                    ctl["resume"].clear()
                    ctl["paused"].clear()
                    at = ctl.pop("resume_at", None)
                    i = at if at is not None else max(0, i - 1)    # from the sentence that was playing, or the last one
                    while i > 0 and not ui.sayable(sentences[i][0]):
                        i -= 1                 # a blocks-only sentence has nothing to say again: the one before it
                i, finished = await speak_from(sentences, i, new, gen_done, ctl, commit, shown)
                if not finished:
                    continue
                while out and not ctl["paused"].is_set():     # the tail: audio still playing after the last sentence was sent
                    await asyncio.sleep(0.05)
                if ctl["paused"].is_set():
                    continue                   # paused during the tail: wait, then say the end again
                drained(0)                     # a mark at the very end (a closing table) shows before the marks are cleared
                break
        finally:
            if not gen.done():
                gen.cancel()
            while not gen.done():              # a second cut must not cancel the drain: the stream would go off by one
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await asyncio.shield(gen)
            clear_audio()
            r = status["reply"]
            if r and r.get("first_word") and not fixed:
                status["latency"] = (f"{r['first_word']:.1f} s", time.monotonic() + 6)
                if r["first_word"] > 3:
                    ui.warn(f"slow: {r['first_word']:.1f} s to first word")
                r["first_word"] = None
            refresh()


def on_out(outdata, frames, t, status_):
    n = len(outdata)
    with OUT:                                  # a cut between the copy and the delete would count a block twice
        b = bytes(out[:n]); del out[:n]
        audio["played"] += len(b)
    outdata[:len(b)] = b
    outdata[len(b):] = b"\x00" * (n - len(b))   # the showing happens on the loop (see shower)


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).split()


def fold(s):
    """Letters and digits only, accents dropped: "Zoé" is "zoe", "R2-D2" and "R2 D2" are "r2d2"."""
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if c.isascii() and c.isalnum())


def addressed(said, name):
    """The turn with its leading name dropped, or None when it doesn't start with the name: "Nyx, slash mute"."""
    want, got = fold(name), ""
    for i, ch in enumerate(said):
        if got == want:                            # the name is read: what follows is the turn
            if fold(ch):
                return None                        # "Nyxie": a longer word, not the name
            return re.sub(r"^\W+", "", said[i:]).strip() or said   # \W keeps "Élodie" whole
        got += fold(ch)
        if not want.startswith(got):
            return None
    return said if got == want else None           # the name alone: kept, so the brain skips it


def address(said, name, called):
    """Under address_me: (the turn for the brain, or None; whether it was the name alone). A turn that starts
    within a few seconds of the name alone (called) is for it unnamed: "Roger." … "What's the sequencer doing?"."""
    rest = addressed(said, name)
    if rest is not None and fold(rest) == fold(name):
        return None, True
    return (said if rest is None and called else rest), False


def backchannel(said):
    words = norm(said)
    return len(words) < 2 or all(w in BACKCHANNEL for w in words)


def intent(said):
    """What an answer to claudio's permission question means: yes, always, no, a question back, or unclear. Read
    from the last part that says yes or no, so "you don't need to spell it. So yes, you are allowed" is a yes."""
    parts = [p for p in re.split(r"(?<=[.!?;])\s+|\.\.\.+", said.strip()) if p.strip()]
    def words(p):                      # phrases whose "no" or "not" means yes, read before the no words
        p = " ".join(norm(p))
        for a, b in (("dont ask again", "always"), ("dont ask", "always"), ("no problem", "fine"), ("no worries", "fine"),
                     ("dont mind", "fine"), ("dont worry", "fine"), ("why not", "fine"), ("go ahead", "fine"),
                     ("do it", "fine"), ("please do", "fine"), ("go for it", "fine")):
            p = re.sub(rf"\b{a}\b", b, p)
        return ["fine"] if p == "please" else p.split()
    for part in reversed(parts):
        w = words(part)
        if any(x in NO for x in w):
            return "no"
        last = lambda words: max((i for i, x in enumerate(w) if x in words), default=-1)
        hedge, yes = last(("but", "wait", "hold", "hang", "later", "what", "why", "how", "first", "read")), last(YES + ("always",))
        if hedge > yes or (part is parts[-1] and part.rstrip().endswith("?")):   # "but just that one, yes": a yes
            return "question"
        if "always" in w:
            return "always"
        if yes >= 0:
            return "yes"
    return "question" if said.rstrip().endswith("?") else "unclear"


def echoed(answered, ws, kind, now):
    """A session's Reply and the end (Stop) of the turn that sent it say the same thing: the second of the two,
    within a minute, is not narrated again. answered: workspace -> (time, kind) of the last one narrated."""
    t, k = answered.get(ws, (0, kind))
    if k != kind and now - t < 60:
        return True
    answered[ws] = (now, kind)
    return False


def described(tool, tool_input, rule, what):
    """What claudio asks about, as said: "run gh pr create", "open claudio-vert.vercel", never a whole command."""
    if rule and rule.startswith("/"):
        return f"go into the {os.path.basename(rule)} folder"
    cmd = str(tool_input.get("command", "")) if tool == "Bash" else ""
    if m := re.match(r'\s*cmux agent message\s+(?:"([^"]+)"|(\S+))', cmd):   # a send: what, and to which session
        to = m[1] or m[2]
        to = next((w for sid, (w, _, _, full) in surfaces.items() if to.upper() in (sid, full.upper())), "a session")
        said = re.findall(r'"((?:[^"\\]|\\.)*)"', cmd)
        words = re.sub(r"^\[spoken by the user, transcribed by claudio\]\s*", "", said[-1] if said else "").split()
        if len(words) > 25:                    # too long to hear: its start, the rest is on screen ("read it all" asks)
            return f'send "{" ".join(words[:12])}…" and {len(words) - 12} more words to {to}'
        return f'send "{" ".join(words)}" to {to}' if words else f"send a message to {to}"
    if rule:
        return what.removeprefix("to ")
    if tool == "Bash":
        cmd = str(tool_input.get("command", ""))
        site = ui.URL.search(cmd)
        words = [w for w in cmd.split() if re.fullmatch(r"[a-z][\w.-]*", w)][:2]
        if words[:1] == ["open"] and site:
            return f"open {site[1].rsplit('.', 1)[0]}"
        return f"run `{' '.join(words) or 'a command'}`" + (f" for {site[1].rsplit('.', 1)[0]}" if site else "")
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    return f"use {tool} on {os.path.basename(path)}" if path else f"use {tool}"


async def shower_typed():
    while True:
        await asyncio.sleep(0.05)
        drained(0)


async def main():
    global cfg, surfaces
    restarted = os.environ.pop("CLAUDIO_RESTARTED", None)   # run() started this one over, with new code
    cfg = config.load()
    ui.layout["split"] = cfg["layout"] == "split"
    for w in config.WARNINGS:
        ui.warn(w)
    if not cfg["deepgram_api_key"]:
        raise SystemExit("No Deepgram key. Run `claudio setup`, or export DEEPGRAM_API_KEY.")
    if cfg["mouth"] == "local":
        try:
            voices = kokoro(cfg["local_model"]).get_voices()
        except OSError as e:
            raise SystemExit(str(e))
        if cfg["local_voice"] not in voices:
            raise SystemExit(f"local_voice {cfg['local_voice']!r} is not a Kokoro voice; one of: {', '.join(sorted(voices))}")
    surfaces = sessions()
    typed = os.environ.get("CLAUDIO_TEXT")
    aec = None if typed else helper()
    rate = {"in": OUT_RATE if aec else IN_RATE}
    if not typed:                # a typed turn runs under the doctor's own banner; redrawing would clear its checks
        ui.banner(name=cfg["name"], facts={"orchestrator": cfg["orchestrator"] or "-", "brain": f"{cfg['model']}/{cfg['effort']}",
                         "style": cfg["style"],
                         "voice": (f"elevenlabs {cfg['elevenlabs_voice'][:8]}" if cfg["mouth"] == "elevenlabs" and cfg["elevenlabs_api_key"]
                                   else f"local {cfg['local_voice']}" if cfg["mouth"] == "local"
                                   else ui.short_voice(cfg["voice"])),
                         "echo cancel": "on" if aec else "off",
                         "memory": "on" if remembered_session() else "fresh",
                         **{k.replace("_", " "): ("on" if v is True else "off" if v is False else v)   # the rest, as set
                            for k, v in cfg.items() if k in config.DEFAULTS and k not in config.SECRETS
                            and k not in ("orchestrator", "model", "effort", "style", "voice", "memory",
                                          "elevenlabs_voice", "local_voice")},
                         "permissions": "off" if status["skip"] else "on"},
                  hints="Enter cuts · Ctrl-C quits · claudio setup")
        ui.to_bottom()          # now, so "warming up the brain" is at the bottom too; before the key reader, which would
                                # take the terminal's answer and leave this read blocked
    config.migrate_allow()
    await brain.start()
    status["warming"] = True
    status["live"] = console.status("[dim]warming up the brain…[/]")
    if not typed:                              # the state line itself, rule and all: "listening" takes its place, no jump
        ui.attach(status["live"])
    status["live"].start()
    refresh()                                  # drawn as listening will be: the level bar, then the words
    try:
        async for _ in brain.turn("Say only: ready."):
            pass
    except BaseException:
        status["live"].stop()
        raise
    status["warming"] = False
    if typed:                                  # a doctor turn prints whole, with no state line
        status["live"].stop()
        status["live"] = None

    if typed:
        with sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=OUT_RATE // 50, callback=on_out):
            ui.you(typed)
            ev = asyncio.Event(); ev.set()
            showing = asyncio.create_task(shower_typed())
            await reply(typed, ev, new_ctl())
            showing.cancel()
        return await brain.stop()

    loop = asyncio.get_running_loop()
    voices = asyncio.create_task(asyncio.to_thread(config.fetch_aura, cfg["deepgram_api_key"]))   # for "slash voice"; kept so it isn't collected
    eleven = cfg["elevenlabs_api_key"] and asyncio.create_task(asyncio.to_thread(config.fetch_elevenlabs, cfg["elevenlabs_api_key"]))
    mic = asyncio.Queue()
    mic_up = asyncio.Event()      # the first mic audio: the audio route is up, so what is played is heard
    helper_holder = {"proc": None}  # the echo-cancelling helper, when it runs
    fallback_streams = {"streams": None}   # the plain mic and speaker, if the helper died
    ears = {"ws": None}            # the Flux socket, when connected
    later = {"resume": None}       # the timer that resumes a paused reply nobody interrupted after all
    called = {"until": 0.0, "turn": False, "told": False, "name": ""}   # under address_me: a turn begun before until needs no name; the name alone, as heard; this turn did

    def on_mic(indata, frames, t, status_):
        loop.call_soon_threadsafe(mic.put_nowait, bytes(indata))

    def live():
        t = current["task"]
        return t is not None and not t.done() and not t.cancelling()   # a cut reply still draining the brain is gone

    def paused():
        return live() and current["ctl"]["paused"].is_set()

    def idle():
        """Nothing said, asked or being heard: a restart would cut nothing."""
        return (not live() and not brain.busy and not status.get("in_turn") and not status.get("typed")
                and not pending["rule"] and not pending["future"] and not pending["press"] and not out)

    def drop_audio():
        clear_audio()
        if helper_holder["proc"]:
            helper_holder["proc"].send_signal(signal.SIGUSR1)     # drop what the helper has queued

    def cut(why="cut"):
        if later["resume"]:
            later["resume"].cancel()
        if live():
            current["task"].cancel()
            drop_audio()
            if why:
                console.print()
                ui.note(why)

    def pause():
        if live() and not paused():
            playing = audio["marks"][0][2] if audio["marks"] else None    # the first sentence not yet playing
            current["ctl"]["resume_at"] = None if playing is None else max(0, playing - 1)
            current["ctl"]["paused"].set()
            drop_audio()
            later["resume"] = asyncio.create_task(resume_later())

    async def resume_later():
        await asyncio.sleep(3)
        resume()                    # whatever that was, it was not a turn

    def resume():
        if later["resume"]:
            later["resume"].cancel()
        if paused():
            current["ctl"]["resume"].set()

    latest = {"handle": None}      # the newest reply asked for, speaking or queued; what a final transcript commits

    def start(text, committed, event=False, fixed=False, screen=None):
        if not event:
            if live():
                cut("replaced" if current["commit"].is_set() else None)    # an unheard early guess goes quietly
            queued = latest["handle"]
            if queued and not queued["task"].done() and queued["task"] is not current["task"]:
                queued["task"].cancel()        # an eager reply still waiting behind the drain: gone too
        ev = asyncio.Event()
        if committed:
            ev.set()
        ctl = new_ctl()
        handle = {"text": text, "commit": ev, "ctl": ctl, "paused": ctl["paused"],
                  "committed_at": time.monotonic() if committed else None}
        handle["task"] = asyncio.create_task(reply(text, ev, ctl, fixed=fixed, handle=handle, screen=screen))
        if not event:
            latest["handle"] = handle
        if not live():                         # otherwise it queues behind the speaking reply and claims `current` on its turn
            current.update(handle)
            status["reply"] = handle
        refresh()


    recent = {"key": None, "at": 0.0}       # the command last refused with a question in reply: a yes can run it

    async def ask(tool, tool_input):
        """A tool use the rules refuse: claudio, not the brain, asks the user, inside the reply that wants it, while
        the call waits, so nothing the brain reads can say yes. yes: this once. always: from now on, as a rule claudio
        made (never sh -c or a bare Write: those are once only). no, a cut or a minute's silence: not run. Unclear:
        asked once more. A question back ("what would that do?") goes to the brain, and a yes to its answer runs that
        same command without asking again."""
        rule, what = config.rule_for(tool, tool_input)
        action = described(tool, tool_input, rule, what)
        key = (tool, json.dumps(tool_input, sort_keys=True))
        if recent["key"] == key and time.time() - recent["at"] < 120 and intent(brain.text) in ("yes", "always"):
            recent["key"] = None
            ui.note(f"allowed once: {rule or action}")
            return PermissionResultAllow()     # they asked about it, heard the answer, and said yes
        if tool == "Bash" and tool_input.get("command"):
            ui.block(f"```sh\n{tool_input['command']}\n```", colors=False)   # the whole of it, not just its first words
        elif tool_input.get("file_path"):
            ui.note(f"{tool} {tool_input['file_path']}")
        question = f"May I {action}?\n" + ("- **1** Yes, this once\n- **2** Always\n- **3** No" if rule
                                            else "- **1** Yes, this once\n- **2** No")   # a key answers too
        ready = False                          # until it is on screen: an "okay" to the reply before it is no yes
        for _ in range(2):
            said = await asked(question, ready)
            answer = intent(said or "")
            if answer != "unclear" or said is None:
                break
            question, ready = "Sorry, yes or no?", True   # they are answering already: take the next words
        if said is None or answer == "no":
            ui.note(f"not allowed: {rule or action}")
            return PermissionResultDeny(message="The user said no, or nothing, so it did not run. Say so in a few words.")
        if answer == "always" and rule:
            config.allow(rule)                 # for later runs; this one has it from the update below
            ui.note(f"allowed {rule}")
            m = re.fullmatch(r"([^(]+)(?:\((.*)\))?", rule)
            return PermissionResultAllow(updated_permissions=[
                PermissionUpdate(type="addDirectories", directories=[rule], destination="session") if rule.startswith("/")
                else PermissionUpdate(type="addRules", rules=[PermissionRuleValue(m[1], m[2])], behavior="allow",
                                      destination="session")])
        if answer in ("yes", "always"):
            ui.note(f"allowed once: {rule or action}")
            return PermissionResultAllow()
        recent.update(key=key, at=time.time())
        return PermissionResultDeny(message=f"Not run yet: asked, the user said \"{said}\". Answer that in a few words, or in full if "
                                            "they asked to hear it all; "
                                            "if they then say yes, run the same command again.")

    async def asked(question, ready):
        """Say the question in the reply speaking now; the user's words, or None for a cut or a minute's silence."""
        future = loop.create_future()
        said, _, options = question.partition("\n")
        before = {k: pending[k] for k in ("ask", "options", "ready")}   # a session's prompt still waiting: back after
        pending.update(future=future, ask=said, options=options, ready=ready)
        brain.say(question)
        try:
            return await asyncio.wait_for(future, 60)
        except asyncio.TimeoutError:
            return None
        finally:
            pending["future"] = None
            if pending["ask"] == said:         # not replaced meanwhile by a session's prompt
                pending.update(before if pending["rule"] else {"ask": "", "options": "", "ready": False})

    brain.on_ask = ask

    def answer(said):
        """The turn after the skip question: yes turns the checks off. The note to show when it was the answer;
        None for anything else, which drops the question and is an ordinary turn."""
        words = norm(said)
        if not pending["rule"] or not pending["ready"]:   # not yet asked: an "okay" to the reply before it is no yes
            return None
        if pending["press"]:                   # a session's permission prompt: read by intent, like claudio's own
            surface, keys, at = pending["press"]
            meant = intent(said)
            if meant == "question" and time.time() - at < 120:
                return None                    # the brain answers it; a yes after still counts, for two minutes
            pending.update(rule=None, press=None)
            meant = "yes" if meant == "always" and "always" not in keys else meant
            if meant not in keys:
                return None                    # anything else: an ordinary turn; the prompt waits on its keyboard
            asyncio.create_task(press(surface, keys, meant))
            return {"yes": "allowed once", "always": "always allowed", "no": "not allowed"}[meant]
        pending["rule"] = None
        meant = intent(said)                   # the whole answer, so "please don't" or "ok wait" is no yes
        if meant == "yes" and len(words) <= 3:
            asyncio.create_task(skipping(True))
            return "no permission checks until you quit"
        if meant == "no":
            return f"not allowed: {SKIP}"
        return None

    async def press(surface, keys, meant):
        """Answer a session's permission prompt by typing in its pane, only while that same prompt still shows."""
        def go():
            if config.permission_keys(pane(surface, 18)) != keys:
                return False
            how = ["send-key", "escape"] if meant == "no" else ["send", keys[meant]]   # a digit is text to cmux, not a key
            return subprocess.run([CMUX, how[0], "--surface", surface, "--force", how[1]],   # --force: into a dialog
                                  capture_output=True, timeout=4).returncode == 0
        try:
            ok = await loop.run_in_executor(None, go)
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if not ok:
            ui.warn("that prompt is no longer on screen; nothing was pressed")

    async def skipping(on):
        """Permission checks off (a yes to /permissions skip) or on again: a brain that has them, same memory."""
        status["skip"] = on
        await brain.restart()
        start("Permission checks are off until you quit." if on else "Permission checks are back on.",
              committed=True, fixed=True)

    def set_mute(on):
        status["muted"] = on
        if on:
            cut(None)
        ui.note("muted · say /unmute" if on else "unmuted")
        start("Muted." if on else "I'm listening again.", committed=True, fixed=True)

    async def fresh_start():
        """/clear: forget the conversation and restart the brain on a blank session."""
        with contextlib.suppress(OSError):
            os.unlink(SESSION)
        await brain.restart()
        ui.rule("fresh start")
        start("Fresh start.", committed=True, fixed=True)

    def pick(arg, voices):
        """A voice by its features, "a british woman": the one voice that has them, or None once the ones that
        might are on screen. On screen only: 41 names read aloud is too long."""
        want, found = config.like(arg, voices)
        if len(found) == 1:
            return found[0]
        if found:
            said = f"{len(found)} voices are {' and '.join(want)}:"
        elif want:
            said = f"No voice is {' and '.join(want)}. The voices are as follows:"
        elif len(arg.split()) == 1:
            said = f"{arg.capitalize()} is not recognised as a voice. The voices are as follows:"
        else:                                  # a sentence, or nothing: just the list
            said = "The voices are as follows:"
        rows = [config.described(n, voices[n]) for n in found or voices]
        cols = ["Voice", "Accent", "Age", "Gender", "Sounds"]
        if not any(r[2] for r in rows):        # Kokoro's names give no age
            cols, rows = cols[:2] + cols[3:], [r[:2] + r[3:] for r in rows]
        start(said, committed=True, fixed=True,   # a table: several criteria, side by side
              screen="\n".join(f"| {' | '.join(r)} |" for r in [cols, ["---"] * len(cols), *rows]))
        return None

    def slash(words):
        """Spoken slash commands: "slash clear", "slash model sonnet"… True when handled."""
        parsed = parse_slash(words)
        if not parsed:
            return False
        cmd, arg = parsed
        ui.note(f"/{cmd.replace('_', ' ')} {arg}".strip())
        if cmd == "voice" and (cfg["mouth"] == "local" or cfg["mouth"] == "elevenlabs" and cfg["elevenlabs_api_key"]):
            cmd = f"{cfg['mouth']}_voice"      # slash voice: the voice of the mouth that speaks
        if cmd not in ("clear", "stop"):
            cut(None)                          # a command over a reply stops it quietly; the note says why
        key = {"colors": "code_colors", "colours": "code_colors", "address": "address_me"}.get(cmd, cmd)
        if key in config.DEFAULTS and (arg or cmd in ("colors", "colours", "layout", "address")
                                       or isinstance(config.DEFAULTS[key], bool)) and (src := config.overridden(key)):
            start(f"{key.replace('_', ' ').capitalize()} is set by {src} here, so I left it.", committed=True, fixed=True)
            return True                        # saved, it would change nothing here, and every other project
        if cmd == "clear":
            cut("cleared")
            asyncio.create_task(fresh_start())
        elif cmd in ("mute", "unmute"):
            set_mute(cmd == "mute")
        elif cmd == "stop":
            cut("stopped")
        elif cmd == "style" and arg in STYLES:
            config.set_key("style", arg)
            brain.changed.set()
        elif cmd == "style":
            said = f"I don't know style {arg}. " if arg else "Style is "     # "slash style" alone: just the choices
            start(f"{said}{', '.join(STYLES)}.", committed=True, fixed=True)
        elif cmd == "voice":
            value, why = config.check("voice", arg.replace(" ", "-")) if arg else (None, "none")   # "elektra" is electra
            if why:                            # "banana", "a british woman", or nothing: by its features, or all of them
                if not (n := pick(arg, config.AURA)):
                    return True
                value = f"aura-2-{n}-en"
            name = ui.short_voice(value)
            config.set_key("voice", value)
            brain.changed.set()
            cfg["voice"] = value               # so the confirmation already speaks in it
            start(f"{name.capitalize()} from now on.", committed=True, fixed=True)
        elif cmd in ("model", "effort") and not arg:   # "slash effort" alone: the choices
            start(f"{cmd.capitalize()} is {', '.join(config.MODELS if cmd == 'model' else config.EFFORTS)}.",
                  committed=True, fixed=True)
        elif cmd in ("model", "effort"):
            choices = config.MODELS if cmd == "model" else config.EFFORTS
            value = next((w for w in arg.split() if w in choices), arg.replace(" ", "-"))   # "sonnet please"
            if (cmd == "model" and value not in config.MODELS) or (cmd == "effort" and value not in config.EFFORTS):
                choices = config.MODELS if cmd == "model" else config.EFFORTS
                start(f"I don't know {cmd} {arg}. Choose {', '.join(choices)}.", committed=True, fixed=True)
                return True
            config.set_key(cmd, value)
            brain.changed.set()
        elif cmd in ("colors", "colours"):     # "slash code colors off"; alone, it flips them
            said = next((w for w in arg.split() if w in config.TRUE + config.FALSE), None)    # "off please" is off
            on = said in config.TRUE if said else not cfg["code_colors"]
            config.set_key("code_colors", on)          # the reload confirms it: ⚙ code_colors → False
            start(f"Code colours {'on' if on else 'off'}.", committed=True, fixed=True)
        elif cmd == "address":                 # "slash address me on"; alone, it flips it
            said = next((w for w in arg.split() if w in config.TRUE + config.FALSE), None)
            on = said in config.TRUE if said else not cfg["address_me"]
            config.set_key("address_me", on)
            start(f"Only turns that start with {cfg['name']} now." if on else "Every turn counts now.",
                  committed=True, fixed=True)
        elif cmd == "local_voice" and arg.replace(" ", "_") not in config.KOKORO:   # "british woman", "af hart", or nothing
            if n := pick(arg, config.kokoro_voices()):
                config.set_key("local_voice", n)
                start(f"Local voice {n}.", committed=True, fixed=True)
        elif cmd == "elevenlabs_voice" and not re.fullmatch(r"[A-Za-z0-9]{20}", arg):   # a name or features, not an id
            if not config.ELEVEN:
                start("I don't have the ElevenLabs voices: it needs the ElevenLabs key, and ElevenLabs reachable at the start.",
                      committed=True, fixed=True)
            elif n := arg.lower() if arg.lower() in config.ELEVEN else pick(arg, config.ELEVEN):
                config.set_key("elevenlabs_voice", config.ELEVEN_IDS[n])
                start(f"{n.capitalize()} from now on.", committed=True, fixed=True)
        elif cmd in SETTINGS and cmd not in COMMANDS:   # every other setting: "slash barge in off", "slash eot 0.8"
            label, kind = cmd.replace("_", " ").replace("eot", "EOT"), type(config.DEFAULTS[cmd])
            label = label[0].upper() + label[1:]
            if kind is bool:                   # on or off; alone, it flips
                said = next((w for w in arg.split() if w in config.TRUE + config.FALSE), None)
                value = said in config.TRUE if said else not cfg[cmd]
            elif not arg:                      # "slash narrate" alone: what it is, and the choices
                choices = f"; choose {', '.join(config.CHOICES[cmd])}" if cmd in config.CHOICES else ""
                start(f"{label} is {cfg[cmd]}{choices}.", committed=True, fixed=True)
                return True
            elif cmd in config.CHOICES:        # "handed off" is handed-off
                value = next((c for c in config.CHOICES[cmd] if c.replace("-", " ") in arg), arg)
            elif kind in (int, float):         # "2500 please"
                value = next((w for w in arg.split() if re.fullmatch(r"\d+(\.\d+)?", w)), arg)
            elif cmd == "orchestrator":        # heard lower case: the workspace as cmux spells it
                value = next((w for w in config.workspaces() if w.lower() == arg), arg)
            else:                              # "flux general multi", "af heart": as the setting spells it
                value = arg.replace(" ", {"ears": "-", "local_voice": "_"}.get(cmd, " "))
            value, why = config.check(cmd, value)
            if why:
                start(f"{why.replace('_', ' ')}.", committed=True, fixed=True)
                return True
            config.set_key(cmd, value)         # the reload applies it, as `claudio set` would
            shown = ("on" if value else "off") if kind is bool else value
            start(f"{label} {shown}.", committed=True, fixed=True)
        elif cmd == "layout":                  # "slash layout split"; alone, it flips it
            said = next((w for w in arg.split() if w in config.CHOICES["layout"]), None)
            new = said or ("inline" if cfg["layout"] == "split" else "split")
            config.set_key("layout", new)              # the reload applies it
            start(f"Layout {new}.", committed=True, fixed=True)
        elif cmd == "name":                    # "slash name roger", "slash my name is roger"
            value, why = config.check("name", re.sub(r"^(?:is|to|as|be)\s+", "", arg).title()) if arg else (None, "")
            if why or not arg:                 # "slash name" alone, or five words: say what it is now
                start(f"{why + '. ' if why else ''}My name is {cfg['name']}. Say slash name and a new one.",
                      committed=True, fixed=True)
                return True
            config.set_key("name", value)      # the reload restarts the brain, which says "Back, as Roger."
            brain.changed.set()
        elif cmd == "permissions" and any(w in words.split() for w in ("skip", "off", "dangerously")):   # wherever said
            ask = "Skip every permission check until you quit? The brain could then run anything, unasked."
            pending.update(rule=SKIP, ask=ask, options="- **1** Yes\n- **2** No", ready=False)   # only a yes right after it turns them off
            start(ask, committed=True, fixed=True)
        elif cmd == "permissions":
            if status["skip"]:
                asyncio.create_task(skipping(False))
            else:
                start("Permission checks are on. Say slash permissions skip to turn them off until you quit.",
                      committed=True, fixed=True)
        elif cmd == "status":
            start(f"Status:\n- Orchestrator {cfg['orchestrator'] or 'none'}.\n- Brain {cfg['model']} at {cfg['effort']} effort.\n"
                  f"- Voice {ui.short_voice(cfg['voice'])}.\n- Memory {'on' if cfg['memory'] else 'off'}.", committed=True, fixed=True)
        elif cmd == "help":
            start(SLASH_HELP, committed=True, fixed=True)
        elif cmd == "restart":                 # once "Restarting." is said, and nothing else is (watch_config)
            start("Restarting.", committed=True, fixed=True)
            status["restart_asked"] = True
        elif cmd in ("quit", "exit"):
            start("Bye.", committed=True, fixed=True)
            said = latest["handle"]["task"]

            async def leave():              # once it is said, as Ctrl-C would
                with contextlib.suppress(asyncio.CancelledError):
                    await said
                if work["task"]:
                    work["task"].cancel()
            asyncio.create_task(leave())
        else:
            start(f"I don't know slash {cmd}. {SLASH_HELP}", committed=True, fixed=True)
        return True

    async def on_event(reader, writer):
        """A session's hook reported in. Narrate handed-off work, permission prompts and questions."""
        global surfaces
        line = await reader.readline()
        writer.close()
        try:
            ev = json.loads(line)
        except ValueError:
            return
        if ev.get("session") == brain.session_id:
            return
        sid = (ev.get("surface") or "")[:8]
        if sid and sid not in surfaces:          # none: a session outside cmux, never one of ours
            surfaces = await loop.run_in_executor(None, sessions)   # one that appeared after we started; cmux can take seconds
        ws, *_, full = surfaces.get(sid, (None, None, None, sid))     # full: the id cmux takes
        if not ws:
            return
        if status["muted"]:
            return                         # muted: nothing spoken, not even the sessions
        keys = (ws, str(ev.get("surface") or "").upper())   # by title, or by the surface id of a session newer than the list
        when, asked = next((brain.handoffs[k] for k in keys if k in brain.handoffs), (0, ""))
        if cfg["narrate"] == "none":
            return
        handed = when > time.time() - 1800
        if ev["event"] == "Stop" and ev.get("text") and (handed or cfg["narrate"] == "all"):
            if echoed(brain.answered, ws, "Stop", time.time()):
                return                     # its reply already said it
            for k in keys:                 # answered: a later turn there is not this request's
                brain.handoffs.pop(k, None)
            text = (f"[event] {ws} finished a turn on your request \"{asked}\". Its last message:\n{ev['text']}" if handed
                    else f"[event] {ws} finished a turn. Its last message:\n{ev['text']}")
        elif ev["event"] == "Notification" and ev.get("kind") == "permission_prompt":
            screen = await loop.run_in_executor(None, pane, full, 18)
            keys = config.permission_keys(screen)
            ours = keys and not pending["future"] and (not pending["rule"] or pending["press"])   # not over another question
            text = (f"[event] {ws} asks for permission: {ev.get('message')}\nIts screen shows:\n{screen}\n"
                    + ("Claudio asks the user yes or no right after you." if ours else "The user answers on its keyboard."))
        elif ev["event"] == "AskUserQuestion" and ev.get("questions"):
            text = f"[event] {ws} (surface {full}) asks you to choose:\n{json.dumps(ev['questions'])}"
        else:
            return
        ui.event(ws, ev["event"], asked if ev["event"] == "Stop" else "")
        if ev["event"] == "Notification" and ours:   # its prompt as the pane shows it, not as the brain sums it up
            ui.block("```\n" + "\n".join(l.rstrip() for l in screen.splitlines() if l.strip()) + "\n```", colors=False)
        start(text, committed=True, event=True)
        if ev["event"] == "Notification" and ours:   # then claudio asks, and types the answer into that pane
            ask = f"Allow it for {ws}?"
            options = "- **1** Yes\n" + ("- **2** Always\n- **3** No" if "always" in keys else "- **2** No")
            pending.update(rule=f"{ws}'s permission", ask=ask, options=options, ready=False, press=(full, keys, time.time()))
            start(ask, committed=True, event=True, fixed=True)

    def flux_url():
        return (f"wss://api.deepgram.com/v2/listen?model={cfg['ears']}&encoding=linear16&sample_rate={rate['in']}"
                f"&eot_threshold={cfg['eot']}&eager_eot_threshold={cfg['eager_eot']}&eot_timeout_ms={cfg['eot_timeout_ms']}"
                f"&keyterm={urllib.parse.quote(cfg['name'])}")    # so an odd name is heard as itself

    def learned():
        """The rules in learned.md, as a set of lines."""
        try:
            return set(open(config.LEARNED).read().splitlines())
        except OSError:
            return set()

    def mtime(path):
        """When the file last changed, or None while it is missing (moved aside, being replaced)."""
        try:
            return os.path.getmtime(path)
        except OSError:
            return None

    async def watch_config():
        global cfg
        stamp = mtime(config.CONF)
        persona = mtime(config.PROMPT)
        rules = learned()
        access = (mtime(config.SETTINGS), mtime(config.MCP))
        shipped, code, code_at = mtime(config.PACKAGED_PROMPT), code_stamp(), None
        last = dict(cfg)                       # the file as last loaded: what a change is told against
        while True:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(brain.changed.wait(), 1.0)
            brain.changed.clear()
            await asyncio.sleep(0.2)          # let `claudio set` finish writing
            now = mtime(config.PACKAGED_PROMPT)
            if now is not None and now != shipped:        # claudio's own persona, updated: new brain, same memory
                shipped = now
                ui.note("claudio's prompt changed; brain restarting")
                await brain.restart()
            now = code_stamp()
            if now != code:                    # claudio's code changed: wait for the last file of the change
                code, code_at = now, time.monotonic()
            if (code_at and time.monotonic() - code_at > 2 or status.get("restart_asked")) and idle():
                status["restart"] = "code" if code_at else "asked"   # once nothing is said or asked: run() re-runs it
                work["task"].cancel()
                return
            now = mtime(config.PROMPT)
            if now is not None and now != persona:        # the persona was edited: new brain, same memory
                persona = now
                ui.note("persona changed; brain restarting")
                await brain.restart()
                start("[event] Your persona prompt was just edited and you were restarted with it. "
                      "Say in a few words that you are back.", committed=True, event=True)
            now = learned()
            if rules - now:                    # a rule dropped (unlearn, an edit): a brain without it, after this turn;
                ui.note("learned rules changed; brain restarting")   # one added it knows already, so no restart
                await brain.restart()
            rules = now
            now = (mtime(config.SETTINGS), mtime(config.MCP))
            if now != access:                  # settings.json or mcp.json edited: a brain that has them
                ours = now[0] == config.written and now[1] == access[1]   # claudio's own "always": the brain has it
                access = now
                if not ours:
                    ui.note("access changed; brain restarting")
                    await brain.restart()
            now = mtime(config.CONF)
            if now is None or now == stamp:
                continue
            stamp = now
            new = config.load()
            for w in config.WARNINGS:
                ui.warn(w)
            restart = any(new[k] != cfg[k] for k in ("model", "effort", "style", "name"))
            renamed = new["name"] != cfg["name"]
            re_ear = any(new[k] != cfg[k] for k in ("ears", "eot", "eager_eot", "eot_timeout_ms", "name"))
            if not new["push_to_talk"]:
                status["gate_open"] = True     # off: the mic is open again
            diff = ", ".join(f"{k} → {ui.short_voice(str(new[k]))}" for k in config.DEFAULTS
                             if k not in config.SECRETS and new[k] != last[k])    # not cfg: a slash voice set it early
            cfg, last = new, dict(new)
            ui.layout["split"] = cfg["layout"] == "split"
            if diff or restart:
                ui.setting(f"{diff or 'settings reloaded'}{'  ·  brain restarting' if restart else ''}")
            if re_ear and ears["ws"]:
                asyncio.create_task(ears["ws"].close())   # the listener reconnects with the new ears
            if restart:
                await brain.restart()
                start(f"[event] You were just restarted with model {cfg['model']} at effort {cfg['effort']}, "
                      f"style {cfg['style']}{', and your name is now ' + cfg['name'] if renamed else ''}. Say only that "
                      f"you're back with it, in two to four words, such as "
                      + (f"'Back, as {cfg['name']}.'" if renamed else f"'Back, on {cfg['style']}.' or 'Back on {cfg['model']}.'"),
                      committed=True, event=True)

    async def brain_watch():
        delay = 1
        while True:
            dead = brain.dead
            await dead.wait()
            await asyncio.sleep(0.1)
            if brain.expected_exit or brain.dead is not dead:
                continue
            ui.warn("the brain died; restarting it")
            why = ("You just crashed and were restarted. Say in a few words that you are back, "
                   "and ask the user to repeat what they said last if they were mid-request.")
            async with brain.lock:
                await brain.stop()             # a reader that failed on one bad message leaves the CLI running
                try:
                    await brain.start()
                except Exception as e:         # it would not start (a broken settings.json…): again, slower each time
                    ui.warn(f"the brain didn't start ({type(e).__name__}); trying again in {delay}s")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30)
                    continue
            delay = 1
            start(f"[event] {why}", committed=True, event=True)

    status["gate_open"] = not cfg["push_to_talk"]   # push to talk: Enter opens the mic until your turn ends

    async def send_mic():
        while True:
            b = await mic.get()
            mic_up.set()
            ws = ears["ws"]
            if ws is None:
                continue
            # barge-in off: deaf only while a reply your turn has committed is playing, never during an
            # eager start, or the rest of what you are saying would be lost
            answering = live() and current["commit"].is_set()
            if (answering and not cfg["barge_in"] and not pending["future"]) or not status["gate_open"]:   # asking: hear the answer
                b = b"\x00" * len(b)
            else:
                peak = max(abs(x) for x in array.array("h", b)[::8]) if len(b) >= 16 else 0
                status["level"] = max(peak, status["level"] * 0.8)     # a quick rise, a slow fall
            with contextlib.suppress(websockets.ConnectionClosed):
                await ws.send(b)

    def heard(ev):
        said = ev.get("transcript", "").strip()
        shown = said                       # as heard, name and all; the brain gets said, the name dropped
        words = " ".join(norm(said))
        if ev["event"] in ("StartOfTurn", "EndOfTurn"):
            status["in_turn"] = ev["event"] == "StartOfTurn"   # the user is talking: no restart under them
        if ev["event"] == "StartOfTurn":
            called["turn"] = time.monotonic() < called["until"]   # begun soon after the name alone, or a turn for me
        if cfg["address_me"] and said and ev["event"] in ("EagerEndOfTurn", "EndOfTurn"):
            rest, alone = address(said, cfg["name"], called["turn"])
            if called["turn"] and called["name"] and not alone and addressed(said, cfg["name"]) is None:
                shown = f"{called['name']} {shown}"   # "Roger?" … "can you tell me": one line, as it was said
            if ev["event"] == "EndOfTurn":
                called["turn"], called["name"] = False, ""
                if alone:                          # its line waits for the turn it opens
                    ui.note("listening")
                    called["until"], called["name"] = time.monotonic() + 8, shown
                elif rest is not None:             # for me: a turn right after goes on with it, the sentence cut at a pause
                    called["until"] = time.monotonic() + 2   # "Roger, can you tell me" … "what the sequencer is doing"
                elif rest is None:
                    ui.you(shown, tentative=True)    # heard, not for me: dim
                    if not called["told"]:          # once a run: why it is dim
                        ui.note(f"not for me: start with {cfg['name']}")
                        called["told"] = True
            if rest is None:
                return
            said = rest
            words = " ".join(norm(said))
        if status["muted"]:                # only "slash unmute" gets through; nothing else is printed or kept
            if ev["event"] == "EndOfTurn" and words.replace("un mute", "unmute") == "slash unmute":
                set_mute(False)
            return
        asking = pending["future"] and current["commit"] and current["commit"].is_set()   # an early guess: as ever
        if asking and not (ev["event"] == "EndOfTurn" and SLASH.search(words)):
            if ev["event"] == "EndOfTurn" and cfg["push_to_talk"]:
                status["gate_open"] = False
            if ev["event"] == "EndOfTurn" and said:   # a tool waits on the question: no pause, no eager start, no cut
                ui.you(shown, tentative=not pending["ready"])   # before the question is out, nothing answers it
                if pending["ready"] and not pending["future"].done():
                    pending["future"].set_result(said)
            return
        if ev["event"] == "EndOfTurn" and said and not paused() and (note := answer(said)):   # paused: a backchannel
            ui.you(shown)
            ui.note(note)
            cut(None)                          # the question, if it was still being asked: answered
            return
        if ev["event"] == "EndOfTurn" and SLASH.search(words):
            ui.you(shown)
            slash(slash_words(said))
            return
        match ev["event"]:
            case "StartOfTurn":
                if cfg["barge_in"] and live() and current["commit"].is_set():
                    pause()
            case "Update":
                if paused() and later["resume"]:           # still talking: the 3 s grace starts over
                    later["resume"].cancel()
                    later["resume"] = asyncio.create_task(resume_later())
            case "EagerEndOfTurn" if said and not paused() and not pending["rule"]:   # an allow answer waits for the end
                if SLASH.search(words):
                    return                      # a command: wait for the final transcript, no brain
                start(said, committed=False)    # quiet: your line prints at EndOfTurn, the reply waits for it
            case "TurnResumed":                 # you kept talking: drop the guess quietly, speaking or still queued
                L = latest["handle"]
                if L and not L["task"].done() and not L["commit"].is_set():
                    cut(None) if L["task"] is current["task"] else L["task"].cancel()
            case "EndOfTurn":
                if cfg["push_to_talk"]:
                    status["gate_open"] = False
                if paused():
                    if said and not backchannel(said):     # a real interruption: this is the new turn
                        ui.you(shown)
                        cut(None)
                        start(said, committed=True)
                    else:
                        if said:
                            ui.you(shown, tentative=True)   # a backchannel: dim, and the reply goes on
                        resume()
                elif said:
                    L = latest["handle"]
                    if (L and not L["task"].done() and not L["task"].cancelling() and not L["commit"].is_set()
                            and norm(L["text"]) == norm(said)):
                        ui.you(shown)
                        L["commit"].set()      # the eager reply for these words, speaking or still queued
                        L["committed_at"] = time.monotonic()
                    else:
                        ui.you(shown)
                        start(said, committed=True)

    async def listen_forever():
        auth = {"Authorization": f"Token {cfg['deepgram_api_key']}"}
        delay = 1
        while True:
            try:
                async with websockets.connect(flux_url(), additional_headers=auth) as ws:
                    ears["ws"] = ws
                    delay = 1
                    status["ears"] = True
                    refresh()
                    async for m in ws:
                        ev = json.loads(m)
                        if ev.get("type") == "TurnInfo":
                            heard(ev)
            except (OSError, websockets.exceptions.WebSocketException) as e:
                ears["ws"] = None
                status["ears"] = False
                refresh()
                ui.note(f"ears lost ({type(e).__name__}); reconnecting in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 15)
            else:
                ears["ws"] = None        # closed on purpose (new ear settings): straight back

    lines = asyncio.Queue()

    def read_keys():
        """What is typed, as it comes: a line at a time, or a key at a time while a question waits."""
        with contextlib.suppress(OSError):
            while chunk := os.read(0, 1024):
                loop.call_soon_threadsafe(lines.put_nowait, chunk.decode(errors="ignore"))
    if ui.typeahead[0]:
        lines.put_nowait(ui.typeahead[0])
    threading.Thread(target=read_keys, daemon=True).start()   # a daemon, so exit never waits on a blocked read
    term = {"saved": termios.tcgetattr(0) if os.isatty(0) else None, "keys": False}

    def key_mode():
        """The terminal sends keys as pressed, unechoed, and what is typed shows on the state line: its own echo
        would be drawn over by the state line. While a question is on screen, one key answers it."""
        want = bool(term["saved"])
        if want != term["keys"]:
            term["keys"] = want
            if want:
                tty.setcbreak(0)
            else:
                termios.tcsetattr(0, termios.TCSANOW, term["saved"])
                status["typed"] = ""

    async def keys():
        typed = ""
        while chunk := await lines.get():
            asking = pending["ready"] and (pending["future"] or pending["rule"])
            pick = dict(re.findall(r"\*\*(\d)\*\* (\w+)", pending["options"])) if asking else {}
            if not typed and chunk.strip() in pick:     # 1, 2 or 3: that answer, at once
                said = pick[chunk.strip()].lower()
                ui.you(said)
                if pending["future"]:
                    if not pending["future"].done():
                        pending["future"].set_result(said)
                elif note := answer(said):
                    ui.note(note)
                    cut(None)
                continue
            for ch in chunk:
                if ch in "\r\n":
                    on_line(typed.strip())
                    typed = ""
                elif ch in "\x7f\b":
                    typed = typed[:-1]
                elif ch == "\x15":            # Ctrl-U: the whole line
                    typed = ""
                elif ch.isprintable() and not chunk.startswith("\x1b"):   # not an arrow key's escape sequence
                    typed += ch
            status["typed"] = typed           # keys unechoed: shown on the state line
            refresh()

    def on_line(typed):
        if typed.startswith("/") and slash("slash " + typed[1:].lower()):
            pass
        elif typed and pending["future"]:   # typed, it answers the question at once
            ui.you(typed)
            if not pending["future"].done():
                pending["future"].set_result(typed)
        elif typed:                         # a typed question is a turn, for when you cannot talk
            ui.you(typed)
            if note := answer(typed):
                ui.note(note)
            else:
                start(typed, committed=True)
        elif cfg["push_to_talk"] and not status["gate_open"]:
            status["gate_open"] = True
            ui.note("mic open")
        else:
            cut()

    async def tick():                      # the state line follows what is happening, four times a second
        while True:
            await asyncio.sleep(0.25)
            key_mode()
            refresh()
            ui.settle()                    # a long block's spoken lines go to the transcript as it grows

    async def shower():                    # the plain audio path: sentences show as the callback thread plays them
        while True:
            await asyncio.sleep(0.05)
            drained(0)

    def pane(sid, lines):
        """The last lines of a surface's screen, or ''."""
        try:
            return subprocess.run([CMUX, "read-screen", "--surface", sid, "--lines", str(lines)],
                                  capture_output=True, text=True, timeout=4).stdout
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def orchestrator_state():
        """What the orchestrator's pane shows: working, waiting on you, or idle."""
        sid = next((full for w, _, _, full in surfaces.values() if w == cfg["orchestrator"]), None)
        if not sid:
            return ""
        screen = pane(sid, 14)
        if not screen:
            return ""
        if "esc to interrupt" in screen:
            return "working"
        if "Do you want" in screen or "❯ 1." in screen:
            return "waiting on you"
        return "idle"

    async def inbox_watch():
        """Replies to claudio's messages land in its own pane's cmux inbox: read them out, like a session's report."""
        me, since, heard = os.environ.get("CMUX_SURFACE_ID"), time.time(), set()
        if not me:
            return

        def take():
            """The queued messages, never marked read: the listing also holds the brain's handoffs on their way, and
            marking those read would stop cmux delivering them to a session still starting up."""
            try:
                out = subprocess.run([CMUX, "agent", "inbox", "--surface", me, "--state", "queued", "--json"],
                                     capture_output=True, text=True, timeout=5).stdout
                return json.loads(out).get("messages", [])
            except (OSError, subprocess.TimeoutExpired, ValueError, AttributeError):
                return []
        while True:
            await asyncio.sleep(3)
            new = [m for m in config.replies(await loop.run_in_executor(None, take), me, since) if m.get("id") not in heard]
            heard.update(m.get("id") for m in new)    # ponytail: ids kept for the run; a few a day
            for m in reversed(new):                   # oldest first
                if status["muted"] or cfg["narrate"] == "none":
                    continue
                name = m.get("sender_name") or "a session"
                for k in (name, str(m.get("sender_surface_id", "")).upper()):
                    brain.handoffs.pop(k, None)       # answered: its turn's end is no news
                ui.event(name, "Reply")
                if echoed(brain.answered, name, "Reply", time.time()):
                    continue                          # its turn's end already said it
                start(f"[event] {m.get('sender_name') or 'A session'} replied to your message:\n{m.get('body', '')}",
                      committed=True, event=True)

    async def orchestrator_watch():        # every 5 s, a glance at the orchestrator's pane; a nudge when it waits
        waiting_since, nudged = None, False
        while True:
            status["orch"] = await loop.run_in_executor(None, orchestrator_state)
            if status["orch"] == "waiting on you":
                waiting_since = waiting_since or time.monotonic()
                if not nudged and time.monotonic() - waiting_since > 120 and not status["muted"] and not live():
                    nudged = True
                    start(f"{cfg['orchestrator']} has been waiting on you for a couple of minutes.", committed=True, fixed=True)
            else:
                waiting_since, nudged = None, False
            await asyncio.sleep(5)

    if os.path.exists(config.SOCK):
        os.unlink(config.SOCK)
    server = await asyncio.start_unix_server(on_event, config.SOCK)
    refresh()                                  # warming up becomes listening, on the same line
    async def greet():
        """So you hear it's up, and the voice works; once the mic is: opening it switches Bluetooth headphones
        (AirPods) to headset mode, about 1.3 s, and what plays meanwhile is lost, "Hi, how" with it."""
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(mic_up.wait(), 3)
        start({"code": "Restarted with new code.", "asked": "Restarted."}.get(restarted, "Hi, how can I help you?"),
              committed=True, fixed=True)
    if not typed:
        asyncio.create_task(greet())
    tasks = [send_mic(), listen_forever(), keys(), watch_config(), brain_watch(), tick(), orchestrator_watch(), inbox_watch()]
    if not aec:
        tasks.append(shower())
    work = {"task": None}
    loop.add_signal_handler(signal.SIGINT, lambda: work["task"] and work["task"].cancel())
    try:
        if aec:
            helper_log = os.path.join(config.DIR, "helper.log")
            helper_proc = await asyncio.create_subprocess_exec(aec, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                               stderr=open(helper_log, "wb"))
            helper_holder["proc"] = helper_proc
            plain = fallback_streams

            def fall_back():
                """The helper died: say why, and carry on with the plain mic and speaker."""
                helper_holder["proc"] = None
                reason = ""
                with contextlib.suppress(OSError):
                    reason = open(helper_log).read().strip().splitlines()[-1:]
                    reason = reason[0] if reason else ""
                ui.warn(f"echo canceller stopped{': ' + reason if reason else ''}; using the plain mic (headphones for barge-in)")
                clear_audio()
                rate["in"] = IN_RATE
                plain["streams"] = (
                    sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16", blocksize=IN_RATE // 50, callback=on_mic),
                    sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=OUT_RATE // 50, callback=on_out))
                for st in plain["streams"]:
                    st.start()
                asyncio.create_task(shower())
                if ears["ws"]:
                    asyncio.create_task(ears["ws"].close())     # the ears come back at the plain mic's rate

            async def mic_pump():
                while chunk := await helper_proc.stdout.read(OUT_RATE // 50 * 2):
                    mic.put_nowait(chunk)
                if helper_holder["proc"]:
                    fall_back()

            async def speaker_pump():
                """Keep ~150 ms queued in the helper: enough that a busy event loop never starves it,
                little enough that a cut (which also clears the helper's queue) feels instant."""
                bps, lead, chunk_size = OUT_RATE * 2, OUT_RATE * 2 * 0.15, OUT_RATE // 50 * 2
                t0, sent = time.monotonic(), 0
                while helper_holder["proc"]:
                    await asyncio.sleep(0.01)
                    played = (time.monotonic() - t0) * bps
                    if sent < played:          # it ran dry (silence between replies): start the lead over
                        sent = played
                    try:
                        while out and sent - played < lead:
                            chunk = bytes(out[:chunk_size]); del out[:chunk_size]
                            drained(len(chunk))
                            helper_proc.stdin.write(chunk)
                            sent += len(chunk)
                        await helper_proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        if helper_holder["proc"]:
                            fall_back()
                        return
            work["task"] = asyncio.gather(mic_pump(), speaker_pump(), *tasks)
            await work["task"]
        else:
            with sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16", blocksize=IN_RATE // 50, callback=on_mic), \
                 sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=OUT_RATE // 50, callback=on_out):
                work["task"] = asyncio.gather(*tasks)
                await work["task"]
    except asyncio.CancelledError:
        pass                                   # Ctrl-C
    finally:
        if term["keys"]:
            termios.tcsetattr(0, termios.TCSANOW, term["saved"])   # quit mid-question: the shell gets its terminal back
        console.print(end="")                  # settle any fading line before the live area goes
        status["live"].stop()
        server.close()
        for st in fallback_streams["streams"] or ():
            with contextlib.suppress(Exception):
                st.stop(); st.close()          # or the mic callback fires after the loop is gone
        brain.expected_exit = True
        await brain.stop()
        proc = helper_holder["proc"]
        if proc and proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                await asyncio.wait_for(proc.wait(), 2)   # before the loop closes, or asyncio complains
        if os.path.exists(config.SOCK):
            os.unlink(config.SOCK)
        console.print()
        ui.note({"code": "restarting with the new code", "asked": "restarting"}.get(status.get("restart"), "bye"))


def code_stamp():
    """When claudio's own code last changed: a new one restarts it (see watch_config)."""
    return max((os.path.getmtime(f) for f in glob.glob(os.path.join(os.path.dirname(__file__), "*.py"))), default=0)


def run(skip=False):
    status["skip"] = skip                      # claudio --dangerously-skip-permissions
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
    if status.get("restart"):                  # the same claudio, new code: same arguments, checks as they were
        args = [a for a in sys.argv if a != "--dangerously-skip-permissions"]
        os.environ["CLAUDIO_RESTARTED"] = status["restart"]
        os.execv(sys.executable, [sys.executable, *args, *(["--dangerously-skip-permissions"] if status["skip"] else [])])
