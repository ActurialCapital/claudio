"""The look: one wordmark, one status strip, one glyph per voice in the transcript."""
import datetime, os
from rich.console import Console
from rich.text import Text
from . import config

console = Console(highlight=False)
TRANSCRIPTS = os.path.join(config.DIR, "transcripts")
COLUMN = 90                     # transcript lines wrap here, however wide the pane; the header uses the full width
last_turn = {"at": None}


def width():
    return min(COLUMN, console.width)


def log(line):
    """Append a line to today's transcript, ~/.config/claudio/transcripts/YYYY-MM-DD.md."""
    try:
        os.makedirs(TRANSCRIPTS, exist_ok=True)
        with open(os.path.join(TRANSCRIPTS, datetime.date.today().isoformat() + ".md"), "a") as f:
            f.write(f"{datetime.datetime.now():%H:%M}  {line}\n")
    except OSError:
        pass

MARK = r"""
 ██████╗██╗      █████╗ ██╗   ██╗██████╗ ██╗ ██████╗
██╔════╝██║     ██╔══██╗██║   ██║██╔══██╗██║██╔═══██╗
██║     ██║     ███████║██║   ██║██║  ██║██║██║   ██║
██║     ██║     ██╔══██║██║   ██║██║  ██║██║██║   ██║
╚██████╗███████╗██║  ██║╚██████╔╝██████╔╝██║╚██████╔╝
 ╚═════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝ ╚═════╝
""".strip("\n").splitlines()
SHADES = ["#ccfbf1", "#99f6e4", "#5eead4", "#2dd4bf", "#14b8a6", "#0d9488"]   # teal, light to deep, one per line
TAGLINE = "a voice in front of your Claude Code sessions"

YOU, ME, EVENT, NOTE = "[bold cyan]›[/]", "[bold #2dd4bf]◆[/]", "[bold magenta]▸[/]", "[dim]·[/]"


def wordmark():
    t = Text()
    for line, shade in zip(MARK, SHADES):
        t.append(line + "\n", style=f"bold {shade}")
    return t


def short_voice(v):
    return v.removeprefix("aura-2-").removesuffix("-en")


def banner(subtitle=None, facts=None, hints=None):
    """The header: wordmark, tagline (or a subtitle like 'setup'), a strip of facts, a line of hints."""
    console.clear()
    console.print()
    console.print(wordmark())
    console.print(f"  [dim italic]{subtitle or TAGLINE}[/]")
    if facts:
        console.print()
        row, width = Text("  "), 2
        for k, v in facts.items():
            fact = Text()
            fact.append(f"{k} ", style="dim")
            fact.append(str(v), style="bold cyan")
            sep = 5 if width > 2 else 0
            if width + sep + len(fact) > console.width - 2 and width > 2:   # next row, never inside a fact
                console.print(row)
                row, width, sep = Text("  "), 2, 0
            if sep:
                row.append("  ·  ", style="dim")
            row.append_text(fact)
            width += sep + len(fact)
        console.print(row)
    if hints:
        console.print(f"  [dim]{hints}[/]")
    console.print()


def you(text, tentative=False):
    now = datetime.datetime.now()
    if not tentative and last_turn["at"] and (now - last_turn["at"]).total_seconds() > 300:
        console.print()
        console.rule(f"[dim]{now:%H:%M}[/]", style="dim", align="left")     # a gap of more than five minutes
    if not tentative:
        last_turn["at"] = now
    line = Text("\n")
    line.append("› ", style="bold cyan")
    line.append(text, style="dim" if tentative else "")
    console.print(line, width=width())
    if not tentative:
        log(f"› {text}")


def me_line(sentence, first):
    """One sentence of claudio's, as a whole line: the glyph on the first of an utterance, indented after."""
    line = Text.assemble(("◆ ", "bold #2dd4bf")) if first else Text("  ")
    line.append(sentence)
    console.print(line, width=width())
    log(("◆ " if first else "  ") + sentence)


KIND = {"Stop": "done", "Notification": "needs permission", "AskUserQuestion": "asks you to choose"}


def event(workspace, kind, asked=""):
    """One header per session report: ▸ Sequencer  done  ·  for "rebase 44…"; the narration follows under it."""
    line = Text("\n")
    line.append("▸ ", style="bold magenta")
    line.append(workspace, style="magenta")
    line.append(f"  {KIND.get(kind, kind.lower())}", style="dim")
    if asked:
        line.append(f'  ·  for "{asked[:70]}"', style="dim")
    console.print(line, width=width())
    log(f"▸ {workspace}  {KIND.get(kind, kind)}" + (f'  ·  for "{asked}"' if asked else ""))


def rule(title):
    console.rule(f"[dim]{title}[/]", style="dim")


def tool(name, inp):
    """A dim line for what the brain is doing: reading a file, running a command."""
    if name == "Read":
        what = "reading " + os.path.basename(inp.get("file_path", ""))
    elif name in ("Grep", "Glob"):
        what = "searching " + inp.get("pattern", "")
    elif name == "Bash":
        what = " ".join(inp.get("command", "").split()[:3])
    else:
        what = name.lower()
    console.print(Text(f"  → {what[:70]}", style="dim"), width=width())


def setting(text):
    console.print(f"[dim]⚙ {text}[/]", width=width())
    log(f"⚙ {text}")


def note(text):
    console.print(f"{NOTE} [dim]{text}[/]", width=width())


def warn(text):
    console.print(f"[bold yellow]![/] [yellow]{text}[/]", width=width())


def check(ok, name, hint=""):
    console.print(f"  {'[green]✓[/]' if ok else '[red]✗[/]'} {name}" + (f"  [dim]{hint}[/]" if hint and not ok else ""))
