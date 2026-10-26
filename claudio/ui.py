"""The look: one wordmark, one status strip, one glyph per voice in the transcript."""
import datetime, os, time
from rich.console import Console, Group, RenderHook
from rich.constrain import Constrain
from rich.control import Control
from rich.table import Table
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
TAGLINE = "[not dim not italic]Talk, and your sessions [bold #fff383]work[/].[/]"   # the site's headline, "work" in its yellow

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
            t.append_text(Text.from_markup(f"   {subtitle}", style="dim italic"))
        if i < len(rows) - 1:
            t.append("\n")
    return t


def short_voice(v):
    return v.removeprefix("aura-2-").removesuffix("-en")


def banner(subtitle=None, facts=None, hints=None):
    """The header: wordmark, tagline (or a subtitle like 'setup'), one fact per line, a line of hints."""
    console.clear()
    console.print()
    console.print(wordmark(subtitle or TAGLINE))
    if facts:
        console.print()
        for k, v in facts.items():   # one fact per line
            console.print(Text.assemble("  ", (f"{k} ", "dim"), (str(v), "bold cyan")))
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


CHARS_PER_SEC = 15              # ponytail: a guess at speaking pace, not the audio's own timing; tune if words run ahead
FADE = 0.35                     # seconds for one word to go from dim to full
SHADES = ["grey30", "grey50", "grey70", ""]
fading = []                     # claudio's blocks still fading in, drawn above the status line until they settle
settling = {"now": False}       # settle() is printing: the hook must not flush the blocks still fading


class Fade:
    """One block of claudio's: its sentences run on as one paragraph, words appear at speaking pace, each dim to full."""
    def __init__(self, first):
        self.head = Text("◆ ", style="bold #2dd4bf") if first else Text("  ")
        self.words = []          # (word, when it starts to show)

    def add(self, sentence):
        at = time.monotonic()    # its audio starts now, so the last sentence's audio is over: show what's left of it
        self.words = [(w, min(t, at)) for w, t in self.words]
        words = sentence.split()
        for i, w in enumerate(words):
            self.words.append((w, at + i * max(0.3, len(sentence) / CHARS_PER_SEC) / len(words)))

    def done(self):
        return not self.words or time.monotonic() - self.words[-1][1] > FADE

    def body(self, final=False):
        line, now = Text(), time.monotonic()
        for w, at in self.words:
            if not final and now < at:
                break
            shade = "" if final else SHADES[min(len(SHADES) - 1, int((now - at) / FADE * len(SHADES)))]
            line.append((" " if line else "") + w, style=shade)
        return line

    def render(self, final=False):
        grid = Table.grid()      # the glyph in its own column: wrapped lines hang under the text, not under it
        grid.add_column(width=2, no_wrap=True)
        grid.add_column()
        grid.add_row(self.head, self.body(final))
        return Constrain(grid, width())

    def __rich__(self):
        return self.render()


class _Settle(RenderHook):
    """Anything printed first settles the fading blocks into the transcript above it, whole.
    Live's own redraw (a print of control codes only) is not a print, or nothing would ever fade."""
    def process_renderables(self, renderables):
        if not fading or settling["now"] or all(isinstance(r, Control) for r in renderables):
            return renderables
        done = []
        while fading:                       # pop, not clear: a sentence added meanwhile from another thread isn't lost
            done.append(fading.pop(0).render(final=True))
        return done + renderables


def settle():
    """Blocks that have finished fading go into the transcript, so a long reply can't outgrow the live area."""
    done = []
    while len(fading) > 1 and fading[0].done():     # the newest stays: the next sentence may still join it
        done.append(fading.pop(0).render(final=True))
    if done:
        settling["now"] = True
        try:
            console.print(*done)
        finally:
            settling["now"] = False


def attach(status):
    """Draw fading blocks above the status spinner. Call before status.start(), so this hook runs before Live's."""
    console.push_render_hook(_Settle())
    status._live.update(_Above(status))     # ponytail: rich's private Live inside Status; own Live if rich moves it


class _Above:
    def __init__(self, status):
        self.status = status

    def __rich__(self):
        return Group(*list(fading), self.status.renderable)


def me_line(sentence, first, live=False):
    """One sentence of claudio's. A new block opens with the glyph; the rest of a block joins its paragraph.
    Live, it fades in word by word; otherwise it prints whole on its own line."""
    if live:
        if first or not fading:
            fading.append(Fade(first))
        fading[-1].add(sentence)
        settle()
    else:
        f = Fade(first)
        f.add(sentence)
        console.print(f.render(final=True))
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
