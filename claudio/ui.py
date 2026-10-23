"""The look: one wordmark, one status strip, one glyph per voice in the transcript."""
from rich.console import Console
from rich.text import Text

console = Console(highlight=False)

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


def me_prefix():
    console.print(f"{ME} ", end="")


def event(workspace, kind):
    console.print(f"\n{EVENT} [magenta]{workspace}[/] [dim]{kind}[/]")


def note(text):
    console.print(f"{NOTE} [dim]{text}[/]")


def warn(text):
    console.print(f"[bold yellow]![/] [yellow]{text}[/]")


def check(ok, name, hint=""):
    console.print(f"  {'[green]✓[/]' if ok else '[red]✗[/]'} {name}" + (f"  [dim]{hint}[/]" if hint and not ok else ""))
