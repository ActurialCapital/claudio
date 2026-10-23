# claudio

A voice in front of your Claude Code sessions. You talk in a terminal; it answers, in a sentence or two, and when you ask for work it hands the task to one of your Claude Code sessions and tells you when that session is done, asks something, or wants a permission.

Not a reading bot: a separate small brain talks with you, decides whether you're discussing or asking for work, and narrates what your sessions report back in plain words.

**Scope, plainly:** macOS, [cmux](https://cmux.dev) as the terminal, [Deepgram](https://deepgram.com) for ears and mouth, a Claude plan for the brain. Other terminals and other speech engines are not supported yet. Not related to `ctoth/claudio`, which plays sound effects on hooks.

## Install

```bash
uv tool install git+https://github.com/ActurialCapital/claudio
claudio          # first run: setup, then it listens
```

Setup checks for `claude` and cmux, asks for your Deepgram key and tests it, lets you pick which cmux workspace is the orchestrator (the session that gets your tasks by default), a voice, the brain's model and effort, and whether talking over it cuts it. Then it adds three hooks to `~/.claude/settings.json`. Sessions started after that report back.

Then, from a project directory:

```bash
cd ~/code/myproject && claudio
```

## Talking to it

- Ask a question: it answers itself, reading the project if it needs to.
- Ask for work: it sends the task to the orchestrator through cmux's agent inbox (`cmux agent message`), and says so. Name another session to send it there instead.
- "What is the sequencer doing?" reads that pane and sums it up.
- "Open a session called Core" opens a new cmux workspace running `claude`. "Open a terminal next to it" splits a pane.
- When a session you handed work to finishes a turn, claudio tells you what it did. When a session asks a permission or a multiple-choice question, claudio reads it out; you answer on that session's keyboard.
- "Use Sonnet", "the orchestrator is Core now", "stop interrupting me": settings changed by voice, kept for next time.
- Talking over it cuts it, on speakers too: on a Mac with the Xcode command line tools, claudio builds a small helper on first run that runs Apple's voice-processing audio unit (the FaceTime echo canceller) for mic and speaker. Without it, barge-in needs headphones. Enter also cuts. Ctrl-C quits.

## Settings

`~/.config/claudio/config.json`, written by setup and by voice. `~/.config/claudio/prompt.md` is the persona; edit it freely, it's read at each start.

| key | default | |
|---|---|---|
| `orchestrator` | | cmux workspace title that gets tasks by default |
| `model` | `default` | brain: `default`, `sonnet`, `opus`, `haiku` (your Claude Code login) |
| `effort` | `low` | brain effort; low is the quick conversational one |
| `voice` | `aura-2-orion-en` | any Deepgram Aura-2 voice |
| `ears` | `flux-general-en` | Deepgram Flux model; `flux-general-multi` for other languages |
| `eager_eot` / `eot` | `0.3` / `0.7` | Flux end-of-turn thresholds |
| `barge_in` | `true` | talking over it cuts it (set false on speakers without the echo canceller) |
| `deepgram_api_key` | | or export `DEEPGRAM_API_KEY` |

`CLAUDIO_<KEY>=value` overrides one run. `CLAUDIO_TEXT="..."` runs one typed turn without the mic, to check the pipeline.

## Hands-free picking

By default claudio reads multiple-choice questions and permission prompts aloud and you press the key. If you want your spoken answer to pick the option for you, add `"Bash(cmux send-key:*)"` to the brain's allowed tools in `claudio/agent.py` (the prompt already explains the keystrokes). Then a misheard "yes" can press keys in your sessions; your call.

## How it works

- Ears: Deepgram Flux over one websocket. It decides the end of your turn itself, and fires an eager signal first; the brain starts on the eager text and the audio is held until the final transcript confirms it.
- Brain: one long-lived `claude -p` in stream-json mode, started in your project directory with your hooks switched off, read-only tools plus a few cmux commands. An interruption sends Claude Code's own interrupt.
- Mouth: Deepgram Aura over a websocket per reply, flushed at each sentence end, so the first sentence plays while the rest is written.
- Audio: `audio.swift`, compiled once into `~/.config/claudio/bin/`, is Apple's voice-processing I/O unit as a pipe: speech in on stdin, echo-cancelled mic out on stdout, both 24 kHz. Measured on a MacBook Pro: the speaker's own voice drops about 17 dB in the mic. Falls back to PortAudio without it.
- Sessions report back through three Claude Code hooks (Stop, Notification, PreToolUse on AskUserQuestion) that post to a Unix socket when claudio is running and exit at once otherwise.

## License

MIT
