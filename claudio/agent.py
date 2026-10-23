"""The voice loop: Deepgram Flux ears (eager end of turn, preemptive generation, barge-in),
one long-lived `claude -p` brain, Deepgram Aura mouth sentence by sentence, and a socket where
the Claude Code hooks (`claudio hook ...`) report what sessions did."""
import asyncio, json, os, re, shutil, signal, subprocess, sys, time
import sounddevice as sd, websockets
from rich.console import Console
from rich.panel import Panel
from . import config

console = Console(highlight=False)
IN_RATE, OUT_RATE = 16000, 24000    # the plain path; the echo-cancelling helper runs both ways at 24000
SENTENCE = re.compile(r"[.!?]['\")]?\s")
CMUX = (os.environ.get("CMUX_BUNDLED_CLI_PATH") or shutil.which("cmux")
        or "/Applications/cmux.app/Contents/Resources/bin/cmux")
cfg, surfaces = {}, {}
out = bytearray()             # audio waiting for the speaker
speaking = asyncio.Lock()     # one reply at a time, mouth included; later ones queue


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


class Brain:
    """One claude process. A turn is a user line on stdin; its text deltas stream back."""
    def __init__(self):
        self.proc, self.session_id, self.busy = None, None, False
        self.lock = asyncio.Lock()
        self.handoffs = {}             # workspace title -> time of the last `cmux agent message` to it

    async def start(self):
        me = os.path.dirname(os.path.abspath(sys.argv[0]))      # so the brain can run `claudio set`
        env = dict(os.environ, PATH=f"{me}:{os.path.dirname(CMUX)}:{os.environ.get('PATH', '')}")
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
            env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)

    async def send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        await self.proc.stdin.drain()

    async def interrupt(self):
        if self.busy:
            await self.send({"type": "control_request", "request_id": f"cut-{os.urandom(4).hex()}",
                             "request": {"subtype": "interrupt"}})

    def saw(self, ev):
        """Side channel: the brain's own session id, and which sessions it handed work to."""
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            self.session_id = ev.get("session_id")
        if ev.get("type") == "assistant":
            for c in ev["message"].get("content", []):
                if c.get("type") == "tool_use" and c.get("name") == "Bash":
                    if m := re.search(r'cmux agent message\s+(?:"([^"]+)"|(\S+))', c["input"].get("command", "")):
                        self.handoffs[m.group(1) or m.group(2)] = time.time()

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
                        return q.put_nowait(None)
                    ev = json.loads(line)
                    self.saw(ev)
                    if ev.get("type") == "stream_event":
                        e = ev["event"]
                        if e.get("type") == "content_block_delta" and e["delta"].get("type") == "text_delta":
                            spoke = True
                            q.put_nowait(e["delta"]["text"])
                        elif e.get("type") == "content_block_start" and e["content_block"].get("type") == "tool_use" and not spoke:
                            spoke = True
                            q.put_nowait("One moment. ")
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
        console.print(f"[yellow]echo canceller did not build; using the plain mic (headphones for barge-in)[/]\n[dim]{r.stderr[-300:]}[/]")
        return None
    return exe


async def reply(text, commit):
    """One spoken reply; audio held until `commit` (the turn's final transcript matched the eager one)."""
    async with speaking:
        sent = got = 0
        held = bytearray()
        auth = {"Authorization": f"Token {cfg['deepgram_api_key']}"}
        url = f"wss://api.deepgram.com/v1/speak?model={cfg['voice']}&encoding=linear16&sample_rate={OUT_RATE}"
        try:
            async with websockets.connect(url, additional_headers=auth) as tts:
                async def play():
                    nonlocal got
                    try:
                        async for m in tts:
                            if isinstance(m, bytes):
                                if commit.is_set():
                                    if held:
                                        out.extend(held); held.clear()
                                    out.extend(m)
                                else:
                                    held.extend(m)
                            elif json.loads(m).get("type") == "Flushed":
                                got += 1
                    except websockets.ConnectionClosed:
                        pass
                player = asyncio.create_task(play())

                async def say(s):
                    nonlocal sent
                    await tts.send(json.dumps({"type": "Speak", "text": s}))
                    await tts.send(json.dumps({"type": "Flush"}))
                    sent += 1

                buf = ""
                console.print("[bold green]claudio[/] ", end="")
                async for d in brain.turn(text):
                    console.print(d, end="", markup=False)
                    buf += d
                    while m := SENTENCE.search(buf):
                        await say(buf[:m.end()])
                        buf = buf[m.end():]
                if buf.strip():
                    await say(buf)
                console.print()
                while got < sent:
                    await asyncio.sleep(0.02)
                await commit.wait()
                if held:
                    out.extend(held); held.clear()
                player.cancel()
            while out:
                await asyncio.sleep(0.05)
        finally:
            out.clear()


def on_out(outdata, frames, t, status):
    n = len(outdata)
    b = bytes(out[:n]); del out[:n]
    outdata[:len(b)] = b
    outdata[len(b):] = b"\x00" * (n - len(b))


def norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).split()


async def main():
    global cfg, surfaces
    cfg = config.load()
    if not cfg["deepgram_api_key"]:
        raise SystemExit("No Deepgram key. Run `claudio setup`, or export DEEPGRAM_API_KEY.")
    surfaces = sessions()
    aec = None if os.environ.get("CLAUDIO_TEXT") else helper()
    in_rate = OUT_RATE if aec else IN_RATE
    console.print(Panel.fit(
        f"[bold]claudio[/]  orchestrator [cyan]{cfg['orchestrator'] or '-'}[/]  brain [cyan]{cfg['model']}/{cfg['effort']}[/]  "
        f"voice [cyan]{cfg['voice']}[/]  echo cancel [cyan]{'on' if aec else 'off'}[/]\n"
        f"[dim]talk to it · Enter cuts a reply · Ctrl-C quits · `claudio setup` to change things[/]",
        border_style="green"))
    await brain.start()
    with console.status("[dim]warming up the brain…[/]"):
        async for _ in brain.turn("Say only: ready."):
            pass

    if text := os.environ.get("CLAUDIO_TEXT"):
        with sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=OUT_RATE // 50, callback=on_out):
            console.print(f"[bold cyan]you[/] {text}")
            ev = asyncio.Event(); ev.set()
            await reply(text, ev)
        return brain.proc.terminate()

    loop = asyncio.get_running_loop()
    mic = asyncio.Queue()
    current = {"task": None, "text": "", "commit": None}
    audio = {"proc": None}         # the echo-cancelling helper, when it runs

    def on_mic(indata, frames, t, status):
        loop.call_soon_threadsafe(mic.put_nowait, bytes(indata))

    def live():
        t = current["task"]
        return t is not None and not t.done()

    def cut(why="cut"):
        if live():
            current["task"].cancel()
            out.clear()
            if audio["proc"]:
                audio["proc"].send_signal(signal.SIGUSR1)     # drop what the helper has queued
            console.print(f"\n[dim]({why})[/]")

    def start(text, committed, event=False):
        if live() and not event:
            cut("replaced")
        ev = asyncio.Event()
        if committed:
            ev.set()
        current.update(task=asyncio.create_task(reply(text, ev)), text=text, commit=ev)

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
        console.print(f"\n[magenta]event[/] [dim]{ws}: {ev['event']}[/]")
        start(text, committed=True, event=True)

    async def watch_config():
        global cfg
        stamp = os.path.getmtime(config.CONF)
        while True:
            await asyncio.sleep(2)
            now = os.path.getmtime(config.CONF)
            if now == stamp:
                continue
            stamp = now
            new = config.load()
            restart = (new["model"], new["effort"]) != (cfg["model"], cfg["effort"])
            cfg = new
            console.print(f"\n[dim](settings reloaded{', brain restarting' if restart else ''})[/]")
            if restart:
                async with brain.lock:
                    brain.proc.terminate()
                    await brain.start()

    async def send_mic():
        while True:
            b = await mic.get()
            if speaking.locked() and not cfg["barge_in"]:
                b = b"\x00" * len(b)
            await flux.send(b)

    async def listen():
        console.print("[green]🎤 listening[/]")
        async for m in flux:
            ev = json.loads(m)
            if ev.get("type") != "TurnInfo":
                continue
            said = ev.get("transcript", "").strip()
            match ev["event"]:
                case "StartOfTurn":
                    if cfg["barge_in"] and live() and current["commit"].is_set():
                        cut()
                case "EagerEndOfTurn" if said:
                    console.print(f"\n[bold cyan]you[/] [dim]{said}[/]")
                    start(said, committed=False)
                case "TurnResumed":
                    if live() and not current["commit"].is_set():
                        cut("resumed")
                case "EndOfTurn" if said:
                    if live() and not current["commit"].is_set() and norm(current["text"]) == norm(said):
                        current["commit"].set()
                    else:
                        console.print(f"\n[bold cyan]you[/] {said}")
                        start(said, committed=True)

    async def keys():
        while await loop.run_in_executor(None, sys.stdin.readline):
            cut()

    if os.path.exists(config.SOCK):
        os.unlink(config.SOCK)
    server = await asyncio.start_unix_server(on_event, config.SOCK)
    flux_url = (f"wss://api.deepgram.com/v2/listen?model={cfg['ears']}&encoding=linear16&sample_rate={in_rate}"
                f"&eot_threshold={cfg['eot']}&eager_eot_threshold={cfg['eager_eot']}")
    try:
        async with websockets.connect(flux_url, additional_headers={"Authorization": f"Token {cfg['deepgram_api_key']}"}) as flux:
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
                await asyncio.gather(mic_pump(), speaker_pump(), send_mic(), listen(), keys(), watch_config())
            else:
                with sd.RawInputStream(samplerate=IN_RATE, channels=1, dtype="int16", blocksize=IN_RATE // 50, callback=on_mic), \
                     sd.RawOutputStream(samplerate=OUT_RATE, channels=1, dtype="int16", blocksize=OUT_RATE // 50, callback=on_out):
                    await asyncio.gather(send_mic(), listen(), keys(), watch_config())
    finally:
        server.close()
        brain.proc.terminate()
        if audio["proc"]:
            audio["proc"].terminate()
        if os.path.exists(config.SOCK):
            os.unlink(config.SOCK)


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[dim]bye[/]")
