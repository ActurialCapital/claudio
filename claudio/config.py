"""Settings in ~/.config/claudio: config.json (the knobs), secrets.json (the keys, mode 600, never named to the
brain) and prompt.md (the persona, yours to edit). Also the few paths and parsers both the agent and the CLI need."""
import json, os, re, shutil

DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "claudio")
CONF = os.path.join(DIR, "config.json")
PROMPT = os.path.join(DIR, "prompt.md")
PACKAGED_PROMPT = os.path.join(os.path.dirname(__file__), "prompt.md")
SECRETS_FILE = os.path.join(DIR, "secrets.json")
SESSION = os.path.join(DIR, "session")
MCP = os.path.join(DIR, "mcp.json")      # MCP servers for the brain, as in a .mcp.json; none when it is absent
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
        "voice": "any Deepgram Aura-2 voice",
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
    if not os.path.exists(PROMPT):
        shutil.copy(PACKAGED_PROMPT, PROMPT)
    WARNINGS.clear()
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
    """`cmux surface list` → {8-char surface id: (workspace title, surface title, cwd)}."""
    found, ws = {}, None
    for line in text.splitlines():
        if m := re.match(r"^\s{4}(\S.*?)\s+workspace:\d+", line):
            ws = m.group(1)
        elif m := re.match(r"^\s{6}\S\s+([0-9A-F]{8})\s+(.*?)\s{2,}(\S+)", line):
            found[m.group(1)] = (ws, m.group(2), m.group(3))
    return found


def surfaces():
    import subprocess
    try:
        return parse_surfaces(subprocess.run([CMUX, "surface", "list"], capture_output=True, text=True, timeout=5).stdout)
    except (OSError, subprocess.TimeoutExpired):
        return {}


def workspaces():
    """Workspace titles in the order cmux lists them."""
    seen = []
    for ws, _, _ in surfaces().values():
        if ws and ws not in seen:
            seen.append(ws)
    return seen


def configured():
    return os.path.exists(CONF)
