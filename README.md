<p align="center">
  <img src="assets/avatar.png" alt="claudio" width="260">
</p>
<p align="center">
  <img src="assets/wordmark.png" alt="claudio" width="380">
</p>
<p align="center">
  <b>A voice in front of your Claude Code sessions.</b>
</p>
<p align="center">
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-0d9488"></a>
  <img alt="macOS" src="https://img.shields.io/badge/macOS-cmux-0d9488">
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-0d9488">
  <img alt="ears & mouth" src="https://img.shields.io/badge/ears%20%26%20mouth-Deepgram-0d9488">
  <img alt="brain" src="https://img.shields.io/badge/brain-Claude%20Code-0d9488">
</p>

<br>

You talk. It answers in a sentence or two, or hands the work to one of your Claude Code sessions and tells you when that session is done, asks something, or needs a permission.

```
› what's the sequencer doing?
◆ Checking its screen.
◆ Idle, waiting on you. It just merged the six core PRs and main is green.
› rebase 44 on main and run the tests
◆ Sent to Sequencer.
▸ Sequencer  Stop
◆ Rebased, tests pass, nothing to fix.
```

## 🚀 Install

```bash
uv tool install git+https://github.com/ActurialCapital/claudio
cd ~/code/myproject && claudio
```

First run is a short setup: your [Deepgram](https://console.deepgram.com) key, the cmux workspace that is your orchestrator, a voice, the brain's model and effort. It installs the Claude Code hooks for you.

## ⚙️ How it works

```mermaid
flowchart LR
    you(["🗣️ you"]) -->|speech| ears["👂 ears"]
    ears -->|text| brain["🧠 brain"]
    brain -->|text| mouth["👄 mouth"]
    mouth -->|speech| you
    brain <-->|"tasks · answers · questions"| s["💻 your sessions"]
```

- 💬 **Discussing?** The brain answers itself, reading the project when it needs facts.
- 🛠️ **Work?** It sends the task to your orchestrator through cmux's agent inbox and says so.
- 📣 **Sessions report back** through Claude Code hooks. Claudio narrates in plain words and reads out questions and permission prompts; you answer those on the keyboard.

## 🎙️ Say

| | |
|---|---|
| "what's the sequencer doing?" | reads that pane, sums it up |
| "rebase 44 and run the tests" | hands it to the orchestrator |
| "open a session called Core" | new cmux workspace running `claude` |
| "use Sonnet" · "the orchestrator is Core now" | changes a setting, kept for next time |
| "slash clear" · "slash status" · "slash help" | the slash commands, spoken |
| "mute" · "unmute" | hears nothing until you unmute |
| talk over it | pauses; a real turn cuts it, an "mm-hm" lets it go on |

<kbd>Enter</kbd> cuts a reply · <kbd>Ctrl</kbd>+<kbd>C</kbd> quits

## 🔬 Under the hood

```mermaid
flowchart LR
    mic["🎙️ mic"] --> aec["Apple voice-processing unit<br/><sub>echo cancellation: talk over it on speakers</sub>"]
    aec --> flux["Deepgram Flux<br/><sub>streaming STT · eager end of turn</sub>"]
    flux --> cp["claude -p<br/><sub>stream-json · one process · remembers</sub>"]
    cp --> aura["Deepgram Aura<br/><sub>streaming TTS · per sentence</sub>"]
    aura --> aec
    hooks["🪝 Stop · Notification · AskUserQuestion"] -->|unix socket| cp
    cp -->|cmux agent message| sessions["💻 sessions"]
```

- 🍎 macOS · 🖥️ [cmux](https://cmux.dev) · 🎧 [Deepgram](https://deepgram.com) · 🧠 your Claude plan
- The brain starts on Flux's eager end of turn; its audio is held until the final transcript agrees.
- Ears reconnect, the brain restarts if it dies, the mouth retries. Errors in `~/.config/claudio/brain.log`.

## 🎛️ Settings

`~/.config/claudio/config.json`, written by setup and by voice. `prompt.md` beside it is the persona.

| key | default | |
|---|---|---|
| `orchestrator` | | cmux workspace that gets tasks by default |
| `model` · `effort` | `default` · `low` | the brain, through your Claude Code login |
| `voice` | `aura-2-orion-en` | any Deepgram Aura-2 voice |
| `ears` | `flux-general-en` | `flux-general-multi` for other languages |
| `eager_eot` · `eot` · `eot_timeout_ms` | `0.3` · `0.7` · `1500` | end-of-turn tuning |
| `barge_in` | `true` | talking over it pauses it |
| `memory` | `true` | resume the last conversation, up to a week old |

`claudio doctor` checks everything and runs one typed turn · `claudio forget` resets memory · `claudio set <key> <value>`

<details>
<summary>🖐️ Hands-free picking of multiple-choice answers</summary>
<br>
By default claudio reads a session's multiple-choice question aloud and you press the key. To let your spoken answer press it, add <code>"Bash(cmux send-key:*)"</code> to the brain's allowed tools in <code>claudio/agent.py</code>; the persona already knows the keystrokes. A misheard "yes" can then press keys in your sessions.
</details>

<br>

<p align="center"><sub>MIT · made with Claude Code</sub></p>
