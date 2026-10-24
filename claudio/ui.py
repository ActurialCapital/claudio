"""The look: one wordmark, one status strip, one glyph per voice in the transcript."""
import datetime, os
from rich.console import Console
from rich.text import Text
from . import config

console = Console(highlight=False)
TRANSCRIPTS = os.path.join(config.DIR, "transcripts")


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
    console.print(f"\n{YOU} [dim]{text}[/]" if tentative else f"\n{YOU} {text}")
    if not tentative:
        log(f"› {text}")


def me_line(sentence, first):
    """One sentence of claudio's, as a whole line: the glyph on the first of an utterance, indented after."""
    line = Text.assemble(("◆ ", "bold #2dd4bf")) if first else Text("  ")
    line.append(sentence)
    console.print(line)
    log(("◆ " if first else "  ") + sentence)


def event(workspace, kind, asked=""):
    console.print()
    if asked:
        console.print(f"  [dim]↳ for: {asked[:90]}[/]")
    console.print(f"{EVENT} [magenta]{workspace}[/] [dim]{kind}[/]")
    log(f"▸ {workspace}  {kind}" + (f"  (for: {asked})" if asked else ""))


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
    console.print(f"  [dim]{what[:70]}[/]")


def note(text):
    console.print(f"{NOTE} [dim]{text}[/]")


def warn(text):
    console.print(f"[bold yellow]![/] [yellow]{text}[/]")


def check(ok, name, hint=""):
    console.print(f"  {'[green]✓[/]' if ok else '[red]✗[/]'} {name}" + (f"  [dim]{hint}[/]" if hint and not ok else ""))
