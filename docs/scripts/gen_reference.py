"""Write docs/generated/reference.json from the code: settings, CLI commands, the setup voices.
Run from the repo root: `uv run python docs/scripts/gen_reference.py`. CI fails if the output is stale."""
import json, os, re
from claudio import cli, config

settings = []
for key, default in config.DEFAULTS.items():
    settings.append({
        "key": key,
        "type": {bool: "boolean", int: "integer", float: "number", str: "text"}[type(default)],
        "default": default,
        "choices": list(config.CHOICES.get(key, ())),
        "range": list(config.RANGES[key]) if key in config.RANGES else None,
        "help": config.HELP[key],
        "secret": key in config.SECRETS,
        "env": key.upper() if key in config.SECRETS else "CLAUDIO_" + key.upper(),
        "may_be_empty": key in config.MAY_BE_EMPTY,
    })

commands = []
for line in cli.USAGE.splitlines():
    if m := re.match(r"^(claudio(?: \S+)*?(?: <\w+>)*)\s{2,}(.+)$", line):
        commands.append({"usage": m.group(1), "help": m.group(2).rstrip(":")})

reference = {"settings": settings, "commands": commands,
             "voices": [{"id": v, "description": d} for v, d in cli.VOICES],
             "hooks": [{"event": e, "matcher": m} for e, m in cli.HOOKS]}

out = os.path.join(os.path.dirname(__file__), "..", "generated", "reference.json")
with open(out, "w") as f:
    json.dump(reference, f, indent=2)
    f.write("\n")
