"""The pure parts: what would break silently. No network, no audio, no claude."""
import os, sys, types

# agent imports sounddevice and websockets at module load; stub them so the pure functions import anywhere
for name in ("sounddevice", "websockets", "websockets.exceptions"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["websockets"].exceptions = sys.modules["websockets.exceptions"]
sys.modules["websockets.exceptions"].WebSocketException = Exception
sys.modules["websockets"].ConnectionClosed = Exception

from claudio import config
from claudio.agent import SENTENCE, backchannel, norm, parse_surfaces


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


def test_config_env_overrides_one_run(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DIR", str(tmp_path))
    monkeypatch.setattr(config, "CONF", str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "PROMPT", str(tmp_path / "prompt.md"))
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
