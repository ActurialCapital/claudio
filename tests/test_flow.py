"""The whole reply flow, end to end: tests/flow.py runs the real agent.main() with fakes only at the edges, one
process per scenario, all at once (about 11 s). Each test reads what its scenario logged."""
import json, os, re, subprocess, sys

import pytest

SCENARIOS = ("mouth-gone", "race-event", "resumed", "markdown", "allow-yes", "allow-always", "allow-other", "allow-unclear", "allow-cut",
             "allow-eager", "allow-no", "voice-banana", "skip", "allow-early", "handoff-new", "loose-table")


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    """{scenario: (its log lines, its config dir)}, every scenario run in parallel."""
    try:
        import sounddevice  # noqa: F401  (claudio imports it; on a runner without PortAudio it can't load)
    except (ImportError, OSError) as e:
        pytest.skip(f"no audio library here: {e}")
    here = os.path.dirname(os.path.abspath(__file__))
    started = {}
    for sc in SCENARIOS:
        home = tmp_path_factory.mktemp(sc)
        started[sc] = (subprocess.Popen([sys.executable, os.path.join(here, "flow.py"), sc], stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        env={**os.environ, "XDG_CONFIG_HOME": str(home)}), home)
    done = {}
    for sc, (proc, home) in started.items():
        out = proc.communicate(timeout=60)[0]
        assert "Traceback" not in out, f"{sc} crashed:\n{out[-2000:]}"
        done[sc] = ([re.sub(r"^\s*[\d.]+\s+", "", line) for line in out.splitlines() if line.strip()], home / "claudio")
    return done


def first(lines, prefix):
    return next(i for i, line in enumerate(lines) if line.startswith(prefix))


def test_it_greets_once_it_is_listening(runs):
    lines, _ = runs["resumed"]
    assert lines[first(lines, "ME")] == "ME 'Hi, how can I help you?\\n'"


def test_kept_talking_drops_the_guess_and_the_final_turn_is_answered(runs):
    lines, _ = runs["resumed"]                # eager guess, TurnResumed, then the same words final
    assert "NOTE resumed" not in lines
    assert first(lines, "YOU 'what is the time'") < first(lines, "ME 'It is noon. '")


def test_with_no_mouth_your_line_comes_first_and_the_brain_answers_once(runs):
    lines, _ = runs["mouth-gone"]
    assert first(lines, "YOU 'what time is it'") < first(lines, "ME 'It is noon. '")
    assert sum(line == "BRAIN 'what time is it'" for line in lines) == 1


def test_talking_over_a_session_report_replaces_it_once(runs):
    lines, _ = runs["race-event"]
    assert sum(line == "NOTE replaced" for line in lines) <= 1
    assert any(line.startswith("YOU 'wait stop and tell me the weather'") for line in lines)


def test_tables_and_code_are_shown_never_said_and_in_place(runs):
    lines, _ = runs["markdown"]
    said = " ".join(line for line in lines if line.startswith("SAY"))
    assert "|" not in said and "```" not in said and "**" not in said and "`" not in said
    table, code = first(lines, "BLOCK '| Engine"), first(lines, "BLOCK '```python")
    assert first(lines, "ME 'Here is how") < table < first(lines, "ME '**Kokoro** wins")
    assert first(lines, "ME 'Here is the call") < code < first(lines, "ME 'It turns text into audio.'")


def test_a_yes_inside_the_reply_lets_the_waiting_command_run_once(runs):
    lines, home = runs["allow-yes"]
    asked = first(lines, "ME 'May I run `gh pr create`?")
    assert "BLOCK '- Yes, this once\\n- Always\\n- No'" in lines                   # the answers: bullets, on screen
    assert first(lines, "ME 'Let me open it.") < asked < first(lines, "YOU 'yes'") < first(lines, "PERM allow")
    assert "NOTE allowed once: Bash(gh pr create:*)" in lines
    assert first(lines, "PERM allow") < first(lines, "ME 'Opened it.'")         # the same reply goes on
    assert sum(line.startswith("BRAIN") for line in lines) == 2                 # the warm-up and the request: no retry
    assert "NOTE stopped" not in lines and not (home / "settings.json").exists()


def test_always_allows_it_now_and_from_now_on_without_a_restart(runs):
    lines, home = runs["allow-always"]
    perm = lines[first(lines, "PERM allow")]
    assert json.loads(perm.split(" ", 2)[2]) == [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": "gh pr create:*"}],
                                                  "behavior": "allow", "destination": "session"}]
    assert json.loads((home / "settings.json").read_text()) == {"permissions": {"allow": ["Bash(gh pr create:*)"]}}
    assert sum(line.startswith("START") for line in lines) == 1                 # claudio's own write: no restart


def test_a_question_from_an_early_start_is_asked_once_the_turn_is_final(runs):
    lines, _ = runs["allow-eager"]
    assert first(lines, "YOU 'open a PR'") < first(lines, "ME 'May I") < first(lines, "YOU 'yes'") < first(lines, "PERM allow")


def test_no_allows_nothing(runs):
    lines, home = runs["allow-no"]
    assert "NOTE not allowed: Bash(gh pr create:*)" in lines and first(lines, "PERM deny") < first(lines, "ME 'Okay.'")
    assert not (home / "settings.json").exists()


def test_a_question_back_reaches_the_brain_and_a_yes_after_runs_it_unasked(runs):
    lines, _ = runs["allow-other"]
    assert any(line.startswith("PERM deny") and "what would that do" in line for line in lines)
    assert first(lines, "PERM deny") < first(lines, "YOU 'ok do it'") < first(lines, "PERM allow")
    assert sum(line.startswith("ME 'May I") for line in lines) == 1                # asked once, not twice


def test_an_unclear_answer_is_asked_again_by_claudio_not_the_brain(runs):
    lines, _ = runs["allow-unclear"]
    again = first(lines, "ME 'Sorry, yes or no?")
    assert first(lines, "YOU 'I said I said'") < again < first(lines, "PERM allow")
    assert not any(line.startswith("PERM deny") for line in lines)


def test_a_cut_while_asking_refuses_the_waiting_command(runs):
    lines, _ = runs["allow-cut"]
    assert "NOTE stopped" in lines and first(lines, "NOTE stopped") < first(lines, "PERM deny")


def test_an_unknown_voice_lists_them_on_screen_and_saves_nothing(runs):
    lines, home = runs["voice-banana"]
    said = [line for line in lines if line.startswith("SAY")]
    assert said[-1] == "SAY 'Banana is not recognised as a voice. The voices are as follows:\\n'"
    assert "- zeus" in lines[first(lines, "BLOCK")]
    assert not (home / "config.json").exists()


def test_permission_checks_go_off_only_after_a_yes_and_come_back(runs):
    lines, home = runs["skip"]
    starts = [line for line in lines if line.startswith("START")]
    assert starts == ["START checks on", "START no permission checks", "START checks on"]
    asked, said_yes = first(lines, "SAY 'Skip every permission check"), first(lines, "YOU 'yes'")
    assert asked < said_yes < lines.index("START no permission checks")
    assert not (home / "config.json").exists()           # never saved


def test_an_okay_to_the_reply_before_the_question_allows_nothing(runs):
    lines, home = runs["allow-early"]
    assert first(lines, "YOU 'okay'") < first(lines, "ME 'May I")
    assert not any(line.startswith(("NOTE allowed", "PERM")) for line in lines)
    assert not (home / "settings.json").exists()


def test_a_session_opened_after_start_is_still_heard_when_it_finishes(runs):
    lines, _ = runs["handoff-new"]
    assert "EVENT Login Stop" in lines
    assert any(line.startswith("BRAIN '[event] Login finished a turn on your request") for line in lines)


def test_a_table_without_outer_bars_is_shown_not_read(runs):
    lines, _ = runs["loose-table"]
    said = [line for line in lines if line.startswith("SAY") and "Hi, how can" not in line]
    assert said == ["SAY 'Here it is.\\n'"]
    assert first(lines, "BLOCK 'Change | Type") > first(lines, "ME 'Here it is.")
