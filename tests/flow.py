"""Run the real claudio.agent.main() for one scenario, with fakes only at the edges: Flux's socket, the brain's
`claude` process, the mouth, the sound devices. Prints what claudio did, one line per thing, with the time.
Usage: XDG_CONFIG_HOME=<a temp dir> python tests/flow.py <scenario>      (test_flow.py runs them all)"""
import asyncio, json, os, signal, sys, tempfile, time

from claudio import agent, config, ui
from claude_agent_sdk import Transport
import websockets.exceptions, websockets.asyncio.client   # what the real connect() would have imported

SC = sys.argv[1]
KEYS = os.pipe()                          # the keyboard: a pipe the script types into, never the real terminal
os.dup2(KEYS[0], 0)
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
NEW = "9F8E7D6C-1111-2222-3333-444455556666"     # a session opened after claudio started: listed from the 2nd look on
listed = []
agent.sessions = lambda: listed.append(1) or {"abcd1234": ("ws1", None, None, "abcd1234"),
                                              **({NEW[:8]: ("Login", None, None, NEW)} if len(listed) > 1 else {})}
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


# ---- the brain: a fake CLI under the real SDK client and Brain.turn, query and interrupt
REPLIES = {
    "markdown": "Here is how the three compare:\n\n| Engine | Speed | License |\n|---|---|---|\n| Kokoro | fast | Apache |\n"
                "| Piper | faster | MIT |\n\n**Kokoro** wins on quality. Two things to try:\n- Run `claudio set mouth local`. "
                "It downloads once.\n- Check the speed.\nHere is the call:\n```python\nkokoro.create(text, voice)\n```\n"
                "It turns text into audio.",
    "race-event": "Once upon a time there was a fox. It ran. It jumped. It slept. The end.",
    "loose-table": "Here it is.\nChange | Type\n`claudio open` for links and notes | Feature\nSkip mode for one run | Feature\n",
}
INTERRUPT = 1.5            # how long a cut brain takes to drain to its result


def ok(req):
    return {"type": "control_response", "response": {"subtype": "success", "request_id": req["request_id"], "response": {}}}


class FakeProc:
    """The CLI's side of the stream-json protocol: control requests answered, a scripted reply per user line."""
    def __init__(self):
        self.stdout, self.gen, self.perm = asyncio.StreamReader(), None, None

    def emit(self, obj):
        self.stdout.feed_data((json.dumps({"session_id": "s", "uuid": "u", **obj}) + "\n").encode())

    def result(self, **k):
        self.emit({"type": "result", "subtype": "success", "duration_ms": 1, "duration_api_ms": 1,
                   "is_error": False, "num_turns": 1, **k})

    def got(self, msg):
        if msg["type"] == "user":
            text = msg["message"]["content"]
            log("BRAIN", repr(text[:60]))
            self.gen = asyncio.get_running_loop().create_task(self.answer(text))
        elif msg["type"] == "control_response" and msg["response"]["request_id"] == "perm":
            r = msg["response"]["response"]
            log("PERM", r["behavior"], json.dumps(r.get("updatedPermissions") or r.get("message", "")))
            if not self.perm.done():          # a cut cancelled the turn waiting on it
                self.perm.set_result(r)
        elif msg["type"] == "control_request":
            self.emit(ok(msg))
            if msg["request"]["subtype"] == "interrupt":
                if self.gen:
                    self.gen.cancel()
                asyncio.get_running_loop().call_later(INTERRUPT, self.result)

    async def answer(self, text):
        await asyncio.sleep(0.3)
        if SC == "handoff-new" and "fix the login" in text:    # hand it over by surface id, as the persona says
            self.emit({"type": "assistant", "message": {"model": "m", "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {
                "command": f'cmux agent message {NEW} --from Voice "[spoken by the user, transcribed by claudio] fix the login"'}}]}})
        if SC.startswith("allow") and ("open a PR" in text or "do it" in text):   # a tool the rules don't cover: the SDK asks claudio
            await self.say("Let me open it. " * (4 if SC == "allow-early" else 1))
            self.perm = asyncio.get_running_loop().create_future()
            self.emit({"type": "control_request", "request_id": "perm", "request": {
                "subtype": "can_use_tool", "tool_name": "Bash", "input": {"command": "gh pr create --title x"}, "tool_use_id": "t"}})
            await self.say("Opened it." if (await self.perm)["behavior"] == "allow" else "Okay.")
        else:
            await self.say(REPLIES.get(SC, "It is noon. Have a nice day."))
        self.result()

    async def say(self, words):
        for i in range(0, len(words), 4):        # in 4-character pieces: a block or a style split anywhere
            self.emit({"type": "stream_event", "event": {"type": "content_block_delta",
                                                        "delta": {"type": "text_delta", "text": words[i:i + 4]}}})
            await asyncio.sleep(0.01)
        self.emit({"type": "stream_event", "event": {"type": "content_block_stop"}})


class FakeTransport(Transport):
    """The SDK's own client and protocol, over a FakeProc instead of a `claude` process."""
    def __init__(self): self.proc = FakeProc()
    async def connect(self): log("START", "no permission checks" if agent.status["skip"] else "checks on")
    async def write(self, data):
        for line in data.splitlines():
            self.proc.got(json.loads(line))
    async def read_messages(self):
        while line := await self.proc.stdout.readline():
            yield json.loads(line)
    async def close(self): self.proc.stdout.feed_eof()
    def is_ready(self): return True
    async def end_input(self): pass
agent.brain.transport = FakeTransport


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


# ---- the ears: Flux events on a script; ("sock", t) is a session reporting in over claudio's socket, ("key", (t, text)) is typed
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
    "allow-yes": (6, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")),
                      (2.5, turn("StartOfTurn")), (2.6, turn("EagerEndOfTurn", "yes")), (2.7, turn("EndOfTurn", "yes"))]),
    "allow-always": (6, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")),
                         (2.5, turn("StartOfTurn")), (2.7, turn("EndOfTurn", "always"))]),
    "allow-other": (9, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")),
                        (3.5, turn("StartOfTurn")), (3.7, turn("EndOfTurn", "what would that do")),
                        (5.5, turn("StartOfTurn")), (5.7, turn("EndOfTurn", "ok do it"))]),
    "allow-unclear": (9, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")),
                          (3.5, turn("StartOfTurn")), (3.7, turn("EndOfTurn", "I said I said")),
                          (5.5, turn("StartOfTurn")), (5.7, turn("EndOfTurn", "So, yes. You are allowed."))]),
    "allow-cut": (6, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")),
                      (2.5, turn("StartOfTurn")), (2.7, turn("EndOfTurn", "slash stop"))]),
    "allow-eager": (9, [(2.0, turn("StartOfTurn")), (2.2, turn("EagerEndOfTurn", "open a PR")),
                        (4.5, turn("EndOfTurn", "open a PR")), (6.0, turn("StartOfTurn")), (6.2, turn("EndOfTurn", "yes"))]),
    "allow-key": (6, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")), ("key", (2.7, "2"))]),
    "allow-early": (8, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")),     # okay to the reply,
                        (1.3, turn("StartOfTurn")), (1.5, turn("EndOfTurn", "okay"))]),     # before the question
    "handoff-new": (6, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "fix the login")), ("sock", 3.0)]),
    "loose-table": (5, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "give me a table of what changed"))]),
    "allow-no": (6, [(0.1, turn("StartOfTurn")), (0.3, turn("EndOfTurn", "open a PR")),
                     (2.5, turn("StartOfTurn")), (2.7, turn("EndOfTurn", "no"))]),
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
            if at == "key":                    # ("key", t, text): typed at t
                t, text = what
                await asyncio.sleep(max(0, base + t - time.monotonic()))
                log("KEY", repr(text))
                os.write(KEYS[1], text.encode())
                continue
            if at == "sock":
                await asyncio.sleep(max(0, base + what - time.monotonic()))
                r, w = await asyncio.open_unix_connection(config.SOCK)
                surface = NEW if SC == "handoff-new" else "abcd1234"
                w.write((json.dumps({"event": "Stop", "session": "other", "surface": surface, "text": "done"}) + "\n").encode())
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
