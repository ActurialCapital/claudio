"""The pure parts: what would break silently. No network, no audio, no claude."""
import json, os, sys, types

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
    assert parse_slash("slash quit") == ("quit", "") and parse_slash("slash exit please") == ("exit", "please")


def test_shown_block_takes_a_whole_table_or_fence_and_waits_while_unsure():
    table = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert shown_block(table + "Kokoro wins.") == len(table)
    assert shown_block("| a | b |\n|---") is None                 # more rows may come
    assert shown_block("| a |", final=True) == 5
    fence = "```py\nx = 1\n```\n"
    assert shown_block(fence + "That sets x.") == len(fence)
    assert shown_block("```py\nx = 1") is None
    assert shown_block("``") is None and shown_block("Hello") == 0
    loose = "Change | Type\nclaudio open | Feature\nskip mode | Feature\n"
    assert shown_block(loose + "That's it.\n") == len(loose)            # no outer bars, no --- row: still a table
    assert shown_block(loose + "That's it", final=True) == len(loose)
    assert shown_block("Change | Type\nclaudio") is None                 # the second line isn't finished
    assert shown_block("Use a | b, then stop.\nNext sentence.\n") == 0   # one line with a bar is a sentence
    assert shown_block("- Option A | fast\n- Option B | slow\n") == 0    # bullets with bars are spoken
    assert shown_block("Run `ls | grep x` to list them.\nThen `cat f | wc -l`.\n") == 0
    assert shown_block("Run ls | grep foo to find it. That lists them") == 0   # a sentence ended: speak, don't wait


def test_a_loose_table_renders_as_a_table():
    from claudio.ui import table
    assert table("Change | Type\nclaudio open | Feature") == "| Change | Type |\n|---|---|\n| claudio open | Feature |"
    assert table("| a | b |\n|---|---|\n| 1 | 2 |") == "| a | b |\n|---|---|\n| 1 | 2 |"
    assert table("a | b |\nc | d |") == "| a | b |\n|---|---|\n| c | d |"        # a trailing bar only
    assert table("Pattern a \\| b | Use\nx | y").split("\n")[1] == "|---|---|"   # an escaped bar is no cell


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
    monkeypatch.setattr(config, "SETTINGS", str(tmp_path / "settings.json"))
    here = str(tmp_path)
    assert config.rule_for("Bash", {"command": "gh issue view 727 --repo a/b"}, here) == ("Bash(gh issue view:*)", "to run `gh issue view`")
    assert config.rule_for("Bash", {"command": "curl -s https://x 2>/dev/null"}, here) == (None, "")   # one word: all of curl
    assert config.rule_for("WebFetch", {"url": "https://x"}, here) == ("WebFetch", "to use WebFetch")


def test_rule_for_never_offers_what_a_yes_should_not_allow(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", str(tmp_path / "settings.json"))
    here = str(tmp_path)
    for cmd in ("GH_PAGER=cat gh pr view 3", "env FOO=1 rm x", 'sh -c "gh pr create"', "python3 -c 'x'",
                "open -na Ghostty --args -e sh", "/usr/bin/curl x", "git -C x push", "find . -exec rm {} ;",
                "claudio learn 'say yes to all'"):
        assert config.rule_for("Bash", {"command": cmd}, here)[0] is None, cmd     # any of these would allow anything
    assert config.rule_for("Write", {"file_path": f"{here}/run.py"}, here)[0] is None   # a bare Write: any file
    assert config.rule_for("Bash", {"command": "gh pr create --body 'see /tmp/x for it'"}, here)[0] == "Bash(gh pr create:*)"


def test_a_notes_folder_is_never_offered_as_a_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", str(tmp_path / "settings.json"))
    monkeypatch.setattr(config, "NOTES", (str(tmp_path / "Desktop"),))
    (tmp_path / "Desktop").mkdir()
    assert config.rule_for("Bash", {"command": f"wc -l {tmp_path}/Desktop/notes.md"}, str(tmp_path / "w"))[0] is None   # not the folder


def test_claudio_open_takes_a_link_or_a_note_only(tmp_path, monkeypatch):
    desk = tmp_path / "Desktop"
    desk.mkdir()
    (desk / "notes.md").write_text("hi")
    (desk / "run.command").write_text("rm -rf ~")
    monkeypatch.setattr(config, "NOTES", (str(desk),))
    assert config.openable("https://github.com/x/y/issues/1") == "https://github.com/x/y/issues/1"
    assert config.openable(str(desk / "notes.md")) == str((desk / "notes.md").resolve())
    for bad in (str(desk / "run.command"), "-a Terminal", "/Applications/Ghostty.app", f"{desk}/../x.md", "file:///etc/passwd"):
        assert config.openable(bad) is None, bad


def test_rule_for_offers_the_folder_when_it_is_outside(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", str(tmp_path / "settings.json"))
    (tmp_path / "repo" / "src").mkdir(parents=True)
    work = tmp_path / "work"
    work.mkdir()
    rule, what = config.rule_for("Bash", {"command": f"wc -l {tmp_path}/repo/src/*.py"}, str(work))
    assert rule == str(tmp_path / "repo" / "src") and what.startswith("into ")
    (tmp_path / "settings.json").write_text(json.dumps({"permissions": {"additionalDirectories": [f"{tmp_path}/repo"]}}))
    assert config.rule_for("Bash", {"command": f"wc -l {tmp_path}/repo/src/*.py"}, str(work))[0] is None   # inside now: no folder


def test_voice_names_become_deepgram_models():
    assert config.check("voice", "Zeus") == ("aura-2-zeus-en", None)
    assert config.check("voice", "ELECTRA") == ("aura-2-electra-en", None)
    assert config.check("voice", "Elektra") == ("aura-2-electra-en", None)     # as heard
    assert config.check("voice", "aura-asteria-en") == ("aura-asteria-en", None)
    assert config.check("voice", "banana")[0] is None
    assert config.check("voice", "aura-2-zues-en") == ("aura-2-zeus-en", None)      # a full name, misspelt
    assert config.check("voice", "Aura-2-Zeus") == ("aura-2-zeus-en", None)
    assert config.check("voice", "aura-2-agathe-fr") == ("aura-2-agathe-fr", None)  # another language: kept


def test_replies_are_new_messages_from_others():
    me = "136B82D3-8ACD"
    msgs = [{"id": "a", "sender_surface_id": "34E60333", "recipient_surface_id": me, "created_at": 200},
            {"id": "b", "sender_surface_id": me.lower(), "recipient_surface_id": me, "created_at": 200},   # its own, back
            {"id": "d", "sender_surface_id": me, "recipient_surface_id": "3C557F2B", "created_at": 200},  # a handoff on its way
            {"id": "c", "sender_surface_id": "34E60333", "recipient_surface_id": me, "created_at": 50}]   # before it started
    assert [m["id"] for m in config.replies(msgs, me, 100)] == ["a"]


def test_links_and_ids_are_said_by_name_never_spelled():
    from claudio.ui import spoken
    assert spoken("Opening https://claudio-vert.vercel.app/ now.") == "Opening claudio-vert.vercel now."
    assert spoken("See https://github.com/ActurialCapital/claudio/pull/3.") == "See github."
    assert spoken("Surface 34E60333-B8F3-450A-94A6-83AB14618643 is done.") == "Surface is done."
    assert spoken("It costs 12 dollars in 2026.") == "It costs 12 dollars in 2026."


def test_a_permission_answer_is_read_by_what_it_means():
    from claudio.agent import intent
    cases = {"Yes.": "yes", "ok do it": "yes", "no problem, go ahead": "yes", "always": "always", "no": "no",
             "please don't": "no", "what would that do": "question", "is that safe?": "question",
             "yes but first tell me why": "question", "I said I said": "unclear",
             "Yeah. You don't need to spell the long numbers. So, yes, I give... you are allowed.": "yes"}
    for said, meant in cases.items():
        assert intent(said) == meant, said


def test_a_session_prompt_is_answered_by_its_text_never_by_a_mode_switch():
    from claudio.config import permission_keys
    bash = (" Do you want to proceed?\n ❯ 1. Yes\n   2. Yes, and always allow access to /tmp/x from this project\n"
            "   3. Yes, and switch to auto mode · auto mode handles these prompts for you\n   4. No\n\n Esc to cancel")
    assert permission_keys(bash) == {"yes": "1", "always": "2", "no": "escape"}
    edit = (" Do you want to make this edit to a.py?\n ❯ 1. Yes\n   2. Yes, allow all edits during this session (shift+tab)\n"
            "   3. No, and tell Claude what to do differently (esc)")
    assert permission_keys(edit) == {"yes": "1", "no": "escape"}      # a mode, not a rule: never "always"
    assert permission_keys("❯ 1. Yes\n  2. No") == {}                  # a numbered list, not a prompt
    assert permission_keys("") == {}


def test_the_question_names_the_thing_never_the_whole_command():
    from claudio.agent import described
    cmd = 'cmux new-split right --surface 34E60333-B8F3-450A-94A6-83AB14618643 --command "open https://claudio-vert.vercel.app/"'
    assert described("Bash", {"command": cmd}, None, "") == "run `cmux new-split` for claudio-vert.vercel"
    assert described("Bash", {"command": 'open "https://claudio-vert.vercel.app/"'}, None, "") == "open claudio-vert.vercel"
    assert described("Bash", {"command": "gh pr create -t x"}, "Bash(gh pr create:*)", "to run `gh pr create`") == "run `gh pr create`"
    assert described("Write", {"file_path": "/x/notes.md"}, None, "") == "use Write on notes.md"


def test_an_allow_file_moves_into_settings_once_and_always_adds_to_it(tmp_path, monkeypatch):
    allow, settings = tmp_path / "allow", tmp_path / "settings.json"
    allow.write_text("# GitHub, all of it\nBash(gh:*)\n\nWebFetch  # docs pages\n~/src/other\n")
    monkeypatch.setattr(config, "ALLOW", str(allow))
    monkeypatch.setattr(config, "SETTINGS", str(settings))
    config.migrate_allow()
    assert json.loads(settings.read_text()) == {"permissions": {"allow": ["Bash(gh:*)", "WebFetch"],
                                                                "additionalDirectories": ["~/src/other"]}}
    assert not allow.exists() and (tmp_path / "allow.bak").exists()
    assert config.allowed_dirs() == [os.path.expanduser("~/src/other")]
    config.allow("Bash(gh:*)")                       # already there: once
    config.allow("Bash(curl:*)")
    assert json.loads(settings.read_text())["permissions"]["allow"] == ["Bash(gh:*)", "WebFetch", "Bash(curl:*)"]
    assert config.written == os.path.getmtime(settings)    # claudio's own write: no restart for it
    settings.write_text("{not json")                 # a hand edit gone wrong is kept, never lost
    config.allow("WebFetch")
    assert (tmp_path / "settings.json.bak").read_text() == "{not json"


def test_rule_for_never_offers_claudios_own_folder_for_good(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", str(tmp_path / "settings.json"))
    for path in (config.DIR, os.path.dirname(config.DIR), os.path.expanduser("~")):
        assert config.rule_for("Bash", {"command": f"cat {path}/x"}, str(tmp_path))[0] is None, path


def test_rule_for_never_offers_a_cmux_command_that_runs_any_program(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS", str(tmp_path / "settings.json"))
    for cmd in ("cmux new-split right --surface A --command htop", "cmux new-workspace --name x", "cmux new-surface",
                "cmux workspace create --name x --command htop"):
        assert config.rule_for("Bash", {"command": cmd}, str(tmp_path))[0] is None, cmd


def test_persona_is_the_package_plus_the_users_additions(tmp_path, monkeypatch):
    mine = tmp_path / "prompt.md"
    monkeypatch.setattr(config, "PROMPT", str(mine))
    monkeypatch.setattr(config, "LEARNED", str(tmp_path / "learned.md"))   # none learned: not the real one
    base = open(config.PACKAGED_PROMPT).read()
    mine.write_text(base)                              # a shipped persona copied here, never edited
    config.WARNINGS.clear(); config._persona_file()
    assert mine.read_text() == config.ADDITIONS and config.persona() == base and not config.WARNINGS
    mine.write_text(config.ADDITIONS + "Call me Jean.\n")
    assert config.persona() == base + "\n\nThe user's own additions, which win over anything above:\nCall me Jean."
    mine.write_text(base + "\nAlways answer in French.\n")   # a whole persona, edited: still used, with a warning
    config.WARNINGS.clear(); config._persona_file()
    assert config.persona().endswith("Always answer in French.\n") and config.WARNINGS


def test_learned_rules_end_the_persona_once_each(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROMPT", str(tmp_path / "prompt.md"))
    monkeypatch.setattr(config, "LEARNED", str(tmp_path / "learned.md"))
    assert config.learn("  'seven'  is usually\n'save' ") == "'seven' is usually 'save'"   # one line, however it came
    config.learn("- 'seven' is usually 'save'")                                             # already there: not twice
    config.learn("vbt is the vectorbtpro repo")
    assert (tmp_path / "learned.md").read_text() == "- 'seven' is usually 'save'\n- vbt is the vectorbtpro repo\n"
    assert config.persona().endswith("which win over anything above:\n- 'seven' is usually 'save'\n"
                                     "- vbt is the vectorbtpro repo")
    with pytest.raises(SystemExit):
        config.learn("  ")


def test_unlearn_drops_exactly_one_rule_or_none(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LEARNED", str(tmp_path / "learned.md"))
    with pytest.raises(SystemExit, match="no learned rule"):
        config.unlearn("seven")                                   # no file yet
    for rule in ("'seven' is usually 'save'", "vbt is the vectorbtpro repo", "vbt tests run with pytest"):
        config.learn(rule)
    with pytest.raises(SystemExit, match="several"):
        config.unlearn("vbt")                                     # two match: ask which, drop none
    assert config.unlearn("  SEVEN ") == "'seven' is usually 'save'"
    assert (tmp_path / "learned.md").read_text() == "- vbt is the vectorbtpro repo\n- vbt tests run with pytest\n"
    with pytest.raises(SystemExit):
        config.unlearn(" ")                                       # nothing said: nothing dropped


def test_a_sessions_question_is_read_from_its_pane_and_a_permission_prompt_never_is():
    from claudio.config import question
    single = ("Color?\n\n❯ 1. red\n     Red\n  2. green\n     Green\n  3. blue\n     Blue\n  4. Type something.\n"
              "────────\n  5. Chat about this\n\nEnter to select · Tab/Arrow keys to navigate · Esc to cancel")
    assert question(single) == {"multi": False, "options": {"1": "red", "2": "green", "3": "blue"}, "other": "4", "rows": 4}
    multi = ("Toppings?\n\n❯ 1. [ ] cheese\n         Cheese\n  2. [✔] ham\n  3. [ ] olives\n  4. [ ] Type something\n"
             "     Submit\n────────\n  5. Chat about this\n\nEnter to select · Tab/Arrow keys to navigate · Esc to cancel")
    assert question(multi) == {"multi": True, "options": {"1": "cheese", "2": "ham", "3": "olives"}, "other": "4", "rows": 4}
    prompt = " Do you want to proceed?\n ❯ 1. Yes\n   2. No\n\n Esc to cancel · Tab to amend"
    assert question(prompt) is None and question(prompt + "\nEnter to select") is None   # a permission prompt: never
    assert question("") is None


def test_choose_ticks_reaches_submit_and_refuses_what_isnt_an_option(monkeypatch):
    import subprocess
    from claudio import cli
    multi = ("Toppings?\n\n❯ 1. [ ] cheese\n  2. [ ] ham\n  3. [ ] olives\n  4. [ ] Type something\n     Submit\n"
             "  5. Chat about this\n\nEnter to select")
    at_submit = multi.replace("❯ 1.", "  1.").replace("     Submit", "❯    Submit")
    screens, sent = [multi, at_submit, "Ready to submit your answers?"], []
    def run(cmd, **k):
        if cmd[1] == "read-screen":
            return subprocess.CompletedProcess(cmd, 0, screens.pop(0) if len(screens) > 1 else screens[0], "")
        sent.append(f"{cmd[1]} {cmd[-1]}")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(cli.subprocess, "run", run)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    assert cli.choose("S", "1,3") == "cheese, olives"
    assert sent == ["send 1", "send 3", *["send-key down"] * 4, "send-key enter", "send 1"]   # ticks, Submit, review
    screens[:] = [multi]
    with pytest.raises(SystemExit, match="1 cheese, 2 ham, 3 olives"):
        cli.choose("S", "5")                                  # Chat about this: never


def test_split_put_your_turn_on_the_right_and_narrow_falls_back():
    import io
    from rich.console import Console
    from claudio import ui
    console, log, at = ui.console, ui.log, ui.last_turn["at"]
    ui.log = lambda line: None
    try:
        ui.layout["split"] = True
        ui.console = Console(file=io.StringIO(), width=80)
        ui.you("lights off")
        line = next(l for l in ui.console.file.getvalue().splitlines() if "lights off" in l)
        assert line.rstrip().endswith("lights off ‹") and line.startswith(" " * 60) and "›" not in line   # pushed right
        ui.console = Console(file=io.StringIO(), width=50)
        ui.you("lights off")
        assert "› lights off" in ui.console.file.getvalue()                 # too narrow for a box
        ui.console = Console(file=io.StringIO(), width=80)
        ui.you("lights off ")
        assert "lights off ‹" in ui.console.file.getvalue()                 # one space before the mark, not two
    finally:
        ui.layout["split"] = False
        ui.console, ui.log, ui.last_turn["at"] = console, log, at


def test_choices_show_an_arrow_and_the_number_with_no_rule():
    import io
    from rich.console import Console
    from claudio import ui
    console, log = ui.console, ui.log
    ui.console, ui.log = Console(file=io.StringIO(), width=60), lambda line: None
    try:
        ui.choices("- **1** Yes, this once\n- **2** No")
        assert ui.console.file.getvalue().splitlines() == ["  → 1 Yes, this once", "  → 2 No"]
        ui.console = Console(file=io.StringIO(), width=60)
        ui.choices("- **Option 3** Later\n\n- **4** Never")
        assert ui.console.file.getvalue().splitlines() == ["  → Option 3 Later", "  → 4 Never"]   # no stray **, no blank row
    finally:
        ui.console, ui.log = console, log


def test_intent_reads_the_whole_answer():
    from claudio.agent import intent
    for said, meant in [("please don't", "no"), ("do not", "no"), ("ok wait", "question"), ("okay hold on", "question"),
                        ("go away", "unclear"), ("yes, don't worry", "yes"), ("Yes, I don't mind", "yes"), ("go ahead", "yes"),
                        ("Yes, always, don't ask again", "always"), ("please", "yes"), ("sure", "yes"), ("nope", "no"),
                        ("you don't need to spell it. So yes, you are allowed", "yes")]:
        assert intent(said) == meant, said


def test_allow_copes_with_a_settings_file_of_another_shape(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS", str(settings))
    for odd in ({"permissions": []}, {"permissions": {"allow": "Bash(git:*)"}}, []):
        settings.write_text(json.dumps(odd))
        config.allow("Bash(gh pr view:*)")
        assert json.loads(settings.read_text())["permissions"]["allow"] == ["Bash(gh pr view:*)"], odd
        assert (tmp_path / "settings.json.bak").exists()


def test_project_file_is_found_from_a_subfolder_and_wins_over_a_set(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_FILE", ".claudio.json")
    monkeypatch.setattr(config, "CONF", str(tmp_path / "config.json"))
    (tmp_path / "proj" / "sub").mkdir(parents=True)
    (tmp_path / "proj" / ".claudio.json").write_text('{"style": "brief"}')
    monkeypatch.chdir(tmp_path / "proj" / "sub")
    assert config.project_file() == str(tmp_path / "proj" / ".claudio.json")
    assert config.overridden("style") == ".claudio.json" and config.overridden("model") == ""
    with pytest.raises(SystemExit, match="set by .claudio.json"):
        config.set_key("style", "caveman")
    monkeypatch.setenv("CLAUDIO_MODEL", "opus")
    assert config.overridden("model") == "CLAUDIO_MODEL"


def test_choices_ignore_case_and_save_keeps_unknown_keys(tmp_path, monkeypatch):
    assert config.check("layout", "Split") == ("split", None) and config.check("model", "Sonnet") == ("sonnet", None)
    monkeypatch.setattr(config, "CONF", str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "SECRETS_FILE", str(tmp_path / "secrets.json"))
    monkeypatch.setattr(config, "DIR", str(tmp_path))
    monkeypatch.setattr(config, "PROJECT_FILE", str(tmp_path / "none.json"))
    (tmp_path / "config.json").write_text('{"custom": 1}')
    config.set_key("effort", "high")
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["custom"] == 1 and saved["effort"] == "high"
    assert os.stat(tmp_path / "secrets.json").st_mode & 0o777 == 0o600
