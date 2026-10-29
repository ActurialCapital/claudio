# bb-plugin-claudio

claudio, the voice in front of your coding sessions, inside bb. The same claudio that runs in a cmux pane: its ears,
brain, voice and rules are the Python program in this repo; this plugin only starts it and shows it.

- `server.ts`: starts claudio with `backend=bb` (its sessions are bb's threads) under `script`, so it has the
  terminal it expects, with no window of its own; its screen goes to `~/.config/claudio/bb.log`. It reads claudio's
  `view.sock` (every transcript entry and its state) and passes it to the panel on the realtime channel `claudio`.
  RPCs: `feed` (the last 500 entries, the state, the brain's model and effort), `say` (a line typed in the panel,
  as if typed at claudio's keyboard), `start` (start claudio, or restart it), `attach` (a file, saved under
  `~/.config/claudio/attachments` for claudio to read).
- `app.tsx`: a **claudio** tab in every thread's right panel: the conversation, drawn with bb's Markdown, and a
  composer (attach, claudio's commands, its model and reasoning, mute). claudio stops after `/exit` or a crash and
  starts again only when its avatar is clicked.

## Setting

`command`: how to start claudio, arguments too (default `~/.local/bin/claudio`). Empty: show a claudio you start
yourself, in a terminal; the panel attaches to it.

## Develop

```sh
npm install
bb plugin install .
bb plugin dev        # rebuild and reload on save; reload bb's window (⌘R) to see the panel change
bb plugin logs claudio -f
```

Run one claudio at a time: one started here and one in cmux would fight over the mic and its sockets.
