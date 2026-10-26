"""Run the real claudio.agent.main() for one scenario, with fakes only at the edges: Flux's socket, the brain's
`claude -p` process, the mouth, the sound devices. Prints what claudio did, one line per thing, with the time.
Usage: XDG_CONFIG_HOME=<a temp dir> python tests/flow.py <scenario>      (test_flow.py runs them all)"""
import asyncio, json, os, signal, sys, tempfile, time

from claudio import agent, config, ui
import websockets.exceptions, websockets.asyncio.client   # what the real connect() would have imported

SC = sys.argv[1]
os.environ.pop("CMUX_SURFACE_ID", None)    # run from a cmux pane, it would read that pane's real inbox
T0 = time.monotonic()
LOG = []


def log(*a):
    LOG.append(f"{time.monotonic() - T0:5.2f}  " + " ".join(str(x) for x in a))


# ---- the screen: record what would be printed
ui.console.file = open(os.devnull, "w")
ui.you = lambda t, tentative=False: log("YOU", repr(t))
ui.note = lambda t: log("NOTE", t)
ui.warn = lambda t: log("WARN", t)
ui.block = lambda md, colors=True: log("BLOCK", repr(md))
ui.me_line = lambda s, first, live=False, secs=None: log("ME", repr(s))
ui.event = lambda ws, kind, asked="": log("EVENT", ws, kind)


# ---- settings: defaults and a fake key; the files (allow, the socket) live in XDG_CONFIG_HOME
def fake_load():
    c = dict(config.DEFAULTS)
    c.update(deepgram_api_key="x", memory=False, narrate="all", mouth="deepgram")
    return c
config.load = fake_load
config.SOCK = os.path.join(tempfile.mkdtemp(), "s")     # a unix socket path must stay under 104 characters
os.makedirs(config.DIR, exist_ok=True)
agent.sessions = lambda: {"abcd1234": ("ws1", None, None, "abcd1234")}
agent.helper = lambda: None


# ---- sound devices: the speaker drains `out` in real time
class FakeIn:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def start(self): pass


class FakeOut(FakeIn):
    def __init__(self, *a, callback=None, **k):
        self.cb = callback

    def __enter__(self):
        async def drain():
            buf = bytearray(480 * 2)
            while True:
                await asyncio.sleep(0.02)
                self.cb(buf, 480, None, None)
        self.task = asyncio.get_running_loop().create_task(drain())
        return self
agent.sd.RawInputStream, agent.sd.RawOutputStream = FakeIn, FakeOut


# ---- the brain: a fake `claude -p` under the real Brain.turn, send and interrupt
REPLIES = {
    "markdown": "Here is how the three compare:\n\n| Engine | Speed | License |\n|---|---|---|\n| Kokoro | fast | Apache |\n"
                "| Piper | faster | MIT |\n\n**Kokoro** wins on quality. Two things to try:\n- Run `claudio set mouth local`. "
                "It downloads once.\n- Check the speed.\nHere is the call:\n```python\nkokoro.create(text, voice)\n```\n"
                "It turns text into audio.",
    "race-event": "Once upon a time there was a fox. It ran. It jumped. It slept. The end.",
}
INTERRUPT = 1.5            # how long a cut brain takes to drain to its result


class FakeStdin:
    def __init__(self, proc): self.proc = proc

    def write(self, b):
        for line in b.decode().splitlines():
            self.proc.got(json.loads(line))

    async def drain(self): pass


class FakeProc:
    def __init__(self):
        self.stdout, self.stdin = asyncio.StreamReader(), FakeStdin(self)
        self.returncode, self.gen, self.dead = None, None, asyncio.Event()

    def emit(self, obj):
        self.stdout.feed_data((json.dumps(obj) + "\n").encode())

    def got(self, msg):
        if msg["type"] == "user":
            text = msg["message"]["content"]
            log("BRAIN", repr(text[:60]))
            self.gen = asyncio.get_running_loop().create_task(self.answer(text))
        elif msg["type"] == "control_request":
            if self.gen:
                self.gen.cancel()
            asyncio.get_running_loop().call_later(INTERRUPT, lambda: self.emit({"type": "result"}))

    async def answer(self, text):
        await asyncio.sleep(0.3)
        words = REPLIES.get(SC, "It is noon. Have a nice day.")
        for i in range(0, len(words), 4):        # in 4-character pieces: a block or a style split anywhere
            self.emit({"type": "stream_event", "event": {"type": "content_block_delta",
                                                        "delta": {"type": "text_delta", "text": words[i:i + 4]}}})
            await asyncio.sleep(0.01)
        self.emit({"type": "stream_event", "event": {"type": "content_block_stop"}})
        refused = SC.startswith("allow") and "open a PR" in text and not os.path.exists(config.ALLOW)
        self.emit({"type": "result", **({"permission_denials": [{"tool_name": "Bash", "tool_input": {
            "command": "gh pr create --title x"}}]} if refused else {})})

    async def wait(self):
        await self.dead.wait()

    def terminate(self):
        self.returncode = 0
        self.dead.set()


async def fake_start(self=agent.brain):
    log("START", "no permission checks" if agent.status["skip"] else "checks on")
    self.proc, self.resumed, self.started_at = FakeProc(), False, time.monotonic()
agent.brain.start = fake_start


# ---- the mouth: a second of audio per sentence, or unreachable
class FakeMouth:
    def __init__(self): self.q, self.sent, self.got = asyncio.Queue(), 0, 0
    async def open(self): pass

    async def receive(self, on_audio):
        while True:
            await self.q.get()
            await asyncio.sleep(0.1)
            on_audio(b"\x01\x00" * 24000)
            self.got += 1

    async def say(self, text):
        log("SAY", repr(text))
        self.q.put_nowait(text)
        self.sent += 1

    def done(self): return self.got >= self.sent
    async def finish(self): pass
    async def close(self): pass


class GoneMouth:
    async def open(self):
        raise OSError("unreachable")
agent.new_mouth = GoneMouth if SC == "mouth-gone" else FakeMouth


# ---- the ears: Flux events on a script; ("sock", t) is a session reporting in over claudio's socket
def turn(event, transcript=""):
    return {"type": "TurnInfo", "event": event, "transcript": transcript}

SCENARIOS = {   # name: (seconds to run, script)
    "mouth-gone": (5, [(0.1, turn("StartOfTurn")), (0.5, turn("EagerEndOfTurn", "what time is it")),
                       (3.5, turn("EndOfTurn", "what time is it"))]),
    "race-event": (9, [(0.1, turn("StartOfTurn")), ("sock", 0.3), (1.6, turn("EagerEndOfTurn", "wait stop")),
                       (1.9, turn("TurnResumed")), (2.5, turn("EndOfTurn", "wait stop and tell me the weather"))]),
    "resumed": (5, [(0.1, turn("StartOfTurn")), (0.5, turn("EagerEndOfTurn", "what is the time")),
                    (1.0, turn("TurnResumed")), (1.8, turn("EndOfTurn", "what is the time"))]),
    "markdown": (11, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "compare the engines"))]),
    "allow-yes": (8, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")),
                      (4.5, turn("StartOfTurn")), (4.7, turn("EndOfTurn", "yes"))]),
    "allow-no": (7, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")),
                     (4.5, turn("StartOfTurn")), (4.7, turn("EndOfTurn", "no"))]),
    "voice-banana": (4, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "slash voice banana"))]),
    "skip": (8, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "slash skip permission")),
                 (2.5, turn("StartOfTurn")), (2.7, turn("EndOfTurn", "yes")),
                 (5.0, turn("StartOfTurn")), (5.2, turn("EndOfTurn", "slash permissions ask"))]),
}
RUN, SCRIPT = SCENARIOS[SC]


class FakeEars:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    async def send(self, b): pass
    async def close(self): pass
    def __aiter__(self): return self.events()

    async def events(self):
        base = time.monotonic()
        for at, what in SCRIPT:
            if at == "sock":
                await asyncio.sleep(max(0, base + what - time.monotonic()))
                r, w = await asyncio.open_unix_connection(config.SOCK)
                w.write((json.dumps({"event": "Stop", "session": "other", "surface": "abcd1234", "text": "done"}) + "\n").encode())
                await w.drain()
                w.close()
                continue
            await asyncio.sleep(max(0, base + at - time.monotonic()))
            log("FLUX", what["event"], repr(what["transcript"]))
            yield json.dumps(what)
        await asyncio.Event().wait()
agent.websockets.connect = FakeEars


async def run():
    asyncio.get_running_loop().call_later(RUN, lambda: os.kill(os.getpid(), signal.SIGINT))
    await agent.main()

asyncio.run(run())
print("\n".join(LOG))
