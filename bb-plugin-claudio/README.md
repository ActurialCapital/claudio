# bb-plugin-claudio

claudio, the voice in front of your coding-agent sessions, as a front end inside bb. The same claudio that runs in a
terminal: its ears, brain, voice and rules are the Python program in this repo; this plugin only starts it and shows
it, with bb threads as its sessions. The user guide: [bb](https://claudio-vert.vercel.app/docs/platforms/bb).
Another front end can be built the same way, on claudio's `view.sock`:
[front ends](https://claudio-vert.vercel.app/docs/reference/front-ends).

- `server.ts`: starts claudio with `backend=bb` (its sessions are bb's threads) under `script`, so it has the
  terminal it expects, with no window of its own; its screen goes to `~/.config/claudio/bb.log`. It reads claudio's
  `view.sock` (every transcript entry and its state) and passes it to the panel on the realtime channel `claudio`.
  It pushes a thread's permission prompt or question to claudio the moment bb records it (`interaction.pending`), so
  claudio stops polling bb for them while the plugin is connected.
  RPCs: `feed` (the last 500 entries, the state, and claudio's hello: its commands, models, efforts and current model), `say` (a line typed in the panel,
  as if typed at claudio's keyboard), `start` (start claudio, or restart it), `attach` (a file, saved under
  `~/.config/claudio/attachments` for claudio to read).
- `app.tsx`: a **claudio** tab in every thread's right panel: the conversation, drawn with bb's Markdown, and a
  composer (attach, claudio's commands, its model and reasoning, mute). claudio stops after `/exit` or a crash and
  starts again only when its avatar is clicked.

## Setting

`command`: how to start claudio, arguments too, such as `uv run claudio` (default `~/.local/bin/claudio`); it runs
with `CLAUDIO_BACKEND=bb`. Empty: show a claudio you start yourself, in a terminal with `backend` set to `bb`; the
panel attaches to it. claudio must be set up once in a terminal first: the plugin can't answer setup's questions.

## Develop

```sh
npm install
bb plugin install .
bb plugin dev        # rebuild and reload on save; reload bb's window (⌘R) to see the panel change
bb plugin logs claudio -f
```

Run one claudio at a time: one started here and one in a terminal would fight over the mic and its sockets. To stop it:
`/exit` (off until the avatar is clicked), or `bb plugin disable claudio`. The plugin's own log is
`bb plugin logs claudio`; claudio's screen is in `~/.config/claudio/bb.log`.
