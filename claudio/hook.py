"""`claudio hook <event>`: a Claude Code hook. Posts what the session just did to the running claudio.
Exits at once when claudio is not running, so every session carries these hooks for free."""
import json, os, socket, sys
from .config import SOCK


def run(kind):
    if not os.path.exists(SOCK):
        return
    ev = json.load(sys.stdin)
    text = ""
    if kind == "Stop":   # ponytail: last assistant text by scanning the whole transcript; fine at a few MB
        try:
            for line in open(ev["transcript_path"]):
                d = json.loads(line)
                if d.get("type") == "assistant":
                    t = " ".join(c.get("text", "") for c in d["message"]["content"] if c.get("type") == "text")
                    if t.strip():
                        text = t
        except (OSError, KeyError, ValueError):
            pass
    msg = {"event": kind, "session": ev.get("session_id"), "surface": os.environ.get("CMUX_SURFACE_ID") or os.environ.get("BB_THREAD_ID"),
           "kind": ev.get("notification_type"), "message": ev.get("message"), "text": text[-1500:],
           "questions": ev.get("tool_input", {}).get("questions") if kind == "AskUserQuestion" else None}
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(1)
        s.connect(SOCK)
        s.sendall((json.dumps(msg) + "\n").encode())
        s.close()
    except OSError:
        pass
