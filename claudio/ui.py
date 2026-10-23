"""The look: one wordmark, one status strip, one glyph per voice in the transcript."""
from rich.console import Console
from rich.text import Text

console = Console(highlight=False)

MARK = r"""
       _                 _ _
   ___| | __ _ _   _  __| (_) ___
  / __| |/ _` | | | |/ _` | |/ _ \
 | (__| | (_| | |_| | (_| | | (_) |
  \___|_|\__,_|\__,_|\__,_|_|\___/
""".strip("\n").splitlines()
SHADES = ["#99f6e4", "#5eead4", "#2dd4bf", "#14b8a6", "#0d9488"]   # teal, light to deep, one per line
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
        strip = Text("  ")
        for i, (k, v) in enumerate(facts.items()):
            if i:
                strip.append("  ·  ", style="dim")
            strip.append(f"{k} ".replace(" ", "\u00a0"), style="dim")           # no break inside a fact
            strip.append(str(v).replace(" ", "\u00a0"), style="bold cyan")
        console.print()
        console.print(strip)
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
