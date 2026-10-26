"""claudio: the command. No arguments runs the voice; `setup` is the first-launch wizard."""
import json, os, shutil, subprocess, sys, urllib.request
from rich.prompt import Confirm, IntPrompt, Prompt
from . import config, ui
from .ui import console
SETTINGS = os.path.expanduser("~/.claude/settings.json")
HOOKS = [("Stop", None), ("Notification", None), ("PreToolUse", "AskUserQuestion")]
VOICES = [("aura-2-orion-en", "male, calm, approachable"), ("aura-2-arcas-en", "male, smooth, clear"),
          ("aura-2-apollo-en", "male, confident, casual"), ("aura-2-thalia-en", "female, clear, confident"),
          ("aura-2-asteria-en", "female, knowledgeable, energetic"), ("aura-2-athena-en", "female, calm, professional")]
USAGE = """claudio             talk (runs setup the first time)
claudio setup       the wizard again
claudio doctor      check everything and run one typed turn
claudio install     add the Claude Code hooks to ~/.claude/settings.json
claudio uninstall   remove them
claudio forget      drop the brain's memory of past conversations
claudio set <key> <value>   change one setting:
                            KEYS
claudio hook <event>        what the hooks call""".replace("KEYS", ", ".join(k for k in config.DEFAULTS if k not in config.SECRETS))


workspaces = config.workspaces


def key_ok(key):
    req = urllib.request.Request("https://api.deepgram.com/v1/projects", headers={"Authorization": f"Token {key}"})
    try:
        return urllib.request.urlopen(req, timeout=8).status == 200
    except Exception:
        return False


def setup():
    cfg = config.stored()                    # the global files' own values: what setup writes back
    ui.banner(subtitle="setup · a few questions, then it listens")
    for name, ok in [("claude", shutil.which("claude")), ("cmux", workspaces() or os.path.exists("/Applications/cmux.app"))]:
        ui.check(ok, name, "needed; install it and run setup again")
    for _ in range(3):
        hint = " [dim](a key is stored; Enter keeps it)[/]" if cfg["deepgram_api_key"] else " [dim](console.deepgram.com)[/]"
        key = Prompt.ask("  Deepgram API key" + hint, password=True, default=cfg["deepgram_api_key"] or None,
                         show_default=False) or cfg["deepgram_api_key"]
        if key and key_ok(key):
            cfg["deepgram_api_key"] = key
            break
        console.print("  [red]that key was refused by Deepgram[/]")
    else:
        raise SystemExit("no working Deepgram key; setup stopped")
    ws = workspaces()
    if ws:
        console.print("  Which workspace is the orchestrator, the session that gets your tasks by default?")
        for i, w in enumerate(ws, 1):
            console.print(f"    [cyan]{i}[/] {w}")
        default = ws.index(cfg["orchestrator"]) + 1 if cfg["orchestrator"] in ws else 1
        cfg["orchestrator"] = ws[IntPrompt.ask("  number", default=default, choices=[str(i) for i in range(1, len(ws) + 1)]) - 1]
    else:
        cfg["orchestrator"] = Prompt.ask("  Orchestrator workspace title", default=cfg["orchestrator"] or "Orchestrator")
    console.print("  Voice:")
    for i, (v, d) in enumerate(VOICES, 1):
        console.print(f"    [cyan]{i}[/] {v}  [dim]{d}[/]")
    names = [v for v, _ in VOICES]
    default = names.index(cfg["voice"]) + 1 if cfg["voice"] in names else 1
    cfg["voice"] = names[IntPrompt.ask("  number", default=default, choices=[str(i) for i in range(1, len(VOICES) + 1)]) - 1]
    cfg["model"] = Prompt.ask("  Brain model", choices=list(config.MODELS), default=cfg["model"])
    cfg["effort"] = Prompt.ask("  Brain effort", choices=list(config.EFFORTS), default=cfg["effort"])
    cfg["barge_in"] = Confirm.ask("  Interrupt it by talking over it? [dim](echo cancellation is built in with the Xcode tools; otherwise use headphones)[/]",
                                  default=cfg["barge_in"])
    config.save(cfg)
    console.print(f"  [green]saved[/] {config.CONF}   key: {config.SECRETS_FILE}   persona: {config.PROMPT}")
    if Confirm.ask("  Add the Claude Code hooks now? [dim](Stop, Notification, AskUserQuestion; sessions started after this report back)[/]", default=True):
        install()
    console.print("\n  Run [bold]claudio[/] from a project directory to talk.")


def _settings():
    """The user's Claude Code settings. A file that exists but cannot be read or parsed stops us:
    writing over it would throw away every permission, env and hook they have."""
    if not os.path.exists(SETTINGS):
        return {}
    try:
        data = json.load(open(SETTINGS))
    except (OSError, ValueError) as e:
        raise SystemExit(f"  {SETTINGS} could not be read as JSON ({e}); fix it first, nothing was changed")
    if not isinstance(data, dict):
        raise SystemExit(f"  {SETTINGS} is not a JSON object; nothing was changed")
    hooks = data.get("hooks", {})
    shape_ok = isinstance(hooks, dict) and all(
        isinstance(entries, list) and all(isinstance(e, dict) and isinstance(e.get("hooks", []), list)
                                          and all(isinstance(h, dict) for h in e.get("hooks", [])) for e in entries)
        for entries in hooks.values())
    if not shape_ok:
        raise SystemExit(f"  the hooks section of {SETTINGS} is not shaped as Claude Code writes it; nothing was changed")
    return data


def _write_settings(s):
    """Atomic, into the real file behind any symlink (dotfiles setups), with a backup of what was there."""
    target = os.path.realpath(SETTINGS)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(target):
        shutil.copy(target, target + ".bak-claudio")
    tmp = target + ".claudio-tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, target)


def install():
    me = os.path.abspath(sys.argv[0])
    s = _settings()
    hooks = s.setdefault("hooks", {})
    for event, matcher in HOOKS:
        entries = hooks.setdefault(event, [])
        for e in entries:
            e["hooks"] = [h for h in e.get("hooks", []) if "claudio hook" not in h.get("command", "") and "voice/hook.sh" not in h.get("command", "")]
        hooks[event] = [e for e in entries if e.get("hooks") or e.get("matcher")]
        cmd = {"type": "command", "command": f"{me} hook {matcher or event}"}
        slot = next((e for e in hooks[event] if (e.get("matcher") or None) == matcher), None)
        if slot is None:
            slot = {"matcher": matcher, "hooks": []} if matcher else {"hooks": []}
            hooks[event].append(slot)
        slot.setdefault("hooks", []).append(cmd)
    _write_settings(s)
    console.print(f"  [green]hooks installed[/] in {SETTINGS}  [dim](backup: settings.json.bak-claudio)[/]")


def uninstall():
    s = _settings()
    for event, entries in s.get("hooks", {}).items():
        for e in entries:
            e["hooks"] = [h for h in e.get("hooks", []) if "claudio hook" not in h.get("command", "")]
        s["hooks"][event] = [e for e in entries if e.get("hooks")]
    _write_settings(s)
    console.print(f"  [green]hooks removed[/] from {SETTINGS}")


def doctor():
    """Every way it can be broken, checked in order, then one typed turn through the whole pipeline."""
    cfg = config.load()
    ok_all = True

    def row(ok, name, hint=""):
        nonlocal ok_all
        ok_all &= bool(ok)
        ui.check(ok, name, hint)

    ui.banner(subtitle="doctor · every way it can be broken, in order")
    claude = shutil.which("claude")
    row(claude, "claude on PATH", "install Claude Code")
    if claude:
        v = subprocess.run([claude, "--version"], capture_output=True, text=True).stdout.strip()
        row(v, f"claude version {v}")
    ws = workspaces()
    row(ws, "cmux reachable", "is cmux running?")
    row(cfg["orchestrator"] in ws, f"orchestrator '{cfg['orchestrator']}' is a live workspace", "claudio set orchestrator <title>")
    row(cfg["deepgram_api_key"], "Deepgram key set", "claudio setup")
    row(cfg["deepgram_api_key"] and key_ok(cfg["deepgram_api_key"]), "Deepgram key accepted", "console.deepgram.com")
    hooks = json.dumps(_settings().get("hooks", {}))
    row(hooks.count("claudio hook") >= 3, "the three Claude Code hooks installed", "claudio install")
    from . import agent
    if cfg["mouth"] == "local":
        try:
            row(cfg["local_voice"] in agent.kokoro(cfg["local_model"]).get_voices(), f"local voice {cfg['local_voice']} loads",
                "claudio set local_voice am_michael")
        except OSError as e:
            row(False, "local voice (Kokoro)", str(e))
    row(os.path.exists(config.HELPER) or shutil.which("swiftc"), "echo canceller built or buildable", "Xcode command line tools; headphones otherwise")
    try:
        import sounddevice as sd
        row(sd.query_devices(kind="input")["name"], f"microphone: {sd.query_devices(kind='input')['name']}")
    except Exception as e:
        row(False, "microphone", str(e)[:80])
    row(os.path.exists(config.PROMPT), "persona additions file present", "it is made on first run")
    console.print("  [dim]one typed turn through brain and mouth…[/]")
    os.environ["CLAUDIO_TEXT"] = "Say only: the doctor is in."
    agent.run()
    console.print("\n  " + ("[green]all good[/]" if ok_all else "[yellow]fix the ✗ lines above[/]"))


def forget():
    if os.path.exists(config.SESSION):
        os.unlink(config.SESSION)
    console.print("  forgotten; the next start is a fresh conversation")


def main():
    args = sys.argv[1:]
    if not args:
        if not config.configured():
            setup()
        from . import agent
        agent.run()
    elif args[0] == "setup":
        setup()
    elif args[0] == "install":
        install()
    elif args[0] == "uninstall":
        uninstall()
    elif args[0] == "doctor":
        doctor()
    elif args[0] == "forget":
        forget()
    elif args[0] == "set" and len(args) == 3:
        print(f"{args[1]} = {config.set_key(args[1], args[2])}")
    elif args[0] == "hook" and len(args) == 2:
        from . import hook
        hook.run(args[1])
    else:
        print(USAGE)
        sys.exit(1 if args and args[0] not in ("-h", "--help", "help") else 0)
