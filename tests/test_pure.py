"""The pure parts: what would break silently. No network, no audio, no claude."""
import os, sys, types

# agent imports sounddevice and websockets at module load; stub them so the pure functions import anywhere
for name in ("sounddevice", "websockets", "websockets.exceptions"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["websockets"].exceptions = sys.modules["websockets.exceptions"]
sys.modules["websockets.exceptions"].WebSocketException = Exception
sys.modules["websockets"].ConnectionClosed = Exception

import pytest
from claudio import config
from claudio.agent import SENTENCE, backchannel, norm, parse_slash, shown_block
from claudio.ui import spoken


@pytest.fixture(autouse=True)
def no_real_transcripts(tmp_path, monkeypatch):
    """No test writes to the user's transcripts: they feed "what did we do today"."""
    from claudio import ui
    monkeypatch.setattr(ui, "TRANSCRIPTS", str(tmp_path / "transcripts"))
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
    assert parse_slash("okay so slash mute") == ("mute", "")
    assert parse_slash("add a slash command") is None
    assert parse_slash("slash slash mute") == ("mute", "")
    assert parse_slash("yeah slash stop") == ("stop", "")
    assert parse_slash("slash e fort low") == ("effort", "low")      # a word split in two
    assert parse_slash("slash efort") == ("effort", "")
    assert parse_slash("slash pandora") == ("voice", "pandora")
    assert parse_slash("slash permission skip") == ("permissions", "skip")
    assert parse_slash("slash skip permission")[0] == "permissions"      # the handler finds "skip" in the words
    assert parse_slash("type slash help in the session") is None


def test_shown_block_takes_a_whole_table_or_fence_and_waits_while_unsure():
    table = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert shown_block(table + "Kokoro wins.") == len(table)
    assert shown_block("| a | b |\n|---") is None                 # more rows may come
    assert shown_block("| a |", final=True) == 5
    fence = "```py\nx = 1\n```\n"
    assert shown_block(fence + "That sets x.") == len(fence)
    assert shown_block("```py\nx = 1") is None
    assert shown_block("``") is None and shown_block("Hello") == 0


def test_spoken_drops_bullets_and_markup():
    assert spoken("- Use **Kokoro** with `claudio set` and *care*.") == "Use Kokoro with claudio set and care."
    assert spoken("2 * 3 * 4 is 24.") == "2 * 3 * 4 is 24."
    assert spoken("- `/clear` starts over, see docs/x.md.") == "slash clear starts over, see docs/x.md."
    assert spoken("Glob **/*.py and `rm **/*.pyc`.") == "Glob **/*.py and rm **/*.pyc."
    assert spoken("See [the pricing page](https://deepgram.com/pricing).") == "See the pricing page."


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
      ● 12BA24EB  Aloha refactor advisor  /Users/jmr/GitHub/aloha  (open: 12BA24EB)  (cmux surface open local/terminal/12BA24EB-6732-4999-BB16-7EE5AF2D35EE)
      ● DFEF3D7D  pnpm dev  /Users/jmr/GitHub/aloha  (open: DFEF3D7D)
    Voice  workspace:1000020019
      ● 34E60333  Speech in Claude code  /Users/jmr/GitHub/aloha  (open: 34E60333)
"""


def test_parse_surfaces_maps_surface_ids_to_workspace_title_surface_title_and_cwd():
    got = parse_surfaces(SURFACES)
    assert got["12BA24EB"] == ("Sequencer", "Aloha refactor advisor", "/Users/jmr/GitHub/aloha",
                               "12BA24EB-6732-4999-BB16-7EE5AF2D35EE")
    assert got["DFEF3D7D"][3] == "DFEF3D7D"          # an older cmux lists no UUID: the 8 chars it took
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


def test_two_live_blocks_settle_in_order():
    import io, time
    from rich.console import Console
    from claudio import ui
    console, log = ui.console, ui.log
    ui.console, ui.log = Console(file=io.StringIO(), width=60), lambda line: None
    try:
        ui.me_line("Checking the screen.\n", True, live=True, secs=lambda: 0.01)
        time.sleep(0.5)
        ui.me_line("Sequencer is running the tests.\n", True, live=True, secs=lambda: 0.01)   # a second block: settles the first
        assert len(ui.fading) == 1 and "Checking the screen." in ui.console.file.getvalue()
    finally:
        ui.fading.clear()
        ui.console, ui.log = console, log


def test_rule_for_allows_the_kind_of_command_not_the_whole_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOW", str(tmp_path / "allow"))
    here = str(tmp_path)
    assert config.rule_for("Bash", {"command": "gh issue view 727 --repo a/b"}, here) == ("Bash(gh issue view:*)", "to run `gh issue view`")
    assert config.rule_for("Bash", {"command": "curl -s https://x 2>/dev/null"}, here) == ("Bash(curl:*)", "to run `curl`")
    assert config.rule_for("WebFetch", {"url": "https://x"}, here) == ("WebFetch", "to use WebFetch")


def test_rule_for_offers_the_folder_when_it_is_outside(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ALLOW", str(tmp_path / "allow"))
    (tmp_path / "repo" / "src").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    rule, what = config.rule_for("Bash", {"command": f"wc -l {tmp_path}/repo/src/*.py"}, str(work))
    assert rule == str(tmp_path / "repo" / "src") and what.startswith("into ")
    (tmp_path / "allow").write_text(f"{tmp_path}/repo\n")      # allowed: the command is the reason now
    assert config.rule_for("Bash", {"command": f"wc -l {tmp_path}/repo/src/*.py"}, str(work))[0] == "Bash(wc:*)"


def test_voice_names_become_deepgram_models():
    assert config.check("voice", "Zeus") == ("aura-2-zeus-en", None)
    assert config.check("voice", "ELECTRA") == ("aura-2-electra-en", None)
    assert config.check("voice", "Elektra") == ("aura-2-electra-en", None)     # as heard
    assert config.check("voice", "aura-asteria-en") == ("aura-asteria-en", None)
    assert config.check("voice", "banana")[0] is None


def test_replies_are_new_messages_from_others():
    me = "136B82D3-8ACD"
    msgs = [{"id": "a", "sender_surface_id": "34E60333", "created_at": 200},
            {"id": "b", "sender_surface_id": me.lower(), "created_at": 200},     # a handoff that came back to its own pane
            {"id": "c", "sender_surface_id": "34E60333", "created_at": 50}]      # from before claudio started
    assert [m["id"] for m in config.replies(msgs, me, 100)] == ["a"]


def test_allowed_reads_one_rule_per_line(tmp_path, monkeypatch):
    f = tmp_path / "allow"
    f.write_text("# GitHub, all of it\nBash(gh:*)\n\nWebFetch  # docs pages\n")
    monkeypatch.setattr(config, "ALLOW", str(f))
    assert config.allowed() == ["Bash(gh:*)", "WebFetch"]
    monkeypatch.setattr(config, "ALLOW", str(tmp_path / "missing"))
    assert config.allowed() == []


def test_persona_is_the_package_plus_the_users_additions(tmp_path, monkeypatch):
    mine = tmp_path / "prompt.md"
    monkeypatch.setattr(config, "PROMPT", str(mine))
    base = open(config.PACKAGED_PROMPT).read()
    mine.write_text(base)                              # a shipped persona copied here, never edited
    config.WARNINGS.clear(); config._persona_file()
    assert mine.read_text() == config.ADDITIONS and config.persona() == base and not config.WARNINGS
    mine.write_text(config.ADDITIONS + "Call me Jean.\n")
    assert config.persona() == base + "\n\nThe user's own additions, which win over anything above:\nCall me Jean."
    mine.write_text(base + "\nAlways answer in French.\n")   # a whole persona, edited: still used, with a warning
    config.WARNINGS.clear(); config._persona_file()
    assert config.persona().endswith("Always answer in French.\n") and config.WARNINGS
