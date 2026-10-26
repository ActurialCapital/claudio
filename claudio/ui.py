"""The look: one wordmark, one status strip, one glyph per voice in the transcript."""
import datetime, os, re, time
from rich.console import Console, Group, RenderHook
from rich.constrain import Constrain
from rich.control import Control
from rich.markdown import Markdown
from rich.padding import Padding
from rich.segment import SegmentLines
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
            f.write(f"{datetime.datetime.now():%H:%M:%S}  {line}\n")
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


CHARS_PER_SEC = 15              # the pace while a sentence's audio is still arriving; after that its real length is used
FADE = 0.35                     # seconds for one word to go from dim to full
SHADES = ["grey30", "grey50", "grey70", ""]
LIVE_LINES = 4                  # a long block keeps only its last lines live; the spoken lines above go to the transcript
fading = []                     # claudio's blocks still fading in, drawn above the status line until they settle
BULLET = re.compile(r"^\s*[-*•]\s+")   # a list item from the brain: "- Silero starts turns"
INLINE = re.compile(r"\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*|`([^`]+)`|(?<![*\w])\*(?=[A-Za-z0-9])([^*\n]*?[A-Za-z0-9.!?])\*(?![*\w])"
                    r"|\[([^\]\n]+)\]\((https?://[^)\s]+)\)")   # **bold**, `code`, *italic*, [a link](url); not **/*.py
INLINE_STYLE = ("bold", "cyan", "italic")
settling = {"now": False}       # settle() is printing: the hook must not flush the blocks still fading


def spoken(text):
    """What the voice says: the sentence without its bullet or markup."""
    said = INLINE.sub(lambda m: next(g for g in m.groups() if g is not None), BULLET.sub("", text))
    return re.sub(r"(?<![\w/])/(?=[a-z])", "slash ", said)   # "/clear" is said "slash clear", as the user says it


def sayable(text):
    """Anything for the voice at all: a blank line or a stray "`" is not."""
    return bool(re.search(r"\w", spoken(text)))


def styled(text):
    """The sentence as shown: markup turned into style."""
    t, at = Text(), 0
    for m in INLINE.finditer(text):
        t.append(text[at:m.start()])
        n = next(i for i, g in enumerate(m.groups()) if g is not None)
        t.append(m.group(n + 1), style=f"underline link {m.group(5)}" if n == 3 else INLINE_STYLE[n])   # a link: clickable
        at = m.end()
    t.append(text[at:])
    return t


def words_in(lines):
    return len(re.findall(r"\S+", " ".join("".join(seg.text for seg in line) for line in lines)))


def hang(head, body):
    """head, then body wrapping under itself rather than under head."""
    grid = Table.grid()
    grid.add_column(width=len(head.plain), no_wrap=True)
    grid.add_column()
    grid.add_row(head, body)
    return grid


class Fade:
    """One block of claudio's: its sentences run on as one paragraph, words appear in time with the voice, each dim to full."""
    def __init__(self, first):
        self.head = Text("◆ ", style="bold #2dd4bf") if first else Text("  ")
        self.words = []          # (word as Text, share of its sentence's audio before it, sentence); "\n" breaks the line
        self.listing, self.bol = False, True     # in a list; the last sentence ended its line
        self.printed = 0         # lines of render(base=self.base) already in the transcript (settle), at self.width
        self.base = self.inked = self.width = 0    # words left out of the render; words in the transcript

    def add(self, sentence, secs=None):
        """secs(): the sentence's audio length once all of it has arrived, else None (the pace estimate stands in)."""
        now = time.monotonic()
        for w, frac, part in self.words:    # its audio starts now, so the last sentence's audio is over: show what's left
            part["end"] = min(part["end"] or now, now)
        part = {"t0": now, "secs": secs or (lambda: None), "est": max(0.3, len(sentence) / CHARS_PER_SEC), "end": None}
        bullet = BULLET.match(sentence)
        if bullet or (self.listing and self.bol):   # a list item, or the first line after a list: a line of its own
            self.words.append(("\n", 0, part))
        if bullet:
            self.words.append((Text("•"), 0, part))
            self.listing = True
        elif self.bol:
            self.listing = False                    # a new line that is no item: the list is over
        self.bol = sentence.endswith("\n")         # a second sentence on an item's line stays in that item
        t = styled(sentence[bullet.end():] if bullet else sentence)
        words = [t[m.start():m.end()] for m in re.finditer(r"\S+", t.plain)]
        total, before = sum(len(w) + 1 for w in words) or 1, 0
        for w in words:                      # a long word takes longer to say: spread by characters, not word count
            self.words.append((w, before / total, part))
            before += len(w) + 1

    @staticmethod
    def at(frac, part):
        t = part["t0"] + frac * (part["secs"]() or part["est"])
        return min(t, part["end"]) if part["end"] else t

    def done(self):
        return not self.words or time.monotonic() - self.at(*self.words[-1][1:]) > FADE

    def body(self, final=False, base=0):
        line, now, n = Text(), time.monotonic(), 0
        for w, frac, part in self.words:
            if n < base:                         # already in the transcript
                n += w != "\n"
                continue
            at = self.at(frac, part)
            if not final and now < at:
                break
            if w == "\n":
                if line:
                    line.append("\n")
                continue
            if line and not line.plain.endswith("\n"):
                line.append(" ")
            w = w.copy()
            if not final:
                w.stylize(SHADES[min(len(SHADES) - 1, int((now - at) / FADE * len(SHADES)))])
            line.append_text(w)
        return line

    def render(self, final=False, base=0):
        grid = Table.grid()      # the glyph in its own column: wrapped lines hang under the text, not under it
        grid.add_column(width=2, no_wrap=True)
        grid.add_column()
        for i, line in enumerate(self.body(final, base).split("\n")):
            if line.plain.startswith("• "):    # a list item hangs under its own text too
                line = hang(line[:2], line[2:])
            grid.add_row(self.head if i == 0 and not base else "", line)
        return Constrain(grid, width())

    def lines(self, final=False, base=None):
        return console.render_lines(self.render(final, self.base if base is None else base), console.options, pad=False)

    def rest(self, final=False):
        """What isn't in the transcript yet. After a resize the old line count means nothing at the new width:
        go on from the first word not printed, on a fresh line."""
        if self.printed and console.width != self.width:
            return SegmentLines(self.lines(final, base=self.inked), new_lines=True)
        return SegmentLines(self.lines(final)[self.printed:], new_lines=True)

    def __rich__(self):
        return self.rest()


class _Settle(RenderHook):
    """Anything printed first settles the fading blocks into the transcript above it, whole.
    Live's own redraw (a print of control codes only) is not a print, or nothing would ever fade."""
    def process_renderables(self, renderables):
        if not fading or settling["now"] or all(isinstance(r, Control) for r in renderables):
            return renderables
        done = []
        while fading:                       # pop, not clear: a sentence added meanwhile from another thread isn't lost
            done.append(fading.pop(0).rest(final=True))
        return done + renderables


def settle():
    """Finished blocks go into the transcript, and so do the spoken lines of a long one, so the live area stays short.
    Wrapping is greedy, so a line above the last never changes once the next has begun."""
    done = []
    while len(fading) > 1 and fading[0].done():     # the newest stays: the next sentence may still join it
        done.append(fading.pop(0).rest(final=True))
    if fading:
        f = fading[-1]
        if f.printed and console.width != f.width:   # resized: start over from the first word not printed
            f.base, f.printed = f.inked, 0
        n = len(f.lines()) - LIVE_LINES
        if n > f.printed:
            lines = f.lines(final=True)
            done.append(SegmentLines(lines[f.printed:n], new_lines=True))
            f.printed, f.width = n, console.width
            f.inked = f.base + words_in(lines[:n]) - (1 if not f.base and f.head.plain.strip() else 0)   # not the ◆
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


def me_line(sentence, first, live=False, secs=None):
    """One sentence of claudio's, as the brain wrote it (a trailing newline ends its line). A new block opens with the
    glyph; the rest of a block joins its paragraph. Live, it fades in word by word over its audio (secs, see Fade.add);
    otherwise it prints whole on its own line."""
    if live:
        if first or not fading:
            fading.append(Fade(first))
        fading[-1].add(sentence, secs)
        settle()
    else:
        f = Fade(first)
        f.add(sentence)
        console.print(f.render(final=True))
    log(("◆ " if first else "  ") + sentence.strip())


def table(md):
    """A loose table ("Change | Type" rows, no outer bars, no --- row) as Markdown renders one."""
    rows = [r if r.startswith("|") else f"| {r} |" for r in md.splitlines() if r.strip()]
    if len(rows) > 1 and not re.fullmatch(r"\|?[\s:|-]+\|?", rows[1]):
        rows.insert(1, "|" + "---|" * rows[0].strip("|").count("|") + "---|")
    return "\n".join(rows)


def block(md, colors=True):
    """A table or code block from the brain: shown whole, in place, never spoken. colors off: code as plain text."""
    shown = Markdown(table(md.strip()) if not md.startswith("```") else md.strip())
    if not colors and md.startswith("```"):
        shown = Text(md.split("\n", 1)[-1].rstrip().removesuffix("```").rstrip("\n"))
    lines = console.render_lines(Constrain(Padding(shown, (0, 0, 0, 2)), width()), console.options, pad=False)
    blank = lambda line: not "".join(seg.text for seg in line).strip()
    while lines and blank(lines[0]):                 # a table's box leaves empty rows around it
        lines.pop(0)
    while lines and blank(lines[-1]):
        lines.pop()
    console.print(SegmentLines(lines, new_lines=True))
    log("\n".join("    " + line for line in md.rstrip().splitlines()).lstrip())   # one entry, indented like the rest


KIND = {"Stop": "done", "Notification": "needs permission", "AskUserQuestion": "asks you to choose", "Reply": "replied"}


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
        what = " ".join(inp.get("command", "").split())   # cut at the line's width below, not after three words
    else:
        what = name.lower()
    console.print(Text(f"  → {what[:70]}", style="dim"), width=width())
    log(f"  → {inp.get('command') or what}"[:300])     # the whole command: the transcript is for looking back


def setting(text):
    console.print(Text(f"⚙ {text}", style="dim"), width=width())
    log(f"⚙ {text}")


def note(text):
    console.print(Text(f"· {text}", style="dim"), width=width())
    log(f"· {text}")


def warn(text):
    line = Text.assemble(("! ", "bold yellow"), (text, "yellow"))
    console.print(line, width=width())
    log(f"! {text}")


def check(ok, name, hint=""):
    line = Text.assemble(("  ✓ ", "green") if ok else ("  ✗ ", "red"), name)
    if hint and not ok:
        line.append(f"  {hint}", style="dim")
    console.print(line)
