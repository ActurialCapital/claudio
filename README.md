<p align="center">
  <img src="assets/banner.jpg" alt="claudio: talk, and your sessions work" width="100%">
</p>
<p align="center">
  <b>A voice in front of your coding-agent sessions.</b>
</p>
<p align="center">
  <a href="https://claudio-vert.vercel.app/docs"><img alt="docs" src="https://img.shields.io/badge/docs-claudio--vert.vercel.app-dd7627"></a>
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-dd7627"></a>
  <img alt="macOS" src="https://img.shields.io/badge/os-macOS-dd7627">
  <a href="https://claudio-vert.vercel.app/docs/platforms"><img alt="sessions: bb or cmux" src="https://img.shields.io/badge/sessions-bb%20%C2%B7%20cmux-dd7627"></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-dd7627">
  <img alt="ears & mouth" src="https://img.shields.io/badge/ears%20%26%20mouth-Deepgram-dd7627">
  <img alt="brain" src="https://img.shields.io/badge/brain-Claude%20Code-dd7627">
</p>

<br>

<p align="center">
  <img src="assets/demo-v2.svg" alt="a conversation with claudio" width="760">
</p>

You talk. It answers in a sentence or two, or hands the work to one of your coding-agent sessions and tells you when that session is done, asks something, or needs a permission. It is not a reading bot: a separate small brain talks with you, decides whether you are discussing or asking for work, and narrates what your sessions report back in plain words.

## 🚀 Install

```bash
uv tool install git+https://github.com/ActurialCapital/claudio
cd ~/code/myproject && claudio
```

The first run is a short setup: your [Deepgram](https://console.deepgram.com) key, the session that is your orchestrator, a voice, the brain's model and effort. It installs the Claude Code hooks for you. `claudio doctor` checks everything afterwards. Your sessions live in cmux or bb: see [Where it runs](#-where-it-runs) for the one step that depends on it.

**Full documentation: [claudio-vert.vercel.app/docs](https://claudio-vert.vercel.app/docs)**, from setup to every setting and what to do when something goes wrong.

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
- 🛠️ **Work?** It sends the task to your orchestrator session and says so. With permission checks on, claudio asks “May I send … to Sequencer?” first, every time; a question such as “should I merge?” gets an answer, never a send.
- 📣 **Sessions report back** through Claude Code hooks. Claudio narrates in plain words, with the request it was for, and reads out questions and permission prompts with the actual command. Answer by voice (yes, always, no, or the option you want) or with 1, 2, 3, and claudio answers it in that session.

## 🧩 Where it runs

The core above is the same everywhere. Around it you make two choices ([platforms](https://claudio-vert.vercel.app/docs/platforms)):

- **Where your sessions live**, the `backend` setting: `bb`, where a session is a bb thread running Claude Code, Codex, Cursor or another agent, or `cmux`, the default, where a session is a Claude Code session in a cmux pane.
- **Where you see and type to claudio**: a terminal, any terminal you start `claudio` from, or bb's panel, a **claudio** tab in every bb thread's right panel. Other front ends, such as an editor extension, can connect to the same `~/.config/claudio/view.sock`; nothing in claudio is tied to one.

| platform | what it is | the one extra step | docs |
|---|---|---|---|
| [bb](https://getbb.app) | sessions are bb threads; the panel is an optional front end | `claudio set backend bb`, then `claudio setup`; for the panel, `cd bb-plugin-claudio && npm install && bb plugin install .`, then reload bb's window (⌘R) | [bb](https://claudio-vert.vercel.app/docs/platforms/bb) |
| [cmux](https://cmux.dev) | sessions are cmux panes; claudio runs in a pane of its own | none: `cmux` is the default | [cmux](https://claudio-vert.vercel.app/docs/platforms/cmux) |

Run one claudio at a time: two, whatever their front ends, would fight over the mic. How the bb plugin starts claudio (its `command` setting) and how to work on it: [bb-plugin-claudio](bb-plugin-claudio).

## 🎙️ Say

| | |
|---|---|
| "what's the sequencer doing?" | reads that session, sums it up |
| "rebase 44 and run the tests" | asks, then hands it to the orchestrator |
| "open a session called Core" | a new session: a cmux workspace running `claude`, or a bb thread |
| "use Sonnet" · "the orchestrator is Core now" | changes a setting, kept for next time |
| "slash clear" · "slash status" · "slash help" | the slash commands, spoken |
| "slash quit" · "slash exit" | says bye and quits |
| "slash restart" · "restart yourself" | starts over, same conversation; new code restarts it on its own, once nothing is said |
| "slash voice a British woman" · "deep male" · "calm" | the one voice that fits, or a table of those that do: accent, age, gender, how it sounds; it sets the voice of the mouth that speaks, Aura, ElevenLabs or Kokoro |
| "slash style brief" · "caveman" · "plain" | how it talks: one sentence, caveman, or plain |
| "slash mute" · "slash unmute" | hears nothing until you unmute |
| "slash code colors off" | code blocks as plain text; "on" brings colours back |
| "slash name Roger" | it answers to Roger and calls itself that |
| "slash address me on" · "off" | only turns that start with its name count, for a room with other people |
| "slash barge in off" · "slash push to talk on" · "slash eot 0.8" | any setting, said as it reads; alone, one that is on or off flips |
| "what did we do today?" | reads today's transcript and tells you |
| "write a note: call Michael" | asks Desktop or Documents, then adds it to `notes.md` there, dated |
| "search what Aura-2 costs" | searches the web, says the answer, shows the links |
| "open issue 727 in the browser" | opens it, or a Google search, and says only "Opening it." |
| "yes", "always" or "no" (or press 1, 2, 3), when it asks to allow a command | yes runs it once; always also adds it to `settings.json`; the reply goes on |
| "yes", "always" or "no" (or 1, 2, 3), when a session asks for permission | answers the session's prompt with that option; no declines it; it never picks a mode switch |
| "forget the rule about seven" | drops that learned rule |
| talk over it | pauses; a real turn cuts it, an "mm-hm" lets it go on |
| type a line | a turn, for when you can't talk; what you type shows on the state line |

<kbd>Enter</kbd> cuts a reply · <kbd>Ctrl</kbd>+<kbd>C</kbd> or `/quit` quits · typed `/mute`, `/effort low`, `/clear` work too

## 🖥️ On screen

```
› rebase 44 on main and run the tests
◆ Sending that to Sequencer.

▸ Sequencer  done  ·  for "rebase 44 on main and run the tests"
◆ Rebased, tests pass, nothing to fix.

▃ listening  ·  1.1 s to first word  ·  Sequencer idle
```

- `›` you, `◆` claudio, `▸` a session reporting back with the request it was for, `→` what the brain is reading or running, `⚙` a setting you changed, `·` a note, `!` a warning. Room noise and "mm-hm"s show dim.
- 📊 The state line: a spinner, a still `■` while muted, a mic level, then listening, thinking, speaking, paused, muted, how long the last reply took to its first word, and what the orchestrator is up to, glanced at every few seconds.
- ⏱️ Each sentence appears as it is spoken, its words fading in over its real audio, so the transcript keeps time with the voice. A thought is one paragraph; lines wrap at 90 columns however wide the terminal.
- 📋 When the shape fits, the screen carries more than the voice: bullets for parallel points, each read aloud; a table for a comparison and highlighted code, shown and never read, with a spoken line on what they show; **bold** and `code` for key words.
- 🕰️ A dim rule with the time marks a gap of more than five minutes.
- 📓 Every conversation is kept in `~/.config/claudio/transcripts/YYYY-MM-DD.md`.
- 🔔 When the orchestrator has been waiting on you for a couple of minutes, it says so, once.
- 🧠 Gets better with use: correct it once ("seven" means "save", "vbt" is that repo) and it keeps the rule in `learned.md` for every future conversation.
- ✍️ Add to the persona in `prompt.md` and the brain restarts with it, memory kept; claudio's own rules come from the package, so updates still reach you.
- 🔄 An update to claudio's own code restarts it by itself, once nothing is said, asked or heard: "Restarted with new code.", the conversation kept.

## 🔬 Under the hood

```mermaid
flowchart LR
    mic["🎙️ mic"] --> aec["Apple voice-processing unit<br/><sub>echo cancellation: talk over it on speakers</sub>"]
    aec --> flux["Deepgram Flux<br/><sub>streaming STT · eager end of turn</sub>"]
    flux --> cp["Claude Agent SDK<br/><sub>one claude process · remembers</sub>"]
    cp --> aura["Deepgram Aura<br/><sub>streaming TTS · per sentence</sub>"]
    aura --> aec
    hooks["🪝 Stop · Notification · AskUserQuestion"] -->|unix socket| cp
    cp -->|"tasks, through the sessions' platform"| sessions["💻 sessions<br/><sub>bb threads · cmux panes</sub>"]
```

- 🍎 macOS · 🖥️ sessions in [bb](https://getbb.app) or [cmux](https://cmux.dev) · 🎧 [Deepgram](https://deepgram.com), or [ElevenLabs](https://elevenlabs.io) for the mouth · 🧠 your Claude plan
- The brain starts on Flux's eager end of turn; its audio is held until the final transcript agrees.
- Ears reconnect, the brain restarts if it dies and says so, a mouth that drops mid-reply is reopened, and if the echo canceller stops the plain mic takes over with the reason shown. Errors land in `~/.config/claudio/brain.log` and `helper.log`.
- Every setting is checked for type, choice and range wherever it comes from; a bad value is skipped with a warning and `claudio set` says why.
- 🔇 Echo cancellation needs the Xcode command line tools once, to build a 100-line Swift helper. Without it, barge-in needs headphones.

## 🎛️ Settings

`~/.config/claudio/config.json`, written by setup and by voice; the keys live apart in `secrets.json` (mode 600), which the brain is not allowed to read. `prompt.md` beside it holds your additions to the persona; write freely. The brain reads files, `git`, `gh` issues and pull requests, and runs a few commands of your sessions' platform (`bb` or `cmux`), asking you before each send to a session; for anything more, answer when claudio asks (yes, always or no; the command waits), or add [permission rules](https://code.claude.com/docs/en/settings#permission-settings) to `settings.json`, such as `{"permissions": {"allow": ["Bash(gh:*)"]}}`. It gets none of your Claude Code MCP servers; list any it should have in `mcp.json`. Saving either file restarts the brain with it. To drop every check for one run, start `claudio --dangerously-skip-permissions`, or say "slash permissions skip" and then yes.

The persona carries rules that keep the voice human, adapted for speech from [humanizer](https://github.com/blader/humanizer)'s list of AI-writing tells: plain words, "is" not "serves as", no forced triads, no inflated significance, at most one hedge, no chatbot wrapper, stop on the last fact. The `style` setting, plain, brief or caveman, switchable mid-session by voice, follows [claudish-to-english](https://github.com/gvzdv/claudish-to-english)'s idea of presets you can flip without touching the prompt.

| key | default | |
|---|---|---|
| `orchestrator` | | the session that gets tasks by default: a bb thread's title or a cmux workspace's |
| `model` · `effort` | `default` · `low` | `default`, `sonnet`, `opus`, `haiku` · `low`, `medium`, `high`, through your Claude Code login |
| `voice` | `aura-2-orion-en` | any Deepgram Aura-2 voice; by voice, a name or what it sounds like |
| `style` | `plain` | `plain`, `brief` (one sentence), `caveman` |
| `ears` | `flux-general-en` | `flux-general-multi` for other languages |
| `eager_eot` · `eot` · `eot_timeout_ms` | `0.3` · `0.7` · `1500` | end-of-turn tuning |
| `barge_in` | `true` | talking over it pauses it |
| `push_to_talk` | `false` | the mic stays closed until you press Enter, for one turn |
| `address_me` | `false` | only turns that start with its name count, for a room with other people; the name alone opens the next turn |
| `memory` | `true` | resume the last conversation, up to a week old |
| `narrate` | `handed-off` | which sessions' finishes to narrate: `handed-off`, `all`, `none` |
| `code_colors` | `true` | highlight code blocks in colour; off shows them as plain text |
| `name` | `claudio` | what it answers to and calls itself, one to three words; the ears listen for it |
| `layout` | `inline` | or `split`: your turns on the right, claudio's on the left; plain lines under 50 columns |
| `backend` | `cmux` | where your sessions live: `cmux` (its panes) or `bb` (its threads); bb's panel always runs claudio with `bb`; see [platforms](https://claudio-vert.vercel.app/docs/platforms) |
| `mouth` | `deepgram` | or `elevenlabs`: put the key in `secrets.json` as `elevenlabs_api_key` or export `ELEVENLABS_API_KEY`; `elevenlabs_voice` is a voice id; or `local`, Kokoro on this Mac with no key: `brew install espeak-ng`, install `claudio[local]`, pick `local_voice`, `local_speed`, and `local_model` (`compressed`, the default and about twice as fast, or `full`) |

`claudio doctor` checks everything and runs one typed turn · `claudio forget` resets memory · `claudio learn <rule>` keeps a correction for good (the brain runs it when you correct it, once you say yes) · `claudio unlearn <words>` drops the one learned rule with those words · `claudio set <key> <value>` changes one setting · `CLAUDIO_<KEY>=…` overrides one run

A `.claudio.json` in a project root overrides any of these for that project, `{"orchestrator": "Core"}` being the usual one.

<br>

<p align="center"><sub>MIT · made with Claude Code · voice rules after <a href="https://github.com/blader/humanizer">humanizer</a> · style presets after <a href="https://github.com/gvzdv/claudish-to-english">claudish-to-english</a></sub></p>
