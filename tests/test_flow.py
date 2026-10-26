"""The whole reply flow, end to end: tests/flow.py runs the real agent.main() with fakes only at the edges, one
process per scenario, all at once (about 11 s). Each test reads what its scenario logged."""
import os, re, subprocess, sys

import pytest

SCENARIOS = ("mouth-gone", "race-event", "resumed", "markdown", "allow-yes", "allow-no", "voice-banana", "skip",
             "allow-early", "handoff-new")


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


def test_a_refused_command_is_allowed_by_saying_yes_and_retried(runs):
    lines, home = runs["allow-yes"]
    assert any("not allowed to run" in line for line in lines if line.startswith("SAY"))
    assert "NOTE allowed Bash(gh pr create:*)" in lines
    assert (home / "allow").read_text() == "Bash(gh pr create:*)\n"
    assert sum(line == "BRAIN 'open a PR'" for line in lines) == 2     # once refused, once allowed


def test_no_allows_nothing(runs):
    lines, home = runs["allow-no"]
    assert "NOTE not allowed: Bash(gh pr create:*)" in lines
    assert not (home / "allow").exists()


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
    assert not any(line.startswith("NOTE allowed") for line in lines)
    assert not (home / "allow").exists()


def test_a_session_opened_after_start_is_still_heard_when_it_finishes(runs):
    lines, _ = runs["handoff-new"]
    assert "EVENT Login Stop" in lines
    assert any(line.startswith("BRAIN '[event] Login finished a turn on your request") for line in lines)
