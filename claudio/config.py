"""Settings in ~/.config/claudio: config.json (the knobs) and prompt.md (the persona, yours to edit)."""
import json, os, shutil

DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "claudio")
CONF = os.path.join(DIR, "config.json")
PROMPT = os.path.join(DIR, "prompt.md")
PACKAGED_PROMPT = os.path.join(os.path.dirname(__file__), "prompt.md")
SOCK = f"/tmp/claudio-{os.getuid()}.sock"
DEFAULTS = {"orchestrator": "", "model": "default", "effort": "low", "voice": "aura-2-orion-en",
            "ears": "flux-general-en", "eager_eot": 0.3, "eot": 0.7, "eot_timeout_ms": 1500,
            "barge_in": True, "memory": True, "push_to_talk": False, "address_me": False,
            "narrate": "handed-off", "mouth": "deepgram", "style": "plain", "elevenlabs_voice": "pNInz6obpgDQGcFmaJgB",
            "deepgram_api_key": "", "elevenlabs_api_key": ""}
SECRETS = ("deepgram_api_key", "elevenlabs_api_key")
PROJECT_FILE = ".claudio.json"      # in the project root: keys that override the global ones there
KINDS = {k: (lambda v: v.lower() in ("1", "true", "yes", "on")) if isinstance(d, bool) else type(d)
         for k, d in DEFAULTS.items()}


def load():
    """The settings, with CLAUDIO_<KEY> env overriding one run. Creates the files on first use."""
    os.makedirs(DIR, exist_ok=True)
    if not os.path.exists(PROMPT):
        shutil.copy(PACKAGED_PROMPT, PROMPT)
    c = dict(DEFAULTS)
    if os.path.exists(CONF):
        c.update(json.load(open(CONF)))
    if os.path.exists(PROJECT_FILE):
        try:
            c.update({k: v for k, v in json.load(open(PROJECT_FILE)).items() if k in DEFAULTS and k not in SECRETS})
        except ValueError:
            pass
    for secret in SECRETS:
        if os.environ.get(secret.upper()):
            c[secret] = os.environ[secret.upper()]
    for k in DEFAULTS:
        v = os.environ.get("CLAUDIO_" + k.upper())
        if v is not None:
            c[k] = KINDS[k](v)
    return c


def save(cfg):
    os.makedirs(DIR, exist_ok=True)
    json.dump({k: cfg[k] for k in DEFAULTS}, open(CONF, "w"), indent=2)
    os.chmod(CONF, 0o600)        # it may hold the Deepgram key


def set_key(key, value):
    if key not in KINDS or key in SECRETS:
        raise SystemExit(f"usage: claudio set <{'|'.join(k for k in KINDS if k not in SECRETS)}> <value>")
    cfg = load()
    cfg[key] = KINDS[key](value)
    save(cfg)
    print(f"{key} = {cfg[key]}")


def configured():
    return os.path.exists(CONF)
