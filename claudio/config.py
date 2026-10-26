"""Settings in ~/.config/claudio: config.json (the knobs), secrets.json (the keys, mode 600, never named to the
brain) and prompt.md (the persona, yours to edit). Also the few paths and parsers both the agent and the CLI need."""
import difflib, hashlib, json, os, re, shutil, urllib.request

DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "claudio")
CONF = os.path.join(DIR, "config.json")
PROMPT = os.path.join(DIR, "prompt.md")
PACKAGED_PROMPT = os.path.join(os.path.dirname(__file__), "prompt.md")
SECRETS_FILE = os.path.join(DIR, "secrets.json")
SESSION = os.path.join(DIR, "session")
MCP = os.path.join(DIR, "mcp.json")      # MCP servers for the brain, as in a .mcp.json; none when it is absent
ALLOW = os.path.join(DIR, "allow")       # more tools for the brain: one Claude Code permission rule per line
HELPER = os.path.join(DIR, "bin", "claudio-audio")
VOICE_MODELS = os.path.join(DIR, "models")          # the local mouth's Kokoro files, downloaded on first use
SOCK = f"/tmp/claudio-{os.getuid()}.sock"
CMUX = (os.environ.get("CMUX_BUNDLED_CLI_PATH") or shutil.which("cmux")
        or "/Applications/cmux.app/Contents/Resources/bin/cmux")
MODELS = ("default", "sonnet", "opus", "haiku")
EFFORTS = ("low", "medium", "high")
RANGES = {"eot": (0.0, 1.0), "eager_eot": (0.0, 1.0), "eot_timeout_ms": (100, 10000), "local_speed": (0.5, 2.0)}
CHOICES = {"model": MODELS, "effort": EFFORTS, "style": ("plain", "brief", "caveman"),
           "narrate": ("handed-off", "all", "none"), "mouth": ("deepgram", "elevenlabs", "local"),
           "local_model": ("compressed", "full")}
WARNINGS = []                      # bad values seen while loading, for the caller to show
DEFAULTS = {"orchestrator": "", "model": "default", "effort": "low", "voice": "aura-2-orion-en",
            "ears": "flux-general-en", "eager_eot": 0.3, "eot": 0.7, "eot_timeout_ms": 1500,
            "barge_in": True, "memory": True, "push_to_talk": False, "address_me": False,
            "narrate": "handed-off", "mouth": "deepgram", "style": "plain", "elevenlabs_voice": "pNInz6obpgDQGcFmaJgB",
            "local_voice": "am_michael", "local_speed": 1.0, "local_model": "compressed", "code_colors": True,
            "deepgram_api_key": "", "elevenlabs_api_key": ""}
SECRETS = ("deepgram_api_key", "elevenlabs_api_key")
HELP = {"orchestrator": "cmux workspace that gets tasks by default",
        "model": "the brain's model, through your Claude Code login",
        "effort": "how hard the brain thinks before it answers",
        "voice": "any Deepgram Aura-2 voice: a name such as zeus, or a full model name",
        "ears": "Deepgram Flux model; flux-general-multi for other languages",
        "eager_eot": "confidence at which the brain starts on a turn early, before you have surely finished",
        "eot": "confidence at which your turn counts as finished",
        "eot_timeout_ms": "silence after which your turn ends whatever the confidence",
        "barge_in": "talking over it pauses it",
        "memory": "resume the last conversation, up to a week old",
        "push_to_talk": "the mic stays closed until you press Enter, for one turn",
        "address_me": "only turns that start with \"claudio\" count, for a room with other people",
        "narrate": "which sessions' finishes to narrate",
        "mouth": "who speaks: Deepgram Aura, ElevenLabs, or local (Kokoro on this Mac, no key)",
        "style": "how it talks: plain, brief (one sentence) or caveman",
        "elevenlabs_voice": "ElevenLabs voice id, when mouth is elevenlabs",
        "local_voice": "Kokoro voice, when mouth is local: am_michael, af_heart, bm_george…",
        "local_speed": "how fast the local voice speaks, 0.5 to 2.0",
        "local_model": "Kokoro model: compressed (88 MB, about twice as fast) or full (325 MB, a little cleaner)",
        "code_colors": "highlight code blocks in colour; off shows them as plain text",
        "deepgram_api_key": "Deepgram key, for ears and the Aura mouth",
        "elevenlabs_api_key": "ElevenLabs key, when mouth is elevenlabs"}
PROJECT_FILE = ".claudio.json"      # in the project root: keys that override the global ones there
KINDS = {k: (lambda v: v.lower() in ("1", "true", "yes", "on")) if isinstance(d, bool) else type(d)
         for k, d in DEFAULTS.items()}


def _read(path):
    try:
        data = json.load(open(path))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def stored():
    """What the global files hold, nothing merged: the only thing `save` writes back."""
    c = dict(DEFAULTS)
    c.update({k: v for k, v in _read(CONF).items() if k in DEFAULTS and k not in SECRETS})
    c.update({k: v for k, v in _read(SECRETS_FILE).items() if k in SECRETS})
    legacy = _read(CONF)
    if any(legacy.get(k) for k in SECRETS):        # a key left in config.json by an older version: move it
        for k in SECRETS:
            c[k] = c[k] or legacy.get(k, "")
        save(c)
    return c


TRUE, FALSE = ("1", "true", "yes", "on"), ("0", "false", "no", "off")
MAY_BE_EMPTY = ("orchestrator",)


def check(key, value):
    """The value as its proper type, or a message saying why it cannot be."""
    kind = type(DEFAULTS[key])
    if kind is bool:
        if isinstance(value, bool):
            v = value
        elif str(value).strip().lower() in TRUE:
            v = True
        elif str(value).strip().lower() in FALSE:
            v = False
        else:
            return None, f"{key} must be true or false, not {value!r}"
    elif kind is int:
        try:
            f = float(value) if not isinstance(value, bool) else None
        except (TypeError, ValueError):
            f = None
        if f is None or not f.is_integer():
            return None, f"{key} must be a whole number, not {value!r}"
        v = int(f)
    elif kind is float:
        try:
            v = float(value) if not isinstance(value, bool) else None
        except (TypeError, ValueError):
            v = None
        if v is None or v != v:
            return None, f"{key} must be a number, not {value!r}"
    else:
        if not isinstance(value, str):
            return None, f"{key} must be text, not {value!r}"
        v = value.strip()
        if not v and key not in MAY_BE_EMPTY:
            return None, f"{key} cannot be empty"
    if key == "voice":                         # "Zeus", "ELECTRA", a misheard "Elektra", "aura-2-zues-en": the model name
        low = v.lower()
        if low.startswith("aura-") and not re.fullmatch(r"aura-2-[a-z]+-en|aura-2-\w+", low):
            v = low                            # an Aura-1 voice, kept as given
        elif re.fullmatch(r"aura-2-[a-z]+-[a-z]{2}", low) and not low.endswith("-en"):
            v = low                            # Aura-2 in another language: not in the English list
        else:
            near = difflib.get_close_matches(low.removeprefix("aura-2-").removesuffix("-en"), AURA, 1, 0.7)
            if not near:
                return None, f"voice must be an Aura-2 voice, one of {', '.join(AURA)}, not {v!r}"
            v = f"aura-2-{near[0]}-en"
    if key in CHOICES and v not in CHOICES[key]:
        return None, f"{key} must be one of {', '.join(CHOICES[key])}, not {v!r}"
    if key in RANGES and not RANGES[key][0] <= v <= RANGES[key][1]:
        return None, f"{key} must be between {RANGES[key][0]} and {RANGES[key][1]}, not {v!r}"
    return v, None


def _merge(c, values, source):
    """Fold values in, keeping only the ones that check out; the rest become warnings."""
    for k, v in values.items():
        if k not in DEFAULTS or k in SECRETS:
            continue
        good, why = check(k, v)
        if why:
            WARNINGS.append(f"{source}: {why}; keeping {c[k]!r}")
        else:
            c[k] = good


def load():
    """The settings for this run: global, then the project's .claudio.json, then CLAUDIO_<KEY> env.
    Creates the persona file on first use. Bad values are skipped and listed in WARNINGS."""
    os.makedirs(DIR, exist_ok=True)
    WARNINGS.clear()
    _persona_file()
    c = dict(DEFAULTS)
    saved = stored()
    _merge(c, {k: saved[k] for k in DEFAULTS if k not in SECRETS}, CONF)
    for k in SECRETS:
        c[k] = saved[k]
    _merge(c, _read(PROJECT_FILE), PROJECT_FILE)
    for secret in SECRETS:
        if os.environ.get(secret.upper()):
            c[secret] = os.environ[secret.upper()]
    _merge(c, {k: os.environ["CLAUDIO_" + k.upper()] for k in DEFAULTS if "CLAUDIO_" + k.upper() in os.environ}, "environment")
    return c


def save(cfg):
    """Write the global files. Pass values from `stored()` (plus your edits), never from `load()`,
    or a project's or the environment's one-run overrides become everyone's defaults."""
    os.makedirs(DIR, exist_ok=True)
    _write(CONF, {k: cfg[k] for k in DEFAULTS if k not in SECRETS}, 0o644)
    _write(SECRETS_FILE, {k: cfg.get(k, "") for k in SECRETS}, 0o600)


def _write(path, data, mode):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


AURA = ["amalthea", "andromeda", "apollo", "arcas", "aries", "asteria", "athena", "atlas", "aurora", "callista", "cora",
        "cordelia", "delia", "draco", "electra", "harmonia", "helena", "hera", "hermes", "hyperion", "iris", "janus",
        "juno", "jupiter", "luna", "mars", "minerva", "neptune", "odysseus", "ophelia", "orion", "orpheus", "pandora",
        "phoebe", "pluto", "saturn", "selene", "thalia", "theia", "vesta", "zeus"]   # Deepgram's English Aura-2 voices, 2026-10


def fetch_aura(key):
    """Replace AURA with Deepgram's current list, when it can be reached. Blocking: run it off the event loop."""
    try:
        req = urllib.request.Request("https://api.deepgram.com/v1/models", headers={"Authorization": f"Token {key}"})
        names = sorted({m["name"] for m in json.load(urllib.request.urlopen(req, timeout=10)).get("tts", [])
                        if str(m.get("canonical_name", "")).startswith("aura-2-") and m["canonical_name"].endswith("-en")})
    except (OSError, ValueError, KeyError, TypeError):
        return
    if names:
        AURA[:] = names


def allowed():
    """The rules in ALLOW, such as Bash(gh:*) or WebFetch; blank lines and # comments skipped."""
    try:
        return [r for r in (line.split("#")[0].strip() for line in open(ALLOW)) if r]
    except OSError:
        return []


NOTES = ("~/Desktop", "~/Documents")   # where the brain may write a note: .md and .txt files only
WRAPPERS = {"env", "sh", "bash", "zsh", "dash", "fish", "python", "python3", "node", "ruby", "perl", "xargs", "sudo",
            "eval", "exec", "nohup", "time", "command", "nice", "timeout", "watch", "osascript", "open", "npx", "uvx"}


def openable(target):
    """What `claudio open` may open, as open takes it, or None: a web link, or a .md/.txt note in a notes folder.
    Never an app, a script or open's own flags: the brain may open these unasked."""
    if re.fullmatch(r"https?://[^\s\"'`]+", target):
        return target
    path = os.path.realpath(os.path.expanduser(target))
    ok = path.endswith((".md", ".txt")) and os.path.isfile(path) and any(
        path.startswith(os.path.realpath(os.path.expanduser(d)) + "/") for d in NOTES)
    return path if ok else None


def outside(tool_input, cwd, dirs):
    """The folder a refused tool use reaches outside the working one and the allowed ones, or None: its git
    repo when it is in one, else the nearest folder that exists. claude -p refuses those whatever the rules."""
    import subprocess
    values = {**tool_input, "command": " ".join(str(tool_input["command"]).split()[1:])} if "command" in tool_input else tool_input
    text = re.sub(r"'[^']*\s[^']*'|\"[^\"]*\s[^\"]*\"", " ", " ".join(str(v) for v in values.values()))   # not the program, not a quoted message
    for p in re.findall(r"(?:^|(?<=[\s\"'=]))(~?/[^\s\"';|&*?{}]+)", text):
        path = os.path.expanduser(p).rstrip("/")
        while path and not os.path.isdir(path):
            path = os.path.dirname(path)
        if not path or path == "/" or path.startswith("/dev") or any(
                path == d or path.startswith(d.rstrip("/") + "/") for d in (cwd, *dirs)):
            continue
        try:
            top = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True,
                                 text=True, timeout=3).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            top = ""
        return top or path
    return None


def rule_for(tool, tool_input, cwd=None):
    """The rule that allows a refused tool use, and how to say what was refused. A folder outside the working one
    is the rule when it is the reason; else for Bash, its leading plain words up to three, so "gh issue view 727
    -R x" gives Bash(gh issue view:*) and a yes allows that kind of command, not all of gh."""
    folder = outside(tool_input, cwd or os.getcwd(), [*allowed_dirs(), *map(os.path.expanduser, NOTES)])
    if folder:
        return folder, "into " + folder.replace(os.path.expanduser("~"), "~", 1)
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return None, ""                        # a bare Write would allow any file anywhere: add a narrow rule by hand
    if tool != "Bash":
        return tool, f"to use {tool}"
    words = []
    for w in str(tool_input.get("command", "")).split():
        if len(words) == 3 or not re.fullmatch(r"[a-z][\w.-]*", w):
            break
        words.append(w)
    if not words or words[0] in WRAPPERS:      # VAR=x, env, sh -c, python -c…: a yes would allow any command
        return None, ""
    prefix = " ".join(words)
    return f"Bash({prefix}:*)", f"to run `{prefix}`"


def allowed_dirs():
    """The folders in ALLOW (a line that is a path), given to the brain with --add-dir."""
    return [os.path.expanduser(r) for r in allowed() if r.startswith(("/", "~"))]


def allow(rule):
    """Add a rule to ALLOW, which restarts the brain with it."""
    os.makedirs(DIR, exist_ok=True)
    with open(ALLOW, "a") as f:
        f.write(f"{rule}\n")


ADDITIONS = """<!--
Your additions to claudio's persona. claudio's own rules come from the package and stay up to date;
whatever you write below is added after them, and wins where they disagree. Saving restarts the brain.
-->
"""
FULL = "You are the voice in front of"   # how a whole persona starts: older versions copied one here
PACKAGED = {"192f75ad59c2cd26", "1db85bb7b3de079f", "2968da599f69e3f7", "404972bf6b6ac69e", "42c31234ba05e10e",
            "4804450a5cbcf202", "4ec8cc6083d69c40", "54a344c215392748", "6bb0bc1be0ea00c9", "87c50e7146225d00",
            "8d611f9f34ffc895", "8dc40ed291c14f27", "9435c916aefdae7c", "c6b8a09b88c21cb1", "d22ef11225abb39d",
            "d9c1b1870e779063", "eeb0428322d4d3e5", "efa4ae1ab656d2a1"}   # every persona claudio shipped as a copy


def _persona_file():
    """PROMPT holds the user's additions. A copy of a shipped persona, never edited, becomes an empty one; an
    edited copy stays the whole persona, with a warning that claudio's later rules can't reach it."""
    try:
        mine = open(PROMPT, "rb").read()
    except OSError:
        mine = None
    if mine is None or hashlib.sha256(mine).hexdigest()[:16] in PACKAGED or mine == open(PACKAGED_PROMPT, "rb").read():
        with open(PROMPT, "w") as f:
            f.write(ADDITIONS)
    elif mine.decode(errors="replace").lstrip().startswith(FULL):
        WARNINGS.append(f"{PROMPT} is a whole persona of your own, so claudio's newer rules don't reach it; "
                        "keep only your changes there (see the persona docs)")


def persona():
    """What the brain is told about itself: the package's persona, then the user's additions."""
    base = open(PACKAGED_PROMPT).read()
    try:
        mine = open(PROMPT).read()
    except OSError:
        return base
    if mine.lstrip().startswith(FULL):
        return mine
    mine = re.sub(r"<!--.*?-->", "", mine, flags=re.S).strip()
    return base + (f"\n\nThe user's own additions, which win over anything above:\n{mine}" if mine else "")


def mcp_servers():
    """The names of the servers in MCP, [] when there is no such file or it can't be read."""
    servers = _read(MCP).get("mcpServers")
    return list(servers) if isinstance(servers, dict) else []


def set_key(key, value):
    if key not in KINDS or key in SECRETS:
        raise SystemExit(f"usage: claudio set <{'|'.join(k for k in KINDS if k not in SECRETS)}> <value>")
    v, why = check(key, value)
    if why:
        raise SystemExit(why)
    cfg = stored()
    cfg[key] = v
    save(cfg)
    return v


def parse_surfaces(text):
    """`cmux surface list` → {8-char surface id: (workspace title, surface title, cwd, the id cmux takes)}.
    cmux now takes only the full UUID (or a ref), listed as local/terminal/<UUID>; older versions took the 8 chars."""
    found, ws = {}, None
    for line in text.splitlines():
        if m := re.match(r"^\s{4}(\S.*?)\s+workspace:\d+", line):
            ws = m.group(1)
        elif m := re.match(r"^\s{6}\S\s+([0-9A-F]{8})\s+(.*?)\s{2,}(\S+)", line):
            full = re.search(r"/(%s[0-9A-F-]{28})\)" % m.group(1), line)
            found[m.group(1)] = (ws, m.group(2), m.group(3), full.group(1) if full else m.group(1))
    return found


def replies(messages, me, since):
    """From claudio's queued inbox, newest first: the messages to read out. Not its own (a handoff that came back
    to its pane), not ones from before it started."""
    return [m for m in messages if str(m.get("sender_surface_id", "")).upper() != me.upper()
            and m.get("created_at", 0) >= since]


def surfaces():
    import subprocess
    try:
        found = parse_surfaces(subprocess.run([CMUX, "surface", "list"], capture_output=True, text=True, timeout=5).stdout)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    me = os.environ.get("CMUX_SURFACE_ID", "").upper()        # claudio's own pane is no session to hand work to
    return {sid: v for sid, v in found.items() if v[3].upper() != me}


def workspaces():
    """Workspace titles in the order cmux lists them."""
    seen = []
    for ws, *_ in surfaces().values():
        if ws and ws not in seen:
            seen.append(ws)
    return seen


def configured():
    return os.path.exists(CONF)
