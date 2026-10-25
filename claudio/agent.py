"""The voice loop: Deepgram Flux ears (eager end of turn, preemptive generation, barge-in),
one long-lived `claude -p` brain, Deepgram Aura mouth sentence by sentence, and a socket where
the Claude Code hooks (`claudio hook ...`) report what sessions did.

Robustness: the ears reconnect with backoff, the brain restarts if it dies (and resumes its last
session, so it remembers), the mouth retries once. An interruption first pauses the reply; a real
turn then cuts it, a backchannel ("mm-hm") or noise lets it carry on from a sentence back."""
import array, asyncio, contextlib, json, os, re, shutil, signal, subprocess, sys, threading, time
import sounddevice as sd, websockets
from . import config, ui
from .ui import console
IN_RATE, OUT_RATE = 16000, 24000    # the plain path; the echo-cancelling helper runs both ways at 24000
SENTENCE = re.compile(r"[.!?]['\")]?\s")
BLOCK_END = object()          # a text block ended (a tool runs next): speak what is buffered, new transcript line
BACKCHANNEL = {"yeah", "yes", "yep", "ok", "okay", "mm", "mhm", "hmm", "uh", "huh", "um", "right", "sure", "oh", "ah", "no"}
CMUX, SESSION = config.CMUX, config.SESSION
cfg, surfaces = {}, {}
current = {"task": None, "text": "", "commit": None, "ctl": None}   # the reply that holds the mouth, set by reply()
out = bytearray()             # audio waiting for the speaker
audio = {"fed": 0, "played": 0, "marks": []}   # bytes in and out of `out`, and (offset, sentences, k, shown) still to show


def feed(m):
    out.extend(m)
    audio["fed"] += len(m)
    status["last_audio"] = time.monotonic()


def drained(n):
    """n bytes left `out` for the speaker: show every sentence whose audio has now started playing."""
    audio["played"] += n
    while audio["marks"] and audio["marks"][0][0] <= audio["played"]:
        _, sentences, k, shown = audio["marks"].pop(0)
        show(sentences, k, shown)


def mark(sentences, k, shown):
    """Sentence k's audio starts at the current end of `out`."""
    audio["marks"].append((audio["fed"], sentences, k, shown))


def clear_audio():
    """A cut: drop what is queued, and the sentences that would have shown with it."""
    out.clear()
    audio["fed"] = audio["played"]
    audio["marks"].clear()
speaking = asyncio.Lock()     # one reply at a time, mouth included; later ones queue
status = {"live": None, "muted": False, "ears": True, "last_audio": 0.0, "reply": None, "orch": "", "gate_open": True,
          "level": 0, "latency": None}
BARS = " ▁▂▃▄▅▆▇"
SLASH_HELP = ("clear starts a fresh conversation. model, effort and voice change the brain or the voice. "
              "style plain, brief or caveman. status says the settings. mute and unmute. stop cuts a reply.")
STYLES = {
    "plain": "",
    "brief": "\n\nSTYLE OVERRIDE, brief: one sentence per reply, two at most when the answer has two parts. "
             "No lead-in before a tool, no question back unless the next step is truly the user's call.",
    "caveman": "\n\nSTYLE OVERRIDE, caveman: this replaces every rule above about sentences. Speak like a caveman: "
               "at most six words per sentence, drop articles, auxiliaries and connectors, fragments are the norm. "
               "Facts, names and numbers stay exact. Example: \"Next: Sales. File fields still open. Main clean. "
               "Want Sales started?\" Never a full polite sentence.",
}
SLASH = re.compile(r"^(?:\w+\s+){0,2}slash\s+(\w+)\s*(.*)$")   # "slash effort low", "um slash mute"; not "add a slash command"


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


parse_surfaces, sessions = config.parse_surfaces, config.surfaces


def system_prompt():
    lines = [f"- {w}: surface {sid} ({t}), in {c}" for sid, (w, t, c) in surfaces.items() if w]
    return (STYLES.get(cfg["style"], "").strip() + "\n\n" + open(config.PROMPT).read()
            + f"\n\nOrchestrator: {cfg['orchestrator'] or 'none set'}.\nSessions now:\n" + "\n".join(lines))


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
        self.changed = asyncio.Event() # set when it ran `claudio set`, so the watcher reloads at once
        self.expected_exit = False     # a restart on purpose, not a death

    async def start(self):
        me = os.path.dirname(os.path.abspath(sys.argv[0]))      # so the brain can run `claudio set`
        env = dict(os.environ, PATH=f"{me}:{os.path.dirname(CMUX)}:{os.environ.get('PATH', '')}")
        resume = remembered_session()
        self.resumed, self.started_at = bool(resume), time.monotonic()
        self.proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--include-partial-messages", "--verbose", "--setting-sources", "",
            "--append-system-prompt", system_prompt(),
            "--disallowedTools", f"Read(//{config.SECRETS_FILE.lstrip('/')})",
            "--allowedTools", "Read", "Grep", "Glob",
            "Bash(git status:*)", "Bash(git log:*)", "Bash(git diff:*)", "Bash(git branch:*)",
            "Bash(cmux agent message:*)", "Bash(cmux surface list:*)", "Bash(cmux read-screen:*)",
            "Bash(cmux new-workspace:*)", "Bash(cmux new-split:*)", "Bash(cmux new-surface:*)",
            "Bash(claudio set:*)",
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
    Untested against a live key when written; the protocol is from ElevenLabs' websocket reference."""
    def __init__(self):
        self.ws, self.sent, self.final = None, 0, False

    async def open(self):
        url = (f"wss://api.elevenlabs.io/v1/text-to-speech/{cfg['elevenlabs_voice']}/stream-input"
               f"?model_id=eleven_flash_v2_5&output_format=pcm_24000")
        self.ws = await websockets.connect(url, additional_headers={"xi-api-key": cfg["elevenlabs_api_key"]})
        await self.ws.send(json.dumps({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}}))

    async def receive(self, on_audio):
        import base64
        try:
            async for m in self.ws:
                ev = json.loads(m)
                if ev.get("audio"):
                    on_audio(base64.b64decode(ev["audio"]))
                if ev.get("isFinal"):
                    self.final = True
        except websockets.ConnectionClosed:
            self.final = True

    async def say(self, text):
        await self.ws.send(json.dumps({"text": text if text.endswith(" ") else text + " ", "flush": True}))
        self.sent += 1

    @property
    def got(self):
        return max(0, self.sent - 1)           # no per-sentence marker: audio arriving now belongs to the last sentence sent

    def done(self):
        return self.final

    async def finish(self):
        await self.ws.send(json.dumps({"text": ""}))      # end of input: the last audio, then isFinal

    async def close(self):
        with contextlib.suppress(Exception):
            await self.ws.close()


def new_mouth():
    return ElevenMouth() if cfg["mouth"] == "elevenlabs" and cfg["elevenlabs_api_key"] else DeepgramMouth()


async def speak_from(sentences, i, new, gen_done, ctl, commit, shown):
    """Speak sentences[i:] over one mouth socket until done or paused. Returns (next index, finished).
    A sentence is printed when its audio starts playing, so the transcript keeps time with the voice."""
    mouth = None
    for attempt in (1, 2):
        try:
            mouth = new_mouth()
            await mouth.open()
            break
        except (OSError, websockets.exceptions.WebSocketException):
            mouth = None
            await asyncio.sleep(1)
    if mouth is None:
        ui.warn("mouth lost: the speech service is unreachable; text only")
        await gen_done.wait()
        for k in range(i, len(sentences)):
            show(sentences, k, shown)
        return len(sentences), True
    first = i                     # the sentence whose audio is arriving: first + mouth.got
    held = bytearray()
    held_marks = []               # (offset within held, k): sentence starts inside the held audio
    marked = set()

    def release():
        """Held audio (synthesized before the final transcript) goes to the speaker, marks and all."""
        for off, k in held_marks:
            audio["marks"].append((audio["fed"] + off, sentences, k, shown))
        held_marks.clear()
        feed(bytes(held)); held.clear()
        r = status["reply"]
        if r and r.get("committed_at") and not r.get("first_word"):
            r["first_word"] = time.monotonic() - r["committed_at"]

    def on_audio(m):
        k = first + mouth.got
        if commit.is_set():
            if held:
                release()
            if k not in marked:
                marked.add(k); mark(sentences, k, shown)
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
            await mouth.say(sentences[i][0])
            i += 1
        await mouth.finish()
        while not mouth.done() and not ctl["paused"].is_set() and not player.done():
            await asyncio.sleep(0.02)
        if ctl["paused"].is_set():
            return i, False
        await commit.wait()
        if held:
            release()
        for k in range(first, i):
            if k not in marked:                # no audio came for it (an empty sentence): show it anyway
                show(sentences, k, shown)
        return i, True
    finally:
        player.cancel()
        committer.cancel()
        await mouth.close()


def show(sentences, k, shown):
    if k < len(sentences) and k not in shown:
        shown.add(k)
        text, first_of_block = sentences[k]
        ui.me_line(text.strip(), first_of_block)


async def reply(text, commit, ctl, fixed=False, handle=None):
    """One spoken reply. Text streams from the brain into sentences; the mouth follows, and can be
    paused (a possible interruption) and resumed a sentence or two back."""
    async with speaking:
        if handle:                             # now it is the one speaking: cut, pause and the state line follow it
            current.update(handle)
            status["reply"] = handle
        refresh()
        sentences, new, gen_done, shown = [], asyncio.Event(), asyncio.Event(), set()

        async def generate():
            buf, first = "", True

            def emit(sentence):
                nonlocal first
                sentences.append((sentence, first))
                new.set()
                first = False
            try:
                if fixed:
                    emit(text)
                    return
                async for d in brain.turn(text):
                    if d is BLOCK_END:
                        if buf.strip():
                            emit(buf)
                        buf, first = "", True
                        continue
                    buf += d
                    while m := SENTENCE.search(buf):
                        emit(buf[:m.end()])
                        buf = buf[m.end():]
                if buf.strip():
                    emit(buf)
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
                    i = max(0, i - 2)      # ponytail: no playback position; say the last sentence or two again
                i, finished = await speak_from(sentences, i, new, gen_done, ctl, commit, shown)
                if not finished:
                    continue
                while out and not ctl["paused"].is_set():     # the tail: audio still playing after the last sentence was sent
                    await asyncio.sleep(0.05)
                if ctl["paused"].is_set():
                    continue                   # paused during the tail: wait, then say the end again
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
    surfaces = sessions()
    typed = os.environ.get("CLAUDIO_TEXT")
    aec = None if typed else helper()
    in_rate = OUT_RATE if aec else IN_RATE
    ui.banner(facts={"orchestrator": cfg["orchestrator"] or "-", "brain": f"{cfg['model']}/{cfg['effort']}",
                     "voice": ui.short_voice(cfg["voice"]), "echo cancel": "on" if aec else "off",
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
    mic = asyncio.Queue()
    helper_holder = {"proc": None}  # the echo-cancelling helper, when it runs
    ears = {"ws": None}            # the Flux socket, when connected
    later = {"resume": None}       # the timer that resumes a paused reply nobody interrupted after all

    def on_mic(indata, frames, t, status_):
        loop.call_soon_threadsafe(mic.put_nowait, bytes(indata))

    def live():
        t = current["task"]
        return t is not None and not t.done()

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

    def start(text, committed, event=False, fixed=False):
        if live() and not event:
            cut("replaced")
        ev = asyncio.Event()
        if committed:
            ev.set()
        ctl = new_ctl()
        handle = {"text": text, "commit": ev, "ctl": ctl, "paused": ctl["paused"],
                  "committed_at": time.monotonic() if committed else None}
        handle["task"] = asyncio.create_task(reply(text, ev, ctl, fixed=fixed, handle=handle))
        if not live():                         # otherwise it queues behind the speaking reply and claims `current` on its turn
            current.update(handle)
            status["reply"] = handle
        refresh()

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
        m = SLASH.search(words)
        if not m:
            return False
        cmd, arg = m.group(1), m.group(2).strip()
        ui.note(f"/{cmd} {arg}".strip())
        if cmd == "clear":
            cut("cleared")
            asyncio.create_task(fresh_start())
        elif cmd in ("mute", "unmute"):
            set_mute(cmd == "mute")
        elif cmd == "stop":
            cut("stopped")
        elif cmd == "style" and arg in STYLES:
            cut(None)
            config.set_key("style", arg)
            brain.changed.set()
        elif cmd in ("model", "effort", "voice") and arg:
            value = arg.replace(" ", "-")
            if cmd == "voice" and not value.startswith("aura-"):
                value = f"aura-2-{value}-en"
            if (cmd == "model" and value not in config.MODELS) or (cmd == "effort" and value not in config.EFFORTS):
                choices = config.MODELS if cmd == "model" else config.EFFORTS
                start(f"I don't know {cmd} {arg}. Choose {', '.join(choices)}.", committed=True, fixed=True)
                return True
            cut(None)
            config.set_key(cmd, value)
            brain.changed.set()
            if cmd == "voice":
                cfg["voice"] = value               # so the confirmation already speaks in it
                start(f"{arg.capitalize()} from now on.", committed=True, fixed=True)
        elif cmd == "status":
            start(f"Orchestrator {cfg['orchestrator'] or 'none'}. Brain {cfg['model']} at {cfg['effort']} effort. "
                  f"Voice {ui.short_voice(cfg['voice'])}. Memory {'on' if cfg['memory'] else 'off'}.", committed=True, fixed=True)
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
        ws = surfaces.get(sid, (None,))[0]
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
            screen = await loop.run_in_executor(None, pane, sid, 18)
            text = f"[event] {ws} asks for permission: {ev.get('message')}\nIts screen shows:\n{screen}"
        elif ev["event"] == "AskUserQuestion" and ev.get("questions"):
            text = f"[event] {ws} (surface {sid}) asks you to choose:\n{json.dumps(ev['questions'])}"
        else:
            return
        ui.event(ws, ev["event"], asked if ev["event"] == "Stop" else "")
        start(text, committed=True, event=True)

    def flux_url():
        return (f"wss://api.deepgram.com/v2/listen?model={cfg['ears']}&encoding=linear16&sample_rate={in_rate}"
                f"&eot_threshold={cfg['eot']}&eager_eot_threshold={cfg['eager_eot']}&eot_timeout_ms={cfg['eot_timeout_ms']}")

    async def watch_config():
        global cfg
        stamp = os.path.getmtime(config.CONF)
        persona = os.path.getmtime(config.PROMPT)
        while True:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(brain.changed.wait(), 1.0)
            brain.changed.clear()
            await asyncio.sleep(0.2)          # let `claudio set` finish writing
            if os.path.getmtime(config.PROMPT) != persona:        # the persona was edited: new brain, same memory
                persona = os.path.getmtime(config.PROMPT)
                ui.note("persona changed; brain restarting")
                await brain.restart()
                start("[event] Your persona prompt was just edited and you were restarted with it. "
                      "Say in a few words that you are back.", committed=True, event=True)
            now = os.path.getmtime(config.CONF)
            if now == stamp:
                continue
            stamp = now
            new = config.load()
            for w in config.WARNINGS:
                ui.warn(w)
            restart = (new["model"], new["effort"], new["style"]) != (cfg["model"], cfg["effort"], cfg["style"])
            re_ear = any(new[k] != cfg[k] for k in ("ears", "eot", "eager_eot", "eot_timeout_ms"))
            diff = ", ".join(f"{k} → {ui.short_voice(str(new[k]))}" for k in config.DEFAULTS
                             if k not in config.SECRETS and new[k] != cfg[k])
            cfg = new
            ui.setting(f"{diff or 'settings reloaded'}{'  ·  brain restarting' if restart else ''}")
            if re_ear and ears["ws"]:
                asyncio.create_task(ears["ws"].close())   # the listener reconnects with the new ears
            if restart:
                await brain.restart()
                start(f"[event] You were just restarted with model {cfg['model']} at effort {cfg['effort']}, "
                      f"style {cfg['style']}. Say in a few words that you are back, in that style.", committed=True, event=True)

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
            if (speaking.locked() and not cfg["barge_in"]) or not status["gate_open"]:
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
            case "EagerEndOfTurn" if said and not paused():
                if SLASH.search(words):
                    return                      # a command: wait for the final transcript, no brain
                ui.you(said)                    # the eager text is the real one nearly always; a change prints again
                start(said, committed=False)
            case "TurnResumed":
                if live() and not current["commit"].is_set():
                    cut("resumed")
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
                    if live() and not current["commit"].is_set() and norm(current["text"]) == norm(said):
                        current["commit"].set()
                        status["reply"]["committed_at"] = time.monotonic()
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
        sid = next((sid for sid, (w, _, _) in surfaces.items() if w == cfg["orchestrator"]), None)
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
    status["live"].start()
    tasks = [send_mic(), listen_forever(), keys(), watch_config(), brain_watch(), tick(), orchestrator_watch()]
    if not aec:
        tasks.append(shower())
    work = {"task": None}
    loop.add_signal_handler(signal.SIGINT, lambda: work["task"] and work["task"].cancel())
    try:
        if aec:
            helper_proc = await asyncio.create_subprocess_exec(aec, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                               stderr=asyncio.subprocess.DEVNULL)
            helper_holder["proc"] = helper_proc

            async def mic_pump():
                while chunk := await helper_proc.stdout.read(OUT_RATE // 50 * 2):
                    mic.put_nowait(chunk)

            async def speaker_pump():
                """Keep ~150 ms queued in the helper: enough that a busy event loop never starves it,
                little enough that a cut (which also clears the helper's queue) feels instant."""
                bps, lead, chunk_size = OUT_RATE * 2, OUT_RATE * 2 * 0.15, OUT_RATE // 50 * 2
                t0, sent = time.monotonic(), 0
                while True:
                    await asyncio.sleep(0.01)
                    played = (time.monotonic() - t0) * bps
                    if sent < played:          # it ran dry (silence between replies): start the lead over
                        sent = played
                    while out and sent - played < lead:
                        chunk = bytes(out[:chunk_size]); del out[:chunk_size]
                        drained(len(chunk))
                        helper_proc.stdin.write(chunk)
                        sent += len(chunk)
                    await helper_proc.stdin.drain()
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
        status["live"].stop()
        server.close()
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
