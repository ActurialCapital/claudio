"""The voice loop: Deepgram Flux ears (eager end of turn, preemptive generation, barge-in),
one long-lived `claude -p` brain, Deepgram Aura mouth sentence by sentence, and a socket where
the Claude Code hooks (`claudio hook ...`) report what sessions did.

Robustness: the ears reconnect with backoff, the brain restarts if it dies (and resumes its last
session, so it remembers), the mouth retries once. An interruption first pauses the reply; a real
turn then cuts it, a backchannel ("mm-hm") or noise lets it carry on from a sentence back."""
import asyncio, contextlib, json, os, re, shutil, signal, subprocess, sys, time
import sounddevice as sd, websockets
from . import config, ui
from .ui import console
IN_RATE, OUT_RATE = 16000, 24000    # the plain path; the echo-cancelling helper runs both ways at 24000
SENTENCE = re.compile(r"[.!?]['\")]?\s")
BLOCK_END = object()          # a text block ended (a tool runs next): speak what is buffered, new transcript line
BACKCHANNEL = {"yeah", "yes", "yep", "ok", "okay", "mm", "mhm", "hmm", "uh", "huh", "um", "right", "sure", "oh", "ah", "no"}
CMUX = (os.environ.get("CMUX_BUNDLED_CLI_PATH") or shutil.which("cmux")
        or "/Applications/cmux.app/Contents/Resources/bin/cmux")
SESSION = os.path.join(config.DIR, "session")
cfg, surfaces = {}, {}
out = bytearray()             # audio waiting for the speaker
speaking = asyncio.Lock()     # one reply at a time, mouth included; later ones queue
status = {"live": None}       # the state line at the bottom of the terminal


def state(s):
    if status["live"]:
        status["live"].update(f"[dim]{s}[/]")


def sessions():
    """cmux's surfaces, keyed by 8-char surface id: (workspace title, surface title, cwd)."""
    found, ws = {}, None
    try:
        text = subprocess.run([CMUX, "surface", "list"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return found
    for line in text.splitlines():
        if m := re.match(r"^\s{4}(\S.*?)\s+workspace:\d+", line):
            ws = m.group(1)
        elif m := re.match(r"^\s{6}\S\s+([0-9A-F]{8})\s+(.*?)\s{2,}(\S+)", line):
            found[m.group(1)] = (ws, m.group(2), m.group(3))
    return found


def system_prompt():
    lines = [f"- {w}: surface {sid} ({t}), in {c}" for sid, (w, t, c) in surfaces.items() if w]
    return (open(config.PROMPT).read()
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
        self.proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json",
            "--include-partial-messages", "--verbose", "--setting-sources", "",
            "--append-system-prompt", system_prompt(),
            "--allowedTools", "Read", "Grep", "Glob",
            "Bash(cmux agent message:*)", "Bash(cmux surface list:*)", "Bash(cmux read-screen:*)",
            "Bash(cmux new-workspace:*)", "Bash(cmux new-split:*)", "Bash(cmux new-surface:*)",
            "Bash(claudio set:*)",
            *(["--model", cfg["model"]] if cfg["model"] != "default" else []),
            *(["--effort", cfg["effort"]] if cfg["effort"] else []),
            *(["--resume", resume] if resume else []),
            env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=open(os.path.join(config.DIR, "brain.log"), "ab"))
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
            with contextlib.suppress(OSError):
                open(SESSION, "w").write(f"{self.session_id} {time.time()}")
        if ev.get("type") == "assistant":
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_use" and c.get("name") == "Bash":
                    cmd = c["input"].get("command", "")
                    if m := re.search(r'cmux agent message\s+(?:"([^"]+)"|(\S+))', cmd):
                        self.handoffs[m.group(1) or m.group(2)] = time.time()
                    if "claudio set" in cmd:
                        self.changed.set()

    async def turn(self, text):
        async with self.lock:
            self.busy = True
            await self.send({"type": "user", "message": {"role": "user", "content": text}})
            q = asyncio.Queue()

            async def pump():
                spoke = False
                while True:
                    line = await self.proc.stdout.readline()
                    if not line:
                        return q.put_nowait(None)      # it died; the watchdog restarts it
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
                    elif ev.get("type") == "result":
                        return q.put_nowait(None)

            task = asyncio.create_task(pump())
            try:
                while (d := await q.get()) is not None:
                    yield d
            finally:
                if not task.done():
                    await self.interrupt()      # a cut: stop Claude, then drain to its result
                await task
                self.busy = False


brain = Brain()


def helper():
    """The echo-cancelling audio helper (audio.swift), built once with swiftc. None when it cannot be."""
    src = os.path.join(os.path.dirname(__file__), "audio.swift")
    exe = os.path.join(config.DIR, "bin", "claudio-audio")
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


async def speak_from(sentences, i, new, gen_done, ctl, commit):
    """Speak sentences[i:] over one Speak socket until done or paused. Returns (next index, finished)."""
    auth = {"Authorization": f"Token {cfg['deepgram_api_key']}"}
    url = f"wss://api.deepgram.com/v1/speak?model={cfg['voice']}&encoding=linear16&sample_rate={OUT_RATE}"
    tts = None
    for attempt in (1, 2):
        try:
            tts = await websockets.connect(url, additional_headers=auth)
            break
        except (OSError, websockets.exceptions.WebSocketException):
            await asyncio.sleep(1)
    if tts is None:
        ui.warn("mouth lost: Deepgram speak unreachable; text only")
        await gen_done.wait()
        return len(sentences), True
    got = sent = 0
    held = bytearray()

    async def play():
        nonlocal got
        try:
            async for m in tts:
                if isinstance(m, bytes):
                    if commit.is_set():
                        if held:
                            out.extend(held); held.clear()
                        out.extend(m)
                        state("speaking")
                    else:
                        held.extend(m)
                elif json.loads(m).get("type") == "Flushed":
                    got += 1
        except websockets.ConnectionClosed:
            pass
    player = asyncio.create_task(play())
    try:
        while True:
            while i >= len(sentences) and not gen_done.is_set() and not ctl["paused"].is_set():
                new.clear()
                await first_of(new.wait(), ctl["paused"].wait())
            if ctl["paused"].is_set():
                return i, False
            if i >= len(sentences):
                break
            await tts.send(json.dumps({"type": "Speak", "text": sentences[i]}))
            await tts.send(json.dumps({"type": "Flush"}))
            sent += 1
            i += 1
        while got < sent and not ctl["paused"].is_set():
            await asyncio.sleep(0.02)
        if ctl["paused"].is_set():
            return i, False
        await commit.wait()
        if held:
            out.extend(held); held.clear()
        return i, True
    finally:
        player.cancel()
        with contextlib.suppress(Exception):
            await tts.close()


async def reply(text, commit, ctl):
    """One spoken reply. Text streams from the brain into sentences; the mouth follows, and can be
    paused (a possible interruption) and resumed a sentence or two back."""
    async with speaking:
        state("thinking")
        sentences, new, gen_done = [], asyncio.Event(), asyncio.Event()

        async def generate():
            buf, fresh = "", True

            def emit(s):
                sentences.append(s)
                new.set()
            try:
                async for d in brain.turn(text):
                    if d is BLOCK_END:
                        if buf.strip():
                            emit(buf)
                        buf = ""
                        if not fresh:
                            console.print()
                        fresh = True
                        continue
                    if fresh:
                        ui.me_prefix()
                        fresh = False
                    console.print(d, end="", markup=False)
                    buf += d
                    while m := SENTENCE.search(buf):
                        emit(buf[:m.end()])
                        buf = buf[m.end():]
                if buf.strip():
                    emit(buf)
                if not fresh:
                    console.print()
            finally:
                gen_done.set()
                new.set()

        gen = asyncio.create_task(generate())
        i = 0
        try:
            while True:
                if ctl["paused"].is_set():
                    state("paused")
                    await ctl["resume"].wait()
                    ctl["resume"].clear()
                    ctl["paused"].clear()
                    i = max(0, i - 2)      # ponytail: no playback position; say the last sentence or two again
                i, finished = await speak_from(sentences, i, new, gen_done, ctl, commit)
                if finished:
                    break
            while out and not ctl["paused"].is_set():
                await asyncio.sleep(0.05)
        finally:
            if not gen.done():
                gen.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await gen
            out.clear()
            state("listening")


def on_out(outdata, frames, t, status_):
    n = len(outdata)
    b = bytes(out[:n]); del out[:n]
    outdata[:len(b)] = b
    outdata[len(b):] = b"\x00" * (n - len(b))


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).split()


def backchannel(said):
    words = norm(said)
    return len(words) < 2 or all(w in BACKCHANNEL for w in words)


async def main():
    global cfg, surfaces
    cfg = config.load()
    if not cfg["deepgram_api_key"]:
        raise SystemExit("No Deepgram key. Run `claudio setup`, or export DEEPGRAM_API_KEY.")
    surfaces = sessions()
    typed = os.environ.get("CLAUDIO_TEXT")
    aec = None if typed else helper()
    in_rate = OUT_RATE if aec else IN_RATE
    ui.banner(facts={"orchestrator": cfg["orchestrator"] or "-", "brain": f"{cfg['model']}/{cfg['effort']}",
                     "voice": ui.short_voice(cfg["voice"]), "echo cancel": "on" if aec else "off",
                     "memory": "on" if remembered_session() else "fresh"},
              hints="talk · Enter cuts a reply · Ctrl-C quits · claudio setup to change things")
    await brain.start()
    with console.status("[dim]warming up the brain…[/]"):
        async for _ in brain.turn("Say only: ready."):
            pass

    if typed:
        with sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=OUT_RATE // 50, callback=on_out):
            ui.you(typed)
            ev = asyncio.Event(); ev.set()
            await reply(typed, ev, new_ctl())
        return brain.proc.terminate()

    loop = asyncio.get_running_loop()
    mic = asyncio.Queue()
    current = {"task": None, "text": "", "commit": None, "ctl": None}
    audio = {"proc": None}         # the echo-cancelling helper, when it runs
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
        out.clear()
        if audio["proc"]:
            audio["proc"].send_signal(signal.SIGUSR1)     # drop what the helper has queued

    def cut(why="cut"):
        if later["resume"]:
            later["resume"].cancel()
        if live():
            current["task"].cancel()
            drop_audio()
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

    def start(text, committed, event=False):
        if live() and not event:
            cut("replaced")
        ev = asyncio.Event()
        if committed:
            ev.set()
        ctl = new_ctl()
        current.update(task=asyncio.create_task(reply(text, ev, ctl)), text=text, commit=ev, ctl=ctl)

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
        if ev["event"] == "Stop" and ev.get("text") and brain.handoffs.get(ws, 0) > time.time() - 1800:
            text = f"[event] {ws} finished a turn. Its last message:\n{ev['text']}"
        elif ev["event"] == "Notification" and ev.get("kind") == "permission_prompt":
            text = f"[event] {ws} asks for permission: {ev.get('message')}"
        elif ev["event"] == "AskUserQuestion" and ev.get("questions"):
            text = f"[event] {ws} (surface {sid}) asks you to choose:\n{json.dumps(ev['questions'])}"
        else:
            return
        ui.event(ws, ev["event"])
        start(text, committed=True, event=True)

    def flux_url():
        return (f"wss://api.deepgram.com/v2/listen?model={cfg['ears']}&encoding=linear16&sample_rate={in_rate}"
                f"&eot_threshold={cfg['eot']}&eager_eot_threshold={cfg['eager_eot']}&eot_timeout_ms={cfg['eot_timeout_ms']}")

    async def watch_config():
        global cfg
        stamp = os.path.getmtime(config.CONF)
        while True:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(brain.changed.wait(), 1.0)
            brain.changed.clear()
            await asyncio.sleep(0.2)          # let `claudio set` finish writing
            now = os.path.getmtime(config.CONF)
            if now == stamp:
                continue
            stamp = now
            new = config.load()
            restart = (new["model"], new["effort"]) != (cfg["model"], cfg["effort"])
            re_ear = any(new[k] != cfg[k] for k in ("ears", "eot", "eager_eot", "eot_timeout_ms"))
            diff = ", ".join(f"{k} → {new[k]}" for k in config.DEFAULTS if k != "deepgram_api_key" and new[k] != cfg[k])
            cfg = new
            ui.note(f"settings: {diff or 'reloaded'}{'; brain restarting' if restart else ''}")
            if re_ear and ears["ws"]:
                asyncio.create_task(ears["ws"].close())   # the listener reconnects with the new ears
            if restart:
                await brain.restart()
                start(f"[event] You were just restarted with model {cfg['model']} at effort {cfg['effort']}. "
                      "Say in a few words that you are back.", committed=True, event=True)

    async def brain_watch():
        while True:
            proc = brain.proc
            await proc.wait()
            await asyncio.sleep(0.1)
            if brain.expected_exit or brain.proc is not proc:
                continue
            ui.warn("the brain died; restarting it")
            async with brain.lock:
                await brain.start()
            start("[event] You just crashed and were restarted. Say in a few words that you are back, "
                  "and ask the user to repeat what they said last if they were mid-request.", committed=True, event=True)

    async def send_mic():
        while True:
            b = await mic.get()
            ws = ears["ws"]
            if ws is None:
                continue
            if speaking.locked() and not cfg["barge_in"]:
                b = b"\x00" * len(b)
            with contextlib.suppress(websockets.ConnectionClosed):
                await ws.send(b)

    def heard(ev):
        said = ev.get("transcript", "").strip()
        match ev["event"]:
            case "StartOfTurn":
                if cfg["barge_in"] and live() and current["commit"].is_set():
                    pause()
            case "EagerEndOfTurn" if said and not paused():
                ui.you(said, tentative=True)
                start(said, committed=False)
            case "TurnResumed":
                if live() and not current["commit"].is_set():
                    cut("resumed")
            case "EndOfTurn":
                if paused():
                    if said and not backchannel(said):     # a real interruption: this is the new turn
                        ui.you(said)
                        cut()
                        start(said, committed=True)
                    else:
                        resume()
                elif said:
                    if live() and not current["commit"].is_set() and norm(current["text"]) == norm(said):
                        current["commit"].set()
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
                    state("listening")
                    async for m in ws:
                        ev = json.loads(m)
                        if ev.get("type") == "TurnInfo":
                            heard(ev)
            except (OSError, websockets.exceptions.WebSocketException) as e:
                ears["ws"] = None
                state(f"ears lost ({type(e).__name__}); reconnecting in {delay}s")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 15)
            else:
                ears["ws"] = None        # closed on purpose (new ear settings): straight back

    async def keys():
        while await loop.run_in_executor(None, sys.stdin.readline):
            cut()

    if os.path.exists(config.SOCK):
        os.unlink(config.SOCK)
    server = await asyncio.start_unix_server(on_event, config.SOCK)
    status["live"] = console.status("[dim]listening[/]")
    status["live"].start()
    tasks = [send_mic(), listen_forever(), keys(), watch_config(), brain_watch()]
    try:
        if aec:
            helper_proc = await asyncio.create_subprocess_exec(aec, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                               stderr=asyncio.subprocess.DEVNULL)
            audio["proc"] = helper_proc

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
                        helper_proc.stdin.write(chunk)
                        sent += len(chunk)
                    await helper_proc.stdin.drain()
            await asyncio.gather(mic_pump(), speaker_pump(), *tasks)
        else:
            with sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16", blocksize=IN_RATE // 50, callback=on_mic), \
                 sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=OUT_RATE // 50, callback=on_out):
                await asyncio.gather(*tasks)
    finally:
        status["live"].stop()
        server.close()
        brain.expected_exit = True
        brain.proc.terminate()
        if audio["proc"]:
            audio["proc"].terminate()
        if os.path.exists(config.SOCK):
            os.unlink(config.SOCK)


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print()
        ui.note("bye")
