<table border="0" cellpadding="0" cellspacing="0">
<tr>
<td width="200" align="center" valign="middle">
<img src="assets/avatar.png" alt="claudio" width="180">
</td>
<td valign="middle">
<pre>
 ██████╗██╗      █████╗ ██╗   ██╗██████╗ ██╗ ██████╗
██╔════╝██║     ██╔══██╗██║   ██║██╔══██╗██║██╔═══██╗
██║     ██║     ███████║██║   ██║██║  ██║██║██║   ██║
██║     ██║     ██╔══██║██║   ██║██║  ██║██║██║   ██║
╚██████╗███████╗██║  ██║╚██████╔╝██████╔╝██║╚██████╔╝
 ╚═════╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚═╝ ╚═════╝
</pre>
<b>A voice in front of your Claude Code sessions.</b>
</td>
</tr>
</table>

You talk. It answers in a sentence or two, or hands the work to one of your Claude Code sessions and tells you when that session is done, asks something, or needs a permission.

## 🧩 What it stands on

```mermaid
flowchart LR
    mac["🍎 macOS"] --- cmux["🖥️ cmux<br/>terminal & agent inbox"] --- claude["🧠 Claude Code<br/>your plan, your sessions"]
    cmux --- dg["🎧 Deepgram<br/>ears & mouth"]
```

## ⚙️ How it works

```mermaid
flowchart LR
    you(["🗣️ you"]) -->|speech| ears["👂 ears"]
    ears -->|text| brain["🧠 brain"]
    brain -->|text| mouth["👄 mouth"]
    mouth -->|speech| you
    brain -->|"hand off a task"| s1["💻 session"]
    s1 -->|"done · question · permission"| brain
```

- **Discussing?** The brain answers itself, reading the project when it needs facts.
- **Work?** It sends the task to your orchestrator session through cmux's agent inbox and says so.
- **Sessions report back** through three Claude Code hooks. Claudio narrates in plain words, reads out questions and permission prompts; you answer those on the keyboard.

## 🔬 Under the hood

```mermaid
flowchart TB
    subgraph ears ["👂 ears"]
        aec["🎙️ Apple voice-processing unit<br/>echo cancellation, so you can talk over it on speakers"] --> flux["Deepgram Flux STT<br/>eager end of turn · preemptive generation"]
    end
    subgraph brain ["🧠 brain"]
        cp["one long-lived <code>claude -p</code><br/>stream-json · low effort · remembers across runs"]
    end
    subgraph mouth ["👄 mouth"]
        aura["Deepgram Aura TTS<br/>streamed sentence by sentence"]
    end
    subgraph hooks ["🪝 hooks"]
        h["Stop · Notification · AskUserQuestion<br/>→ Unix socket → narration"]
    end
    flux --> cp --> aura
    h --> cp
```

## 🚀 Install

```bash
uv tool install git+https://github.com/ActurialCapital/claudio
claudio          # setup on first run, then it listens
```

Setup asks for your [Deepgram](https://console.deepgram.com) key, lets you pick the orchestrator from your live cmux workspaces, a voice, the brain's model and effort, and installs the hooks. Then, from any project:

```bash
cd ~/code/myproject && claudio
```

## 🎙️ Talking to it

| say | it |
|---|---|
| "what's the sequencer doing?" | reads that pane and sums it up |
| "rebase 44 and run the tests" | hands it to the orchestrator |
| "open a session called Core" | opens a cmux workspace running `claude` |
| "use Sonnet" · "the orchestrator is Core now" | changes a setting, kept for next time |
| "mute" · "unmute" | hears nothing until you unmute |
| talk over it | pauses; a real turn cuts it, an "mm-hm" lets it go on |

Enter cuts a reply. Ctrl-C quits.

## 🎛️ Settings

`~/.config/claudio/config.json`, written by setup and by voice. `prompt.md` beside it is the persona; edit freely.

| key | default | |
|---|---|---|
| `orchestrator` | | cmux workspace that gets tasks by default |
| `model` · `effort` | `default` · `low` | the brain, through your Claude Code login |
| `voice` | `aura-2-orion-en` | any Deepgram Aura-2 voice |
| `ears` | `flux-general-en` | `flux-general-multi` for other languages |
| `eager_eot` · `eot` · `eot_timeout_ms` | `0.3` · `0.7` · `1500` | Flux end-of-turn tuning |
| `barge_in` | `true` | talking over it pauses it |
| `memory` | `true` | resume the last conversation, up to a week old |

`claudio doctor` checks everything and runs one typed turn. `claudio forget` resets the memory. `claudio set <key> <value>` changes one setting.

<details>
<summary>Hands-free picking of multiple-choice answers</summary>

By default claudio reads a session's multiple-choice question aloud and you press the key. To let your spoken answer press it, add `"Bash(cmux send-key:*)"` to the brain's allowed tools in `claudio/agent.py`; the persona already knows the keystrokes. A misheard "yes" can then press keys in your sessions.
</details>

## 📄 License

MIT
