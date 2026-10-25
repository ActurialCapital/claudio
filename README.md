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

<p align="center">
  <img src="assets/demo-v2.svg" alt="a conversation with claudio" width="760">
</p>

You talk. It answers in a sentence or two, or hands the work to one of your Claude Code sessions and tells you when that session is done, asks something, or needs a permission. It is not a reading bot: a separate small brain talks with you, decides whether you are discussing or asking for work, and narrates what your sessions report back in plain words.

## 🚀 Install

```bash
uv tool install git+https://github.com/ActurialCapital/claudio
cd ~/code/myproject && claudio
```

The first run is a short setup: your [Deepgram](https://console.deepgram.com) key, the cmux workspace that is your orchestrator, a voice, the brain's model and effort. It installs the Claude Code hooks for you. `claudio doctor` checks everything afterwards.

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
- 📣 **Sessions report back** through Claude Code hooks. Claudio narrates in plain words, with the request it was for, and reads out questions and permission prompts with the actual command. You answer those on the keyboard.

## 🎙️ Say

| | |
|---|---|
| "what's the sequencer doing?" | reads that pane, sums it up |
| "rebase 44 and run the tests" | hands it to the orchestrator |
| "open a session called Core" | new cmux workspace running `claude` |
| "use Sonnet" · "the orchestrator is Core now" | changes a setting, kept for next time |
| "slash clear" · "slash status" · "slash help" | the slash commands, spoken |
| "slash style brief" · "caveman" · "plain" | how it talks: one sentence, caveman, or plain |
| "slash mute" · "slash unmute" | hears nothing until you unmute |
| "what did we do today?" | reads today's transcript and tells you |
| talk over it | pauses; a real turn cuts it, an "mm-hm" lets it go on |
| type a line | a turn, for when you can't talk |

<kbd>Enter</kbd> cuts a reply · <kbd>Ctrl</kbd>+<kbd>C</kbd> quits · typed `/mute`, `/effort low`, `/clear` work too

## 🖥️ On screen

```
› rebase 44 on main and run the tests
◆ Sending that to Sequencer.
  → cmux agent message

▸ Sequencer  done  ·  for "rebase 44 on main and run the tests"
◆ Rebased, tests pass, nothing to fix.

▃ listening  ·  1.1 s to first word  ·  Sequencer idle
```

- `›` you, `◆` claudio, `▸` a session reporting back with the request it was for, `→` what the brain is reading or running, `⚙` a setting you changed, `·` a note, `!` a warning. Room noise and "mm-hm"s show dim.
- 📊 The state line: a mic level, then listening, thinking, speaking, paused, muted, how long the last reply took to its first word, and what the orchestrator is up to, glanced from its pane every few seconds.
- ⏱️ Each sentence appears as it is spoken, so the transcript keeps time with the voice. Lines wrap at 90 columns however wide the pane.
- 🕰️ A dim rule with the time marks a gap of more than five minutes.
- 📓 Every conversation is kept in `~/.config/claudio/transcripts/YYYY-MM-DD.md`.
- 🔔 When the orchestrator has been waiting on you for a couple of minutes, it says so, once.
- ✍️ Edit `prompt.md` and the brain restarts with the new persona, memory kept.

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

- 🍎 macOS · 🖥️ [cmux](https://cmux.dev) · 🎧 [Deepgram](https://deepgram.com), or [ElevenLabs](https://elevenlabs.io) for the mouth · 🧠 your Claude plan
- The brain starts on Flux's eager end of turn; its audio is held until the final transcript agrees.
- Ears reconnect, the brain restarts if it dies and says so, a mouth that drops mid-reply is reopened, and if the echo canceller stops the plain mic takes over with the reason shown. Errors land in `~/.config/claudio/brain.log` and `helper.log`.
- Every setting is checked for type, choice and range wherever it comes from; a bad value is skipped with a warning and `claudio set` says why.
- 🔇 Echo cancellation needs the Xcode command line tools once, to build a 100-line Swift helper. Without it, barge-in needs headphones.

## 🎛️ Settings

`~/.config/claudio/config.json`, written by setup and by voice; the keys live apart in `secrets.json` (mode 600), which the brain is not allowed to read. `prompt.md` beside it is the persona; edit it freely.

The persona carries rules that keep the voice human, adapted for speech from [humanizer](https://github.com/blader/humanizer)'s list of AI-writing tells: plain words, "is" not "serves as", no forced triads, no inflated significance, at most one hedge, no chatbot wrapper, stop on the last fact. The `style` setting, plain, brief or caveman, switchable mid-session by voice, follows [claudish-to-english](https://github.com/gvzdv/claudish-to-english)'s idea of presets you can flip without touching the prompt.

| key | default | |
|---|---|---|
| `orchestrator` | | cmux workspace that gets tasks by default |
| `model` · `effort` | `default` · `low` | `default`, `sonnet`, `opus`, `haiku` · `low`, `medium`, `high`, through your Claude Code login |
| `voice` | `aura-2-orion-en` | any Deepgram Aura-2 voice |
| `style` | `plain` | `plain`, `brief` (one sentence), `caveman` |
| `ears` | `flux-general-en` | `flux-general-multi` for other languages |
| `eager_eot` · `eot` · `eot_timeout_ms` | `0.3` · `0.7` · `1500` | end-of-turn tuning |
| `barge_in` | `true` | talking over it pauses it |
| `push_to_talk` | `false` | the mic stays closed until you press Enter, for one turn |
| `address_me` | `false` | only turns that start with "claudio" count, for a room with other people |
| `memory` | `true` | resume the last conversation, up to a week old |
| `narrate` | `handed-off` | which sessions' finishes to narrate: `handed-off`, `all`, `none` |
| `mouth` | `deepgram` | or `elevenlabs`: put the key in `secrets.json` as `elevenlabs_api_key` or export `ELEVENLABS_API_KEY`; `elevenlabs_voice` is a voice id |

`claudio doctor` checks everything and runs one typed turn · `claudio forget` resets memory · `claudio set <key> <value>` changes one setting · `CLAUDIO_<KEY>=…` overrides one run

A `.claudio.json` in a project root overrides any of these for that project, `{"orchestrator": "Core"}` being the usual one.

<br>

<p align="center"><sub>MIT · made with Claude Code · voice rules after <a href="https://github.com/blader/humanizer">humanizer</a> · style presets after <a href="https://github.com/gvzdv/claudish-to-english">claudish-to-english</a></sub></p>
