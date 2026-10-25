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

SUN = "#DF3F00"                  # the website's dithered sun
TAGLINE = "a voice in front of your Claude Code sessions"

YOU, ME, EVENT, NOTE = "[bold cyan]›[/]", "[bold #2dd4bf]◆[/]", "[bold magenta]▸[/]", "[dim]·[/]"


def sun(n=12):
    """The mark: a sphere lit from the top left, 4x4 Bayer-dithered, two pixels per half-block character
    so they come out square. Same maths as the site's components/sun-mark.tsx."""
    bayer = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]

    def on(x, y):
        nx, ny = (x + .5) / (n / 2) - 1, (y + .5) / (n / 2) - 1
        r2 = nx * nx + ny * ny
        if r2 > 1:
            return False
        lit = max(0, (-.5 * nx - .6 * ny + .62 * (1 - r2) ** .5) / .98)
        return .18 + .82 * lit > (bayer[(y % 4) * 4 + x % 4] + .5) / 16
    cell = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}
    return ["".join(cell[on(x, y), on(x, y + 1)] for x in range(n)) for y in range(0, n, 2)]


def wordmark(subtitle=TAGLINE):
    """The sun with 'claudio' and the subtitle beside its middle."""
    t, rows = Text(), sun()
    mid = len(rows) // 2
    for i, row in enumerate(rows):
        t.append("  " + row, style=SUN)
        if i == mid - 1:
            t.append("   claudio", style="bold")
        elif i == mid:
            t.append(f"   {subtitle}", style="dim italic")
        if i < len(rows) - 1:
            t.append("\n")
    return t


def short_voice(v):
    return v.removeprefix("aura-2-").removesuffix("-en")


def banner(subtitle=None, facts=None, hints=None):
    """The header: wordmark, tagline (or a subtitle like 'setup'), a strip of facts, a line of hints."""
    console.clear()
    console.print()
    console.print(wordmark(subtitle or TAGLINE))
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
    console.print(Text(f"⚙ {text}", style="dim"), width=width())
    log(f"⚙ {text}")


def note(text):
    console.print(Text(f"· {text}", style="dim"), width=width())


def warn(text):
    line = Text.assemble(("! ", "bold yellow"), (text, "yellow"))
    console.print(line, width=width())


def check(ok, name, hint=""):
    line = Text.assemble(("  ✓ ", "green") if ok else ("  ✗ ", "red"), name)
    if hint and not ok:
        line.append(f"  {hint}", style="dim")
    console.print(line)
