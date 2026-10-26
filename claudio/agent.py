"""The voice loop: Deepgram Flux ears (eager end of turn, preemptive generation, barge-in),
one long-lived `claude -p` brain, Deepgram Aura mouth sentence by sentence, and a socket where
the Claude Code hooks (`claudio hook ...`) report what sessions did.

Robustness: the ears reconnect with backoff, the brain restarts if it dies (and resumes its last
session, so it remembers), the mouth retries once. An interruption first pauses the reply; a real
turn then cuts it, a backchannel ("mm-hm") or noise lets it carry on from a sentence back."""
import array, asyncio, contextlib, difflib, json, os, re, shutil, signal, subprocess, sys, threading, time
import sounddevice as sd, websockets
from rich.spinner import SPINNERS
from . import config, ui
from .ui import console
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
    return 0


BLOCK_END = object()          # a text block ended (a tool runs next): speak what is buffered, new transcript line
YES, NO = {"yes", "yeah", "yep", "y", "sure", "ok", "okay", "allow", "go"}, {"no", "nope", "n", "dont", "deny", "never"}
BACKCHANNEL = {"yeah", "yes", "yep", "ok", "okay", "mm", "mhm", "hmm", "uh", "huh", "um", "right", "sure", "oh", "ah", "no"}
CMUX, SESSION = config.CMUX, config.SESSION
cfg, surfaces = {}, {}
current = {"task": None, "text": "", "commit": None, "ctl": None}   # the reply that holds the mouth, set by reply()
out = bytearray()             # audio waiting for the speaker
audio = {"fed": 0, "played": 0, "marks": []}   # bytes in and out of `out`, and (offset, sentences, k, shown, secs) still to show


def feed(m):
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
    out.clear()
    audio["fed"] = audio["played"]
    audio["marks"].clear()
speaking = asyncio.Lock()     # one reply at a time, mouth included; later ones queue
status = {"live": None, "muted": False, "ears": True, "last_audio": 0.0, "reply": None, "orch": "", "gate_open": True,
          "level": 0, "latency": None}
BARS = " ▁▂▃▄▅▆▇"
SPIN, MUTED = SPINNERS["dots"]["frames"], ["■"]
SLASH_HELP = ("Slash commands:\n"
              "- `/clear` starts a fresh conversation.\n"
              "- `/model` default, sonnet, opus or haiku.\n"
              "- `/effort` low, medium or high.\n"
              "- `/voice` and a name, such as zeus; alone, it lists them.\n"
              "- `/style` plain, brief or caveman.\n"
              "- `/colors` on or off, for code.\n"
              "- `/status` says the settings.\n"
              "- `/mute` and `/unmute`.\n"
              "- `/stop` cuts a reply.\n"
              "- `/help` says this list.")
COMMANDS = {"clear", "mute", "unmute", "stop", "style", "model", "effort", "voice", "status", "help", "colors", "colours"}
STYLES = {
    "plain": "",
    "brief": "\n\nSTYLE OVERRIDE, brief: this replaces every rule above about length and format. Speak one sentence "
             "per reply, two at most when the answer has two parts. No lead-in before a tool, no question back unless "
             "the next step is truly the user's call. Whenever the answer names several things, sums up or compares, "
             "the screen carries it: a Markdown table when the things have two or more factors (shown, never read), "
             "else bullets of a few words each. Order: one short spoken sentence saying what it is, then the table "
             "or bullets, then at most one sentence on what stands out. Never open a reply with a table or bullets.",
    "caveman": "\n\nSTYLE OVERRIDE, caveman: this replaces every rule above about sentences. Speak like a caveman: "
               "at most six words per sentence, drop articles, auxiliaries and connectors, fragments are the norm. "
               "Facts, names and numbers stay exact. Example: \"Next: Sales. File fields still open. Main clean. "
               "Want Sales started?\" Never a full polite sentence.",
}
LEAD = "|".join(["um", "uh", "ok", "okay", "so", "hey", "and", "well", "please", "yeah", "right", "now", "slash", *COMMANDS])   # what may come before "slash"
SLASH = re.compile(rf"^(?:(?:{LEAD})\s+){{0,2}}slash\s+(\w+)\s*(.*)$")   # "um slash mute", an echoed "mute slash mute"; not "add a slash command"


def parse_slash(words):
    """("style", "caveman") from "slash um i want a caveman"; None when it is no command."""
    m = SLASH.search(words)
    if not m:
        return None
    rest = f"{m.group(1)} {m.group(2)}".split()
    if rest[0] not in COMMANDS:                # misheard: "slash e fort", "slash efort", "slash colours" spelt oddly
        for n in (2, 1):
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
        status["live"].update(f"[cyan]{bar}[/] [dim]{state_text()}[/]")
        status["live"].renderable.frames = MUTED if status["muted"] else SPIN     # muted: a still square, no spin


parse_surfaces, sessions = config.parse_surfaces, config.surfaces


def system_prompt():
    lines = [f"- {w}: surface {full} ({t}), in {c}" for sid, (w, t, c, full) in surfaces.items() if w]
    keys = [k for k in config.DEFAULTS if k not in config.SECRETS]
    settings = ", ".join(f"{k}={cfg[k]}" for k in keys)
    persona = (open(config.PROMPT).read()
               .replace("{TRANSCRIPTS}", ui.TRANSCRIPTS)
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
            + "\n".join(lines)
            + "\n\nRules that matter most, last so they stay in mind:\n"
            + "- A turn not meant for you (talk to someone else, a TV, a name, one stray word) or cut off mid-thought "
              "(\"Can you tell me\") gets exactly [skip] as your whole reply. Nothing else.\n"
            + (f"- GitHub here is {owner}/{repo}. A repo named without its owner, such as \"{repo}-app\", is {owner}/<that name>: "
               f"gh ... -R {owner}/<name>.\n" if owner else "")
            + (f"- The voice is {cfg['mouth']}: local_voice, local_speed and local_model do nothing, and it has no speed "
               "setting. Say so rather than suggest them.\n" if cfg["mouth"] != "local" else "")
            + "- Never say a setting changed unless `claudio set` succeeded, and never send work after a no.")


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
    """One claude process. A turn is a user line on stdin; its text deltas stream back."""
    def __init__(self):
        self.proc, self.session_id, self.busy = None, None, False
        self.lock = asyncio.Lock()
        self.handoffs = {}             # workspace title -> time of the last `cmux agent message` to it
        self.on_denied = None          # (denials, the turn's text): a tool use the allow-list refused
        self.changed = asyncio.Event() # set when it ran `claudio set`, so the watcher reloads at once
        self.expected_exit = False     # a restart on purpose, not a death

    async def start(self):
        me = os.path.dirname(os.path.abspath(sys.argv[0]))      # so the brain can run `claudio set`
        env = {k: v for k, v in os.environ.items() if k.lower() not in config.SECRETS}   # the brain never needs the keys
        env["PATH"] = f"{me}:{os.path.dirname(CMUX)}:{os.environ.get('PATH', '')}"
        resume = remembered_session()
        mcp = config.mcp_servers()
        self.resumed, self.started_at = bool(resume), time.monotonic()
        self.proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--include-partial-messages", "--verbose", "--setting-sources", "",
            "--strict-mcp-config",            # never the desktop's MCP servers: only those in mcp.json, if any
            "--disable-slash-commands",       # nor its skills and /commands: the brain took them for claudio's
            *(["--mcp-config", config.MCP] if mcp else []),
            "--append-system-prompt", system_prompt(),
            "--disallowedTools", f"Read(//{config.SECRETS_FILE.lstrip('/')})",
            "--allowedTools", "Read", "Grep", "Glob",
            "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)", "Bash(git branch:*)",
            "Bash(gh issue view:*)", "Bash(gh issue list:*)", "Bash(gh pr view:*)", "Bash(gh pr list:*)",   # GitHub, read only
            "Bash(gh pr diff:*)", "Bash(gh pr checks:*)", "Bash(gh repo view:*)", "Bash(gh repo list:*)", "Bash(gh search:*)",
            "Bash(cmux agent message:*)", "Bash(cmux surface list:*)", "Bash(cmux read-screen:*)",
            "Bash(cmux new-workspace:*)", "Bash(cmux new-split:*)", "Bash(cmux new-surface:*)",
            "Bash(cmux send-key:*)",          # to pick the option the user chose in a session's question
            "Bash(claudio set:*)",
            *(f"mcp__{name}" for name in mcp),
            *config.allowed(),                # the user's own: ~/.config/claudio/allow
            *(["--model", cfg["model"]] if cfg["model"] != "default" else []),
            *(["--effort", cfg["effort"]] if cfg["effort"] else []),
            *(["--resume", resume] if resume else []),
            env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=open(os.path.join(config.DIR, "brain.log"), "ab"),
            limit=16 * 1024 * 1024)            # a Read of a big file is one stream-json line; the default 64 KiB hangs the turn
        if resume:
            await asyncio.sleep(1.5)
            if self.proc.returncode is not None:      # that session is gone: forget it and start fresh
                os.unlink(SESSION)
                await self.start()

    async def restart(self):
        async with self.lock:
            self.expected_exit = True
            self.proc.terminate()
            await self.start()
            self.expected_exit = False

    async def send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        await self.proc.stdin.drain()

    async def interrupt(self):
        if self.busy and self.proc.returncode is None:
            await self.send({"type": "control_request", "request_id": f"cut-{os.urandom(4).hex()}",
                             "request": {"subtype": "interrupt"}})

    def saw(self, ev):
        """Side channel: the brain's own session id, and which sessions it handed work to."""
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            self.session_id = ev.get("session_id")
            if cfg.get("memory", True):
                with contextlib.suppress(OSError):
                    open(SESSION, "w").write(f"{self.session_id} {time.time()}")
        if ev.get("type") == "assistant":
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_use":
                    ui.tool(c.get("name"), c.get("input", {}))
                if c.get("type") == "tool_use" and c.get("name") == "Bash":
                    cmd = c["input"].get("command", "")
                    if m := re.search(r'cmux agent message\s+(?:"([^"]+)"|(\S+))', cmd):
                        asked = re.findall(r'"((?:[^"\\]|\\.)*)"', cmd)
                        self.handoffs[m.group(1) or m.group(2)] = (time.time(), asked[-1] if asked else "")
                    if "claudio set" in cmd:
                        self.changed.set()

    async def turn(self, text):
        async with self.lock:
            self.busy = True
            tag = "" if cfg["style"] == "plain" or text.startswith("[event]") else f"({cfg['style']} style) "
            await self.send({"type": "user", "message": {"role": "user", "content": tag + text}})
            q = asyncio.Queue()

            async def pump():
                spoke, last_text = False, ""
                try:
                    while True:
                        line = await self.proc.stdout.readline()
                        if not line:
                            return                     # it died; the watchdog restarts it
                        ev = json.loads(line)
                        self.saw(ev)
                        if ev.get("type") == "stream_event":
                            e = ev["event"]
                            if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta":
                                spoke = True
                                q.put_nowait(e["delta"]["text"])
                            elif e.get("type") == "content_block_stop" and spoke:
                                q.put_nowait(BLOCK_END)   # a text block ended: speak its tail now, new line
                            elif e.get("type") == "content_block_start" and e["content_block"].get("type") == "tool_use" and not spoke:
                                spoke = True          # it skipped its lead-in: a word by tool kind, so the tool run is not silence
                                q.put_nowait("Looking. " if e["content_block"].get("name") in ("Read", "Grep", "Glob") else "Checking. ")
                        elif ev.get("type") == "assistant":
                            last_text = " ".join(c.get("text", "") for c in ev["message"].get("content", []) if c.get("type") == "text")
                        elif ev.get("type") == "result":
                            if ev.get("permission_denials") and self.on_denied and not text.startswith("[event]"):
                                self.on_denied(ev["permission_denials"], text)
                            if ev.get("is_error") and not spoke and last_text:
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
                self.busy = False


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
                    samples, _ = await asyncio.to_thread(self.tts.create, text, voice=cfg["local_voice"],
                                                         speed=cfg["local_speed"])
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
        await mouth.close()


def show(sentences, k, shown, secs=None):
    if k < len(sentences) and k not in shown:
        shown.add(k)
        text, first_of_block, blocks = sentences[k]
        for b in blocks:
            ui.block(b, colors=cfg.get("code_colors", True))
        if text:
            ui.me_line(text, first_of_block, live=bool(status["live"]), secs=secs)


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
    b = bytes(out[:n]); del out[:n]
    outdata[:len(b)] = b
    outdata[len(b):] = b"\x00" * (n - len(b))
    if b:
        audio["played"] += len(b)              # the callback thread: the showing happens on the loop (see shower)


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).split()


def backchannel(said):
    words = norm(said)
    return len(words) < 2 or all(w in BACKCHANNEL for w in words)


async def shower_typed():
    while True:
        await asyncio.sleep(0.05)
        drained(0)


async def main():
    global cfg, surfaces
    cfg = config.load()
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
        ui.banner(facts={"orchestrator": cfg["orchestrator"] or "-", "brain": f"{cfg['model']}/{cfg['effort']}",
                         "voice": (f"elevenlabs {cfg['elevenlabs_voice'][:8]}" if cfg["mouth"] == "elevenlabs" and cfg["elevenlabs_api_key"]
                                   else f"local {cfg['local_voice']}" if cfg["mouth"] == "local"
                                   else ui.short_voice(cfg["voice"])),
                         "echo cancel": "on" if aec else "off",
                         "memory": "on" if remembered_session() else "fresh"},
                  hints="Enter cuts · Ctrl-C quits · claudio setup")
    await brain.start()
    with console.status("[dim]warming up the brain…[/]"):
        async for _ in brain.turn("Say only: ready."):
            pass

    if typed:
        with sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=OUT_RATE // 50, callback=on_out):
            ui.you(typed)
            ev = asyncio.Event(); ev.set()
            showing = asyncio.create_task(shower_typed())
            await reply(typed, ev, new_ctl())
            showing.cancel()
        return brain.proc.terminate()

    loop = asyncio.get_running_loop()
    voices = asyncio.create_task(asyncio.to_thread(config.fetch_aura, cfg["deepgram_api_key"]))   # for "slash voice"; kept so it isn't collected
    mic = asyncio.Queue()
    helper_holder = {"proc": None}  # the echo-cancelling helper, when it runs
    fallback_streams = {"streams": None}   # the plain mic and speaker, if the helper died
    ears = {"ws": None}            # the Flux socket, when connected
    later = {"resume": None}       # the timer that resumes a paused reply nobody interrupted after all

    def on_mic(indata, frames, t, status_):
        loop.call_soon_threadsafe(mic.put_nowait, bytes(indata))

    def live():
        t = current["task"]
        return t is not None and not t.done() and not t.cancelling()   # a cut reply still draining the brain is gone

    def paused():
        return live() and current["ctl"]["paused"].is_set()

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

    pending = {"rule": None, "text": "", "retry": None}   # a rule asked about, the request it was for, one to retry

    def denied(denials, text):
        """The brain was refused a tool: claudio, not the brain, asks the user, so nothing it reads can say yes."""
        rule, what = config.rule_for(denials[0].get("tool_name", ""), denials[0].get("tool_input") or {})
        if rule in config.allowed():
            return
        pending.update(rule=rule, text=text)
        start(f"I'm not allowed to run `{what}`. Allow it from now on? Say yes or no.", committed=True, fixed=True, event=True)

    brain.on_denied = denied

    def answer(said):
        """The turn after an allow question: yes adds the rule and retries the request; no drops it. The note to
        show when it was the answer; None for anything else, which drops the question and is an ordinary turn."""
        rule, pending["rule"] = pending["rule"], None
        words = norm(said)
        if not rule or not words or len(words) > 3:
            return None
        if words[0] in YES:
            config.allow(rule)                 # watch_config sees it, restarts the brain, then retries
            pending["retry"] = pending["text"]
            return f"allowed {rule}"
        if words[0] in NO:
            return f"not allowed: {rule}"
        return None

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

    def slash(words):
        """Spoken slash commands: "slash clear", "slash model sonnet"… True when handled."""
        parsed = parse_slash(words)
        if not parsed:
            return False
        cmd, arg = parsed
        ui.note(f"/{cmd} {arg}".strip())
        if cmd not in ("clear", "stop"):
            cut(None)                          # a command over a reply stops it quietly; the note says why
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
            name = arg.replace(" ", "-").removeprefix("aura-2-").removesuffix("-en")
            if name not in config.AURA:        # "banana", "can you list the voices", or nothing: all of them, nothing saved
                said = f"{arg.capitalize()} is not recognised as a voice. " if len(arg.split()) == 1 else ""   # a sentence: just the list
                start(f"{said}The voices are as follows:", committed=True, fixed=True,
                      screen="\n".join(f"- {n}" for n in config.AURA))    # on screen only: 41 names read aloud is too long
                return True
            config.set_key("voice", f"aura-2-{name}-en")
            brain.changed.set()
            cfg["voice"] = f"aura-2-{name}-en"     # so the confirmation already speaks in it
            start(f"{name.capitalize()} from now on.", committed=True, fixed=True)
        elif cmd in ("model", "effort") and not arg:   # "slash effort" alone: the choices
            start(f"{cmd.capitalize()} is {', '.join(config.MODELS if cmd == 'model' else config.EFFORTS)}.",
                  committed=True, fixed=True)
        elif cmd in ("model", "effort"):
            value = arg.replace(" ", "-")
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
        elif cmd == "status":
            start(f"Status:\n- Orchestrator {cfg['orchestrator'] or 'none'}.\n- Brain {cfg['model']} at {cfg['effort']} effort.\n"
                  f"- Voice {ui.short_voice(cfg['voice'])}.\n- Memory {'on' if cfg['memory'] else 'off'}.", committed=True, fixed=True)
        elif cmd == "help":
            start(SLASH_HELP, committed=True, fixed=True)
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
        if sid not in surfaces:
            surfaces = sessions()          # a session that appeared after we started
        ws, *_, full = surfaces.get(sid, (None, None, None, sid))     # full: the id cmux takes
        if not ws:
            return
        if status["muted"]:
            return                         # muted: nothing spoken, not even the sessions
        when, asked = brain.handoffs.get(ws, (0, ""))
        if cfg["narrate"] == "none":
            return
        handed = when > time.time() - 1800
        if ev["event"] == "Stop" and ev.get("text") and (handed or cfg["narrate"] == "all"):
            text = (f"[event] {ws} finished a turn on your request \"{asked}\". Its last message:\n{ev['text']}" if handed
                    else f"[event] {ws} finished a turn. Its last message:\n{ev['text']}")
        elif ev["event"] == "Notification" and ev.get("kind") == "permission_prompt":
            screen = await loop.run_in_executor(None, pane, full, 18)
            text = f"[event] {ws} asks for permission: {ev.get('message')}\nIts screen shows:\n{screen}"
        elif ev["event"] == "AskUserQuestion" and ev.get("questions"):
            text = f"[event] {ws} (surface {full}) asks you to choose:\n{json.dumps(ev['questions'])}"
        else:
            return
        ui.event(ws, ev["event"], asked if ev["event"] == "Stop" else "")
        start(text, committed=True, event=True)

    def flux_url():
        return (f"wss://api.deepgram.com/v2/listen?model={cfg['ears']}&encoding=linear16&sample_rate={rate['in']}"
                f"&eot_threshold={cfg['eot']}&eager_eot_threshold={cfg['eager_eot']}&eot_timeout_ms={cfg['eot_timeout_ms']}")

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
        access = (mtime(config.ALLOW), mtime(config.MCP))
        last = dict(cfg)                       # the file as last loaded: what a change is told against
        while True:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(brain.changed.wait(), 1.0)
            brain.changed.clear()
            await asyncio.sleep(0.2)          # let `claudio set` finish writing
            now = mtime(config.PROMPT)
            if now is not None and now != persona:        # the persona was edited: new brain, same memory
                persona = now
                ui.note("persona changed; brain restarting")
                await brain.restart()
                start("[event] Your persona prompt was just edited and you were restarted with it. "
                      "Say in a few words that you are back.", committed=True, event=True)
            if (mtime(config.ALLOW), mtime(config.MCP)) != access:   # allow or mcp.json edited: a brain that has them
                access = (mtime(config.ALLOW), mtime(config.MCP))
                ui.note("access changed; brain restarting")
                await brain.restart()
                if pending["retry"]:           # a yes to an allow question: the request again, now allowed
                    start(pending["retry"], committed=True)
                    pending["retry"] = None
            now = mtime(config.CONF)
            if now is None or now == stamp:
                continue
            stamp = now
            new = config.load()
            for w in config.WARNINGS:
                ui.warn(w)
            restart = (new["model"], new["effort"], new["style"]) != (cfg["model"], cfg["effort"], cfg["style"])
            re_ear = any(new[k] != cfg[k] for k in ("ears", "eot", "eager_eot", "eot_timeout_ms"))
            if not new["push_to_talk"]:
                status["gate_open"] = True     # off: the mic is open again
            diff = ", ".join(f"{k} → {ui.short_voice(str(new[k]))}" for k in config.DEFAULTS
                             if k not in config.SECRETS and new[k] != last[k])    # not cfg: a slash voice set it early
            cfg, last = new, dict(new)
            if diff or restart:
                ui.setting(f"{diff or 'settings reloaded'}{'  ·  brain restarting' if restart else ''}")
            if re_ear and ears["ws"]:
                asyncio.create_task(ears["ws"].close())   # the listener reconnects with the new ears
            if restart:
                await brain.restart()
                start(f"[event] You were just restarted with model {cfg['model']} at effort {cfg['effort']}, "
                      f"style {cfg['style']}. Say only that you're back with it, in two to four words, such as "
                      f"'Back, on {cfg['style']}.' or 'Back on {cfg['model']}.'", committed=True, event=True)

    async def brain_watch():
        while True:
            proc = brain.proc
            await proc.wait()
            await asyncio.sleep(0.1)
            if brain.expected_exit or brain.proc is not proc:
                continue
            if brain.resumed and time.monotonic() - brain.started_at < 8:
                with contextlib.suppress(OSError):
                    os.unlink(SESSION)             # the remembered session would not resume: start fresh, once
                ui.note("the remembered conversation is gone; starting fresh")
                why = "The conversation you were resuming is gone, so you start fresh. Say so in a few words."
            else:
                ui.warn("the brain died; restarting it")
                why = ("You just crashed and were restarted. Say in a few words that you are back, "
                       "and ask the user to repeat what they said last if they were mid-request.")
            async with brain.lock:
                await brain.start()
            start(f"[event] {why}", committed=True, event=True)

    status["gate_open"] = not cfg["push_to_talk"]   # push to talk: Enter opens the mic until your turn ends

    async def send_mic():
        while True:
            b = await mic.get()
            ws = ears["ws"]
            if ws is None:
                continue
            # barge-in off: deaf only while a reply your turn has committed is playing, never during an
            # eager start, or the rest of what you are saying would be lost
            answering = live() and current["commit"].is_set()
            if (answering and not cfg["barge_in"]) or not status["gate_open"]:
                b = b"\x00" * len(b)
            else:
                peak = max(abs(x) for x in array.array("h", b)[::8]) if len(b) >= 16 else 0
                status["level"] = max(peak, status["level"] * 0.8)     # a quick rise, a slow fall
            with contextlib.suppress(websockets.ConnectionClosed):
                await ws.send(b)

    def heard(ev):
        said = ev.get("transcript", "").strip()
        words = " ".join(norm(said))
        if cfg["address_me"] and said and ev["event"] in ("EagerEndOfTurn", "EndOfTurn"):
            if not words.startswith("claudio"):
                if ev["event"] == "EndOfTurn":
                    ui.you(said, tentative=True)    # heard, not for me: dim
                return
            said = re.sub(r"^\W*claudio\W*", "", said, flags=re.I).strip() or said
            words = " ".join(norm(said))
        if status["muted"]:                # only "slash unmute" gets through; nothing else is printed or kept
            if ev["event"] == "EndOfTurn" and words.replace("un mute", "unmute") == "slash unmute":
                set_mute(False)
            return
        if ev["event"] == "EndOfTurn" and said and (note := answer(said)):
            ui.you(said)
            ui.note(note)
            cut(None)                          # the question, if it was still being asked: answered
            return
        if ev["event"] == "EndOfTurn" and SLASH.search(words):
            ui.you(said)
            slash(words)
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
                        ui.you(said)
                        cut(None)
                        start(said, committed=True)
                    else:
                        if said:
                            ui.you(said, tentative=True)   # a backchannel: dim, and the reply goes on
                        resume()
                elif said:
                    L = latest["handle"]
                    if (L and not L["task"].done() and not L["task"].cancelling() and not L["commit"].is_set()
                            and norm(L["text"]) == norm(said)):
                        ui.you(said)
                        L["commit"].set()      # the eager reply for these words, speaking or still queued
                        L["committed_at"] = time.monotonic()
                    else:
                        ui.you(said)
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
    threading.Thread(target=lambda: [loop.call_soon_threadsafe(lines.put_nowait, l) for l in sys.stdin],
                     daemon=True).start()              # a daemon, so exit never waits on a blocked read

    async def keys():
        while line := await lines.get():
            typed = line.strip()
            if typed.startswith("/") and slash("slash " + typed[1:].lower()):
                pass
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
    status["live"] = console.status("[dim]listening[/]")
    ui.attach(status["live"])
    status["live"].start()
    if not typed:
        start("Hi, how can I help you?", committed=True, fixed=True)    # so you hear it's up, and the voice works
    tasks = [send_mic(), listen_forever(), keys(), watch_config(), brain_watch(), tick(), orchestrator_watch()]
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
        console.print(end="")                  # settle any fading line before the live area goes
        status["live"].stop()
        server.close()
        for st in fallback_streams["streams"] or ():
            with contextlib.suppress(Exception):
                st.stop(); st.close()          # or the mic callback fires after the loop is gone
        brain.expected_exit = True
        for proc in (brain.proc, helper_holder["proc"]):
            if proc and proc.returncode is None:
                proc.terminate()
                with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                    await asyncio.wait_for(proc.wait(), 2)   # before the loop closes, or asyncio complains
        if os.path.exists(config.SOCK):
            os.unlink(config.SOCK)
        console.print()
        ui.note("bye")


def run():
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
