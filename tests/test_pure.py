"""The pure parts: what would break silently. No network, no audio, no claude."""
import os, sys, types

# agent imports sounddevice and websockets at module load; stub them so the pure functions import anywhere
for name in ("sounddevice", "websockets", "websockets.exceptions"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["websockets"].exceptions = sys.modules["websockets.exceptions"]
sys.modules["websockets.exceptions"].WebSocketException = Exception
sys.modules["websockets"].ConnectionClosed = Exception

from claudio import config
from claudio.agent import SENTENCE, backchannel, norm, parse_slash
from claudio.config import parse_surfaces


def split(text):
    out, buf = [], ""
    for ch in text:
        buf += ch
        while m := SENTENCE.search(buf):
            out.append(buf[:m.end()].strip())
            buf = buf[m.end():]
    if buf.strip():
        out.append(buf.strip())
    return out


def test_sentences_split_at_terminal_punctuation_followed_by_space():
    assert split("One. Two! Three? Four") == ["One.", "Two!", "Three?", "Four"]


def test_sentences_keep_decimals_and_abbreviations_without_a_space():
    assert split("Version 2.1 is out. Ship it.") == ["Version 2.1 is out.", "Ship it."]


def test_sentences_allow_a_closing_quote_or_bracket():
    assert split('He said "go." Then left.') == ['He said "go."', "Then left."]


def test_sentences_split_at_a_newline_for_list_items():
    assert split("Three parts:\n- Silero\n- Kokoro.") == ["Three parts:", "- Silero", "- Kokoro."]


def test_parse_slash_skips_filler_takes_bare_styles_and_fixes_misheard_ones():
    assert parse_slash("slash um i want a caveman") == ("style", "caveman")
    assert parse_slash("slash caveman") == ("style", "caveman")
    assert parse_slash("slash style pavement") == ("style", "caveman")
    assert parse_slash("slash model sonnet") == ("model", "sonnet")
    assert parse_slash("slash banana") == ("banana", "")
    assert parse_slash("can you add a slash command") is None


def test_backchannel_is_short_or_only_filler():
    assert backchannel("mm-hm")
    assert backchannel("yeah yeah")
    assert backchannel("")
    assert not backchannel("what about the tests")
    assert not backchannel("no wait")


def test_norm_lowercases_and_strips_punctuation():
    assert norm("Hello, World!") == ["hello", "world"]


SURFACES = """This Mac  JR's MacBook Pro  · 2 terminals
  terminals/
    Sequencer  workspace:1000020009
      ● 12BA24EB  Aloha refactor advisor  /Users/jmr/GitHub/aloha  (open: 12BA24EB)
      ● DFEF3D7D  pnpm dev  /Users/jmr/GitHub/aloha  (open: DFEF3D7D)
    Voice  workspace:1000020019
      ● 34E60333  Speech in Claude code  /Users/jmr/GitHub/aloha  (open: 34E60333)
"""


def test_parse_surfaces_maps_surface_ids_to_workspace_title_surface_title_and_cwd():
    got = parse_surfaces(SURFACES)
    assert got["12BA24EB"] == ("Sequencer", "Aloha refactor advisor", "/Users/jmr/GitHub/aloha")
    assert got["34E60333"][0] == "Voice"
    assert len(got) == 3


def _scratch(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONF", str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "SECRETS_FILE", str(tmp_path / "secrets.json"))
    monkeypatch.setattr(config, "PROMPT", str(tmp_path / "prompt.md"))
    monkeypatch.setattr(config, "PROJECT_FILE", str(tmp_path / ".claudio.json"))


def test_config_env_overrides_one_run(tmp_path, monkeypatch):
    _scratch(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAUDIO_EFFORT", "high")
    monkeypatch.setenv("CLAUDIO_BARGE_IN", "false")
    monkeypatch.setenv("CLAUDIO_EOT", "0.5")
    c = config.load()
    assert c["effort"] == "high" and c["barge_in"] is False and c["eot"] == 0.5
    assert os.path.exists(config.PROMPT)


def test_config_set_key_rejects_unknown_and_the_secret():
    import pytest
    with pytest.raises(SystemExit):
        config.set_key("nope", "1")
    with pytest.raises(SystemExit):
        config.set_key("deepgram_api_key", "x")


def test_set_key_writes_global_values_only_and_keeps_secrets_apart(tmp_path, monkeypatch):
    _scratch(tmp_path, monkeypatch)
    (tmp_path / ".claudio.json").write_text('{"orchestrator": "FromRepo", "narrate": "none"}')
    monkeypatch.setenv("CLAUDIO_STYLE", "caveman")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "env-key")
    config.set_key("effort", "high")
    import json
    on_disk = json.load(open(config.CONF))
    assert on_disk["effort"] == "high"
    assert on_disk["orchestrator"] == "" and on_disk["narrate"] == "handed-off" and on_disk["style"] == "plain"
    assert "deepgram_api_key" not in on_disk
    assert json.load(open(config.SECRETS_FILE))["deepgram_api_key"] == ""
    assert oct(os.stat(config.SECRETS_FILE).st_mode)[-3:] == "600"
    assert config.load()["orchestrator"] == "FromRepo"       # the project override still applies at run time


def test_set_key_rejects_unknown_model_and_effort(tmp_path, monkeypatch):
    import pytest
    _scratch(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        config.set_key("model", "opus-four")
    with pytest.raises(SystemExit):
        config.set_key("effort", "max")
    config.set_key("model", "sonnet")


def test_project_file_that_is_not_an_object_is_ignored(tmp_path, monkeypatch):
    _scratch(tmp_path, monkeypatch)
    for bad in ("[]", '"x"', "null", "42", "{"):
        (tmp_path / ".claudio.json").write_text(bad)
        assert config.load()["orchestrator"] == ""


def test_legacy_key_in_config_json_moves_to_secrets(tmp_path, monkeypatch):
    _scratch(tmp_path, monkeypatch)
    import json
    (tmp_path / "config.json").write_text(json.dumps({"effort": "low", "deepgram_api_key": "old-key"}))
    c = config.stored()
    assert c["deepgram_api_key"] == "old-key"
    assert "deepgram_api_key" not in json.load(open(config.CONF))
    assert json.load(open(config.SECRETS_FILE))["deepgram_api_key"] == "old-key"


def test_slash_only_at_the_start_of_a_turn():
    from claudio.agent import SLASH
    assert SLASH.search("slash mute")
    assert SLASH.search("um slash effort low").groups() == ("effort", "low")
    assert SLASH.search("mute slash mute")
    assert not SLASH.search("ask the orchestrator to add a slash command for deploy")
    assert not SLASH.search("the path has a slash in it")


def test_check_rejects_bad_types_choices_and_ranges():
    assert config.check("eot", "abc")[1].startswith("eot must be a number")
    assert config.check("eot_timeout_ms", "1.5")[1].startswith("eot_timeout_ms must be a whole number")
    assert config.check("eot", "7")[1].startswith("eot must be between")
    assert config.check("model", "opus-four")[1].startswith("model must be one of")
    assert config.check("model", 123)[1]
    assert config.check("effort", None)[1]
    assert config.check("barge_in", "false") == (False, None)
    assert config.check("eot", "0.6") == (0.6, None)


def test_load_skips_bad_project_values_with_a_warning(tmp_path, monkeypatch):
    _scratch(tmp_path, monkeypatch)
    (tmp_path / ".claudio.json").write_text('{"model": 123, "effort": null, "eot": "x", "voice": 7, "orchestrator": "Core"}')
    c = config.load()
    assert (c["model"], c["effort"], c["eot"], c["orchestrator"]) == ("default", "low", 0.7, "Core")
    assert c["voice"] == "aura-2-orion-en"                     # a number for a string key is refused
    assert len(config.WARNINGS) == 4


def test_tool_line_survives_markup_characters(capsys):
    from claudio import ui
    ui.tool("Grep", {"pattern": "[/]"})
    ui.tool("Bash", {"command": "git log --grep=[/x] --oneline"})
    ui.tool("Read", {"file_path": "/app/[id].tsx"})
    out = capsys.readouterr().out
    assert "[/]" in out and "[/x]" in out and "[id].tsx" in out


def test_settings_write_follows_a_symlink_and_refuses_odd_hook_shapes(tmp_path, monkeypatch):
    import json, pytest
    from claudio import cli
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}))
    link = tmp_path / "settings.json"
    link.symlink_to(real)
    monkeypatch.setattr(cli, "SETTINGS", str(link))
    cli.install()
    assert link.is_symlink() and "hooks" in json.load(open(real)) and "permissions" in json.load(open(real))
    for bad in ('{"hooks": []}', '{"hooks": {"Stop": ["x"]}}', '{"permissions": {}, }'):
        real.write_text(bad)
        with pytest.raises(SystemExit):
            cli.install()
        assert real.read_text() == bad


def test_check_is_strict_about_bools_strings_and_whole_numbers():
    assert config.check("barge_in", "ture")[1].startswith("barge_in must be true or false")
    assert config.check("barge_in", "no") == (False, None)
    assert config.check("barge_in", "Yes ") == (True, None)
    assert config.check("voice", ["x"])[1].startswith("voice must be text")
    assert config.check("voice", "")[1] == "voice cannot be empty"
    assert config.check("orchestrator", "") == ("", None)
    assert config.check("eot_timeout_ms", "1500.0") == (1500, None)
    assert config.check("eot_timeout_ms", 1500.7)[1].startswith("eot_timeout_ms must be a whole number")
    assert config.check("eot", "nan")[1].startswith("eot must be a number")


def test_ui_helpers_print_brackets_literally(capsys):
    from claudio import ui
    ui.warn("model must be one of a, b, not '[/]'")
    ui.note("/effort [/]")
    ui.setting("orchestrator → [wip] core")
    ui.check(False, "orchestrator '[wip] core' is live", "hint [x]")
    out = capsys.readouterr().out
    assert out.count("[/]") == 2 and "[wip] core" in out and out.count("[wip]") == 2 and "[x]" in out


def test_eleven_mouth_maps_audio_to_sentences_by_character_position():
    from claudio.agent import ElevenMouth
    m = ElevenMouth()
    for t in ("One. ", "Two two. ", "Three. "):            # say() without a socket: just the bookkeeping
        m.ends.append((m.ends[-1] if m.ends else 0) + len(t))
    seen = []
    for chars in (list("One. "), list("Two "), list("two. "), list("Three. ")):
        start = m.chars
        m.chars += len(chars)
        m.current = next((n for n, end in enumerate(m.ends) if start < end), max(0, len(m.ends) - 1))
        seen.append(m.got)
    assert seen == [0, 1, 1, 2]


def test_every_setting_has_a_description():
    assert set(config.HELP) == set(config.DEFAULTS)


def test_sun_mark_is_a_square_block_of_equal_rows():
    from claudio import ui
    rows = ui.sun()
    assert len(rows) == 6 and {len(r) for r in rows} == {12} and any(r.strip() for r in rows)


def test_set_key_returns_the_value_and_prints_nothing(tmp_path, monkeypatch, capsys):
    _scratch(tmp_path, monkeypatch)
    assert config.set_key("voice", "aura-2-thalia-en") == "aura-2-thalia-en"
    assert capsys.readouterr().out == ""      # claudio's own transcript is on screen when the brain changes a setting


def test_local_mouth_counts_a_sentence_only_after_its_audio(monkeypatch):
    import asyncio, numpy as np
    from claudio import agent
    monkeypatch.setattr(agent, "cfg", {"local_voice": "am_michael", "local_speed": 1.0}, raising=False)
    m = agent.LocalMouth()
    m.tts = types.SimpleNamespace(create=lambda text, voice, speed: (np.array([0.5, -2.0], np.float32), 24000))
    seen = []

    async def go():
        for t in ("One.", "  ", "Two."):
            await m.say(t)
        task = asyncio.create_task(m.receive(lambda b: seen.append((m.got, b))))
        while not m.done():
            await asyncio.sleep(0)
        task.cancel()
    asyncio.run(go())
    pcm = np.array([16383, -32767], "<i2").tobytes()          # 0.5 and a clipped -2.0 as int16
    assert seen == [(0, pcm), (2, pcm)]                         # the blank sentence counts, but plays nothing
