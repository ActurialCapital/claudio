"""claudio: the command. No arguments runs the voice; `setup` is the first-launch wizard."""
import json, os, shutil, subprocess, sys, urllib.request
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from . import config

console = Console(highlight=False)
SETTINGS = os.path.expanduser("~/.claude/settings.json")
HOOKS = [("Stop", None), ("Notification", None), ("PreToolUse", "AskUserQuestion")]
VOICES = [("aura-2-orion-en", "male, calm, approachable"), ("aura-2-arcas-en", "male, smooth, clear"),
          ("aura-2-apollo-en", "male, confident, casual"), ("aura-2-thalia-en", "female, clear, confident"),
          ("aura-2-asteria-en", "female, knowledgeable, energetic"), ("aura-2-athena-en", "female, calm, professional")]
USAGE = """claudio             talk (runs setup the first time)
claudio setup       the wizard again
claudio install     add the Claude Code hooks to ~/.claude/settings.json
claudio uninstall   remove them
claudio set <key> <value>   change one setting (orchestrator, model, effort, voice, ears, eager_eot, eot, barge_in)
claudio hook <event>        what the hooks call"""


def workspaces():
    cmux = (os.environ.get("CMUX_BUNDLED_CLI_PATH") or shutil.which("cmux")
            or "/Applications/cmux.app/Contents/Resources/bin/cmux")
    try:
        text = subprocess.run([cmux, "surface", "list"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [l.strip().rsplit("  workspace:", 1)[0] for l in text.splitlines() if "  workspace:" in l]


def key_ok(key):
    req = urllib.request.Request("https://api.deepgram.com/v1/projects", headers={"Authorization": f"Token {key}"})
    try:
        return urllib.request.urlopen(req, timeout=8).status == 200
    except Exception:
        return False


def setup():
    cfg = config.load()
    console.print(Panel.fit("[bold]claudio setup[/]\n[dim]a voice in front of your Claude Code sessions[/]", border_style="green"))
    for name, ok in [("claude", shutil.which("claude")), ("cmux", workspaces() or os.path.exists("/Applications/cmux.app"))]:
        console.print(f"  {'[green]✓[/]' if ok else '[red]✗[/]'} {name}" + ("" if ok else "  [dim]needed; install it and run setup again[/]"))
    for _ in range(3):
        key = Prompt.ask("  Deepgram API key [dim](console.deepgram.com)[/]", password=True,
                         default=cfg["deepgram_api_key"] or None)
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
    cfg["model"] = Prompt.ask("  Brain model", choices=["default", "sonnet", "opus", "haiku"], default=cfg["model"])
    cfg["effort"] = Prompt.ask("  Brain effort", choices=["low", "medium", "high"], default=cfg["effort"])
    cfg["barge_in"] = Confirm.ask("  Interrupt it by talking over it? [dim](yes needs headphones; the mic hears the speaker)[/]",
                                  default=cfg["barge_in"])
    config.save(cfg)
    console.print(f"  [green]saved[/] {config.CONF}   persona: {config.PROMPT}")
    if Confirm.ask("  Add the Claude Code hooks now? [dim](Stop, Notification, AskUserQuestion; sessions started after this report back)[/]", default=True):
        install()
    console.print("\n  Run [bold]claudio[/] from a project directory to talk.")


def _settings():
    try:
        return json.load(open(SETTINGS))
    except (OSError, ValueError):
        return {}


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
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    json.dump(s, open(SETTINGS, "w"), indent=2)
    console.print(f"  [green]hooks installed[/] in {SETTINGS}")


def uninstall():
    s = _settings()
    for event, entries in s.get("hooks", {}).items():
        for e in entries:
            e["hooks"] = [h for h in e.get("hooks", []) if "claudio hook" not in h.get("command", "")]
        s["hooks"][event] = [e for e in entries if e.get("hooks")]
    json.dump(s, open(SETTINGS, "w"), indent=2)
    console.print(f"  [green]hooks removed[/] from {SETTINGS}")


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
    elif args[0] == "set" and len(args) == 3:
        config.set_key(args[1], args[2])
    elif args[0] == "hook" and len(args) == 2:
        from . import hook
        hook.run(args[1])
    else:
        print(USAGE)
        sys.exit(1 if args and args[0] not in ("-h", "--help", "help") else 0)
