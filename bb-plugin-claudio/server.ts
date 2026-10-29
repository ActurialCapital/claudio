// bb-plugin-claudio: claudio, the voice in front of your sessions, as a panel in bb.
//
// claudio itself (Python: ears, brain, voice, rules) is the same program cmux runs. This backend starts it with
// backend=bb, so its sessions are bb's threads, and reads its view socket: every transcript entry and its state,
// which it passes to the panel (app.tsx). Text typed in the panel goes back as if typed at claudio's keyboard.
import { spawn } from "node:child_process";
import { closeSync, mkdirSync, openSync, writeFileSync } from "node:fs";
import { connect, type Socket } from "node:net";
import { homedir } from "node:os";
import { join } from "node:path";
import { defineRpcContract, type BbPluginApi } from "@get-bb/plugin-sdk";
import { z } from "zod";

const entrySchema = z.object({
  kind: z.string(),        // you, me, block, event, tool, note, warn, rule; or state, or reset (claudio started anew)
  text: z.string(),
  at: z.number(),
  first: z.boolean().optional(),
  what: z.string().optional(),     // an event's kind: done, needs permission, asks you to choose, replied
  asked: z.string().optional(),
});
export type Entry = z.infer<typeof entrySchema>;

// claudio's hello (agent.py hello()): what it offers, so the panel never keeps its own copy of these lists
const helloSchema = z.object({
  kind: z.literal("hello"),
  commands: z.array(z.string()),
  models: z.array(z.string()),
  efforts: z.array(z.string()),
  model: z.string(),
  effort: z.string(),
});
export type Hello = z.infer<typeof helloSchema>;

export const rpcContract = defineRpcContract({
  start: {
    input: z.null(),
    output: z.object({ ok: z.boolean() }),
  },
  feed: {
    input: z.null(),
    output: z.object({
      entries: z.array(entrySchema),
      state: z.string(),
      connected: z.boolean(),
      hello: helloSchema.nullable(),
    }),
  },
  attach: {
    input: z.object({ name: z.string().min(1).max(200), data: z.string().max(14_000_000) }),   // base64, ~10 MB
    output: z.object({ path: z.string() }),
  },
  say: {
    input: z.object({ text: z.string().trim().max(4000) }),   // empty: a bare Enter, it cuts or opens the mic
    output: z.object({ sent: z.boolean() }),
  },
});

/** Realtime channel: the payload is one entry, a state, or a reset; the panel refetches the feed on reconnect. */
const CHANNEL = "claudio";

const configDir = join(process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config"), "claudio");
const VIEW = join(configDir, "view.sock");
const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((done) => {
    const stop = () => (clearTimeout(timer), done());
    const timer = setTimeout(() => (signal.removeEventListener("abort", stop), done()), ms);
    signal.addEventListener("abort", stop, { once: true });
  });

export default async function plugin(bb: BbPluginApi) {
  const settings = bb.settings.define({
    command: {
      type: "string",
      label: "claudio command",
      description: "How to start claudio, arguments too (uv run claudio). Leave empty to only show a claudio you start yourself.",
      default: join(homedir(), ".local", "bin", "claudio"),
    },
  });
  const { command } = await settings.get();

  const entries: Entry[] = [];
  let state = "not running";
  let hello: Hello | null = null;
  let view: Socket | null = null;
  let running: { stop: () => void; exited: Promise<unknown> } | null = null;   // the claudio running now
  let wake: (() => void) | null = null;      // starts it again once it has exited

  // claudio, run under `script` so it has the terminal it expects; its screen goes to bb.log, the panel shows it.
  // script needs a pipe for its input, not node's socket: one that stays open and silent (panel typing goes by view).
  if (command) {
    bb.background.service("claudio", {
      async start(signal) {
        while (!signal.aborted) {
          const log = openSync(join(configDir, "bb.log"), "w");
          // when claudio exits (slash exit, a crash), kill 0 ends the group, tail too, so the exit is seen
          // sh -c "$0" inside script: the command may carry arguments
          const child = spawn("sh", ["-c", 'tail -f /dev/null | { script -q /dev/null /bin/sh -c "$0"; kill 0; }', command], {
            detached: true,                  // its own process group: stopping it stops tail, script and claudio
            env: {
              ...process.env,
              // bb's server may not have the login shell's PATH: claudio needs claude and bb
              PATH: [join(homedir(), ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin", process.env.PATH].join(":"),
              CLAUDIO_BACKEND: "bb", COLUMNS: "100", LINES: "40", TERM: "xterm-256color",
            },
            stdio: ["ignore", log, log],
          });
          closeSync(log);                           // the child has its own copy
          const exited = new Promise<number | null>((done) => child.on("exit", done));
          const stop = () => process.kill(-child.pid!, "SIGINT");
          signal.addEventListener("abort", stop, { once: true });
          running = { stop, exited };
          const code = await exited;
          running = null;
          signal.removeEventListener("abort", stop);
          bb.log.info(`claudio exited (${code})`);
          if (signal.aborted) break;                // bb is stopping the plugin: done, not waiting for a click
          await new Promise<void>((go) => {         // off until the avatar is clicked: never restarts alone
            const quit = () => go();
            wake = () => (signal.removeEventListener("abort", quit), go());
            signal.addEventListener("abort", quit, { once: true });
          });
        }
      },
    });
  }

  // The view socket: what claudio shows, a JSON line each; reconnects whenever claudio (re)starts.
  bb.background.service("view", {
    async start(signal) {
      while (!signal.aborted) {
        await new Promise<void>((done) => {
          const socket = connect(VIEW);
          let buffer = "";
          socket.on("connect", () => {
            view = socket;
            socket.write(JSON.stringify({ push: true }) + "\n");   // bb's interactions come from here: claudio stops polling
            entries.length = 0;              // it sends what came before first
            bb.realtime.publish(CHANNEL, { kind: "reset", text: "", at: Date.now() / 1000 });
          });
          socket.on("data", (chunk) => {
            buffer += chunk.toString();
            let nl: number;
            while ((nl = buffer.indexOf("\n")) >= 0) {
              const line = buffer.slice(0, nl);
              buffer = buffer.slice(nl + 1);
              let raw: unknown;
              try {
                raw = JSON.parse(line);
              } catch {
                continue;
              }
              const greeting = helloSchema.safeParse(raw);
              if (greeting.success) {
                hello = greeting.data;
                bb.realtime.publish(CHANNEL, hello);
                continue;
              }
              const parsed = entrySchema.safeParse(raw);
              if (!parsed.success) continue;
              if (parsed.data.kind === "state") state = parsed.data.text;
              else entries.push(parsed.data), entries.splice(0, entries.length - 500);
              bb.realtime.publish(CHANNEL, parsed.data);
            }
          });
          socket.on("error", () => {});
          const drop = () => socket.destroy();
          socket.on("close", () => {
            signal.removeEventListener("abort", drop);
            if (view === socket) {           // a connection that was up: a failed try (claudio off) says nothing
              view = null;
              state = "not running";
              bb.realtime.publish(CHANNEL, { kind: "state", text: state, at: Date.now() / 1000 });
            }
            done();
          });
          signal.addEventListener("abort", drop, { once: true });
        });
        await sleep(1000, signal);
      }
    },
  });

  // a thread's permission prompt or question, the moment bb records it, to claudio (which polls for them without us)
  bb.events.on("interaction.pending", ({ thread, interaction }) => {
    view?.write(JSON.stringify({ interaction: { ...interaction, threadId: thread.id, title: thread.title ?? thread.id } }) + "\n");
  });

  bb.rpc.register(rpcContract, {
    feed: async () => ({ entries, state, connected: view !== null, hello }),
    // a file from the composer's +: kept where claudio's brain can Read it; the message names its path
    attach: async ({ name, data }) => {
      const dir = join(configDir, "attachments");
      mkdirSync(dir, { recursive: true });
      const path = join(dir, `${Date.now()}-${name.replace(/[^\w.-]+/g, "_")}`);
      writeFileSync(path, Buffer.from(data, "base64"));
      return { path };
    },
    // the avatar: start claudio, or restart it if it is running (it exits, then starts at once)
    start: async () => {
      if (running) {                       // it exits; the service then waits, and wake starts it again
        const { stop, exited } = running;
        stop();
        await exited;                        // bb stopping the plugin meanwhile leaves wake null: nothing starts
      }
      wake?.();
      wake = null;
      return { ok: true };
    },
    say: async ({ text }) => {
      if (!view) return { sent: false };
      view.write(JSON.stringify({ say: text }) + "\n");
      return { sent: true };
    },
  });
}
