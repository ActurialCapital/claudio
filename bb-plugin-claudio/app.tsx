// bb-plugin-claudio: the panel. claudio's transcript as a chat in a tab of the thread's right panel, drawn with bb's
// own Markdown (tables, lists, code as in a thread). It shows what claudio shows in its terminal, and a line typed
// here is a line typed there.
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Markdown,
  definePluginApp,
  experimental_ProviderIcon as ProviderIcon,
  useRealtime,
  useRealtimeConnectionState,
  useRpc,
} from "@get-bb/plugin-sdk/app";
import type { Entry, Hello, rpcContract } from "./server";
import { Icon } from "@/components/ui/icon";
import { cn } from "@/lib/utils";

const CHANNEL = "claudio";            // server.ts publishes on it; only types come from there: it runs in node

// claudio's mark: the site's sun (docs/components/sun-mark.tsx), a sphere lit from the top left, dithered with a 4x4
// Bayer matrix on a 32x32 grid of dots
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];
const CELLS: [number, number][] = [];
for (let y = 0; y < 32; y++) {
  for (let x = 0; x < 32; x++) {
    const nx = (x + 0.5) / 16 - 1;
    const ny = (y + 0.5) / 16 - 1;
    const r2 = nx * nx + ny * ny;
    if (r2 > 1) continue;
    const lit = Math.max(0, (-0.5 * nx - 0.6 * ny + 0.62 * Math.sqrt(1 - r2)) / 0.98);
    if (0.18 + 0.82 * lit > (BAYER[(y % 4) * 4 + (x % 4)] + 0.5) / 16) CELLS.push([x, y]);
  }
}

function Sun({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn("shrink-0 text-[#ea5a0c]", className)}>
      {CELLS.map(([x, y]) => (
        <circle key={`${x}-${y}`} cx={x + 0.5} cy={y + 0.5} r="0.42" fill="currentColor" />
      ))}
    </svg>
  );
}

type Item =
  | { kind: "you"; text: string; at: number }
  | { kind: "me"; text: string; at: number; tools: string[] }
  | { kind: "event"; text: string; what: string; at: number }
  | { kind: "note" | "warn" | "rule"; text: string; at: number };

/** Entries as chat items: claudio's sentences and blocks join its message, as its terminal joins them, and the
 * commands it ran ride in that message as chips. */
function items(entries: Entry[]): Item[] {
  const out: Item[] = [];
  let ran: string[] = [];                          // commands run since the user spoke, before the reply's first words
  for (const e of entries) {
    const last = out[out.length - 1];
    if (e.kind === "me" && !e.first && last?.kind === "me") {
      last.text += e.text.endsWith("\n") ? e.text : e.text + " ";
    } else if (e.kind === "block" && last?.kind === "me") {
      last.text += `\n\n${e.text}\n\n`;
    } else if (e.kind === "tool") {
      if (last?.kind === "me") last.tools.push(e.text);   // mid-reply: in the message it is part of
      else ran.push(e.text);
    } else if (e.kind === "me" || e.kind === "block") {
      out.push({ kind: "me", at: e.at, tools: ran, text: e.kind === "block" ? `${e.text}\n\n` : e.text + (e.text.endsWith("\n") ? "" : " ") });
      ran = [];
    } else if (e.kind === "event") {
      out.push({ kind: "event", at: e.at, what: e.what ?? "", text: `${e.text}${e.asked ? ` · “${e.asked}”` : ""}` });
    } else if (e.kind === "you" || e.kind === "note" || e.kind === "warn" || e.kind === "rule") {
      out.push({ kind: e.kind, at: e.at, text: e.text });
    }
  }
  if (ran.length) out.push({ kind: "me", at: Date.now() / 1000, tools: ran, text: "" });   // working, not spoken yet
  return out;
}

const MAX = 4000;                                  // server.ts say: the longest message it takes
const MAX_FILE = 10_000_000;                       // server.ts attach: about 14 MB once base64, its limit

const clock = (at: number) => new Date(at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

function useClaudio() {
  const rpc = useRpc<typeof rpcContract>();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [state, setState] = useState("…");
  const [hello, setHello] = useState<Hello | null>(null);   // what claudio offers, and its model now
  const refetch = useCallback(() => {
    rpc.call("feed").then((feed) => {
      setEntries(feed.entries);
      setState(feed.state);
      setHello(feed.hello);
    }, () => setState("not running"));
  }, [rpc]);
  useRealtime(CHANNEL, (payload) => {
    const e = payload as Entry;
    if (e.kind === "hello") setHello(payload as Hello);   // on connect, and after any settings change
    else if (e.kind === "state") setState(e.text);
    else if (e.kind === "reset") setEntries([]), refetch();   // claudio started anew: its history, its model
    else {
      setEntries((old) => [...old.slice(-499), e]);
    }
  });
  const connection = useRealtimeConnectionState();
  useEffect(() => {
    if (connection === "connected") refetch();   // on mount, and after a reconnect: signals missed meanwhile are not replayed
  }, [connection, refetch]);
  return { rpc, entries, state, hello };
}

// claudio's brain is Claude: bb's Claude Code artwork for the model chip (an id alone falls back to a generic glyph)
const CLAUDE = {
  id: "claude-code",
  logoUrl: "/api/v1/system/providers/claude-code/logo",
  strings: { iconTint: { light: "#D97757", dark: "#D97757" } },
};

/** A command, mono, its slash in the sun's orange. */
function Slash({ cmd }: { cmd: string }) {
  return (
    <span className="font-mono text-white/85">
      <span className="text-[#ea5a0c]">/</span>
      {cmd.slice(1)}
    </span>
  );
}

/** claudio's commands (from its hello) as a word of their own, never a path such as /Users/x/notes.md. */
const commandsIn = (commands: string[]) =>
  new RegExp(`(?<![\\w/.~-])(/(?:${commands.join("|") || "(?!)"}))(?![\\w/])`);

/** A note from claudio, centred as a small pill: a command it ran (/mute), a setting (⚙ …) or a remark; any
 * /command inside is shown as one. */
function Note({ text, warn, commands }: { text: string; warn: boolean; commands: string[] }) {
  const setting = text.startsWith("⚙ ");
  const body = setting ? text.slice(2) : text;
  const parts = body.split(commandsIn(commands));
  return (
    <div className="flex justify-center py-0.5">
      <span
        className={cn(
          "inline-flex max-w-[92%] items-center gap-1.5 rounded-full px-3 py-1 text-[12px] ring-1 backdrop-blur-sm",
          warn ? "bg-[#d0605f]/12 text-[#ef8a82] ring-[#d0605f]/25" : "bg-white/[0.05] text-white/55 ring-white/[0.07]",
        )}
      >
        {setting ? <Icon name="Settings" className="size-3.5 shrink-0 text-white/40" /> : null}
        <span className="truncate">{parts.map((part, j) => (j % 2 ? <Slash key={j} cmd={part} /> : part))}</span>
      </span>
    </div>
  );
}

/** A crossed-out mic, drawn here: bb has no such icon name and would show its lightning fallback. */
function MicOff() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="size-[18px]" aria-hidden>
      <path d="M12 19v3M15 9.34V5a3 3 0 0 0-5.68-1.33M16.95 16.95A7 7 0 0 1 5 12v-2M18.89 13.23A7 7 0 0 0 19 12v-2M9 9v3a3 3 0 0 0 5.12 2.12" />
      <path d="m2 2 20 20" />
    </svg>
  );
}

/** claudio's own commands, as typed in its terminal: run at once, or (ending in a space) put in the composer to finish. */
const COMMANDS: [string, string][] = [
  ["Status", "/status"],
  ["Help", "/help"],
  ["Clear the conversation", "/clear"],
  ["Stop talking", "/stop"],
  ["Voice…", "/voice "],
  ["Style…", "/style "],
  ["Name…", "/name "],
  ["Restart claudio", "/restart"],
];

/** A popover's close: a click outside box, or Escape, while it is open. */
function useDismiss(box: { current: HTMLElement | null }, open: boolean, setOpen: (open: boolean) => void) {
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [box, open, setOpen]);
}

// how each of claudio's model aliases (its hello lists them) reads today; one not here shows as its alias
const NAMES: Record<string, string> = { opus: "Opus 5.5", sonnet: "Sonnet 5", haiku: "Haiku 4.5", default: "Default" };
const named = (model: string) => NAMES[model] ?? model[0].toUpperCase() + model.slice(1);

/** The brain's model and reasoning, picked as in bb's own composer; a pick is claudio's /model or /effort. */
function ModelPicker({ brain, say }: { brain: Hello; say: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useDismiss(box, open, setOpen);
  const shown = brain.models.map((m) => [m, named(m)]).filter(([, name]) => name.toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-label="claudio's model and reasoning"
        onClick={() => setOpen(!open)}
        className={cn("flex h-9 items-center gap-1.5 rounded-xl px-2.5 text-[13px] text-white/85 transition hover:bg-white/[0.06] active:scale-95",
                      open && "bg-white/[0.08]")}
      >
        <ProviderIcon providerKind="agent" provider={CLAUDE} className="size-4" />
        {named(brain.model)}
        <span className="capitalize text-white/45">{brain.effort}</span>
        <Icon name="ChevronDown" className="size-3.5 text-white/40" />
      </button>
      {open ? (
        <div className="absolute bottom-full left-0 z-10 mb-2 w-[19rem] overflow-hidden rounded-xl border border-white/10 bg-[#202120] text-[13.5px] text-white/85 shadow-[0_8px_30px_rgba(0,0,0,0.5)]">
          <div className="flex items-center gap-1 border-b border-white/[0.07] px-3 pt-2.5">
            <span className="border-b-2 border-white/80 px-1.5 pb-2" title="Claude">
              <ProviderIcon providerKind="agent" provider={CLAUDE} className="size-5" />
            </span>
          </div>
          <label className="flex items-center gap-2.5 border-b border-white/[0.07] px-3.5 py-2.5">
            <Icon name="Search" className="size-4 text-white/45" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search models"
              className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-white/35"
            />
          </label>
          <div className="border-b border-white/[0.07] p-1.5">
            <div className="px-2 pb-1 pt-1.5 text-xs font-medium text-white/50">Model</div>
            {shown.map(([model, name]) => (
              <button
                key={model}
                type="button"
                onClick={() => (setOpen(false), model !== brain.model && say(`/model ${model}`))}
                className="flex w-full items-center rounded-lg px-2 py-1.5 text-left hover:bg-white/[0.07]"
              >
                {name}
                {model === brain.model ? <Icon name="Check" className="ml-auto size-4 text-white/70" /> : null}
              </button>
            ))}
            {shown.length ? null : <div className="px-2 py-1.5 text-white/40">No model matches</div>}
          </div>
          <div className="p-1.5">
            <div className="px-2 pb-1.5 pt-1.5 text-xs font-medium text-white/50">Reasoning</div>
            <div className="flex gap-1 px-1 pb-1">
              {brain.efforts.map((effort) => (
                <button
                  key={effort}
                  type="button"
                  onClick={() => (setOpen(false), effort !== brain.effort && say(`/effort ${effort}`))}
                  className={cn("rounded-lg px-3 py-1.5 capitalize transition hover:bg-white/[0.07]",
                                effort === brain.effort && "bg-white/[0.12] text-white")}
                >
                  {effort}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

type MenuItem = { title: string; hint?: string; run: () => void; divider?: boolean };

/** A button that opens a small list above it; a click outside, or Escape, closes it. */
function Menu({ label, trigger, triggerClass, items }: { label: string; trigger: ReactNode; triggerClass: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useDismiss(box, open, setOpen);
  return (
    <div ref={box} className="relative">
      <button type="button" aria-label={label} title={label} onClick={() => setOpen(!open)} className={cn("transition active:scale-95", triggerClass)}>
        {trigger}
      </button>
      {open ? (
        <div className="absolute bottom-full left-0 z-10 mb-2 min-w-[13rem] rounded-xl border border-white/10 bg-[#202120] p-1 shadow-[0_8px_30px_rgba(0,0,0,0.5)]">
          {items.map((item) => (
            <button
              key={item.title}
              type="button"
              onClick={() => (setOpen(false), item.run())}
              className={cn(
                "flex w-full items-center gap-3 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-white/85 hover:bg-white/[0.07]",
                item.divider && "mt-1 border-t border-white/[0.07] pt-2",
              )}
            >
              {item.title}
              <span className="ml-auto font-mono text-[11.5px] text-white/40">{item.hint}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** The chat, as a tab of a thread's right panel. */
function Panel() {
  const { rpc, entries, state, hello } = useClaudio();
  const [error, setError] = useState("");
  const say = (text: string) =>
    rpc.call("say", { text }).then(
      (r) => (r.sent ? (setError(""), true) : (setError("Not sent: claudio isn't running. Click its avatar to start it."), false)),
      () => (setError(`Not sent: a message can be ${MAX} characters at most.`), false),
    );
  const [typed, setTyped] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });   // braces: it returns a Promise now, which React would take for a cleanup
  }, [entries]);
  const [files, setFiles] = useState<{ name: string; path: string }[]>([]);
  const [uploading, setUploading] = useState(0);
  const picker = useRef<HTMLInputElement>(null);
  const attach = async (list: FileList | null) => {
    const picked = Array.from(list ?? []);
    setUploading((n) => n + picked.length);
    for (const file of picked) {
      try {
        if (file.size > MAX_FILE) throw new Error(`${file.name} is over 10 MB`);
        const data = await new Promise<string>((done, fail) => {
          const reader = new FileReader();
          reader.onload = () => done(String(reader.result).split(",")[1] ?? "");
          reader.onerror = reader.onabort = () => fail(new Error(`${file.name} could not be read`));
          reader.readAsDataURL(file);
        });
        const saved = await rpc.call("attach", { name: file.name, data });
        setFiles((old) => [...old, { name: file.name, path: saved.path }]);
      } catch (e) {
        setError(`Not attached: ${e instanceof Error ? e.message : file.name}.`);
      } finally {
        setUploading((n) => n - 1);
      }
    }
  };
  const send = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = [typed.trim(), ...files.map((f) => `[attached file: ${f.path}]`)].filter(Boolean).join("\n");
    if (uploading) return;
    if (!text) return void say("");                   // a bare Enter, as at claudio's keyboard: it cuts, or opens the mic
    if (await say(text)) setTyped(""), setFiles([]);   // kept when it didn't go, so nothing typed is lost
  };
  const muted = state.startsWith("muted");
  const dot = state.startsWith("listening") ? "bg-[#5fd068]" : state.startsWith("speaking") ? "bg-[#7aa7e3]"
    : state.startsWith("not running") ? "bg-[#d0605f]" : "bg-[#e3b45f] animate-pulse";
  return (
    <aside className="relative flex h-full min-h-0 flex-col bg-[#181918] text-[#e9e9e7]">
      {/* no bar: the avatar and name float on the chat, on a glass pill of their own */}
      <header className="pointer-events-none absolute inset-x-0 top-0 z-10 px-3 pt-3">
        <div className="flex w-fit max-w-full items-center gap-2.5 rounded-full bg-[#1c1d1c]/55 py-1.5 pl-1.5 pr-4 shadow-[0_4px_18px_rgba(0,0,0,0.35),inset_0_1px_0_rgba(255,255,255,0.06)] ring-1 ring-white/[0.08] backdrop-blur-xl backdrop-saturate-150">
        <button
          type="button"
          onClick={() => rpc.call("start").catch(() => {})}
          title={state.startsWith("not running") ? "Start claudio" : "Restart claudio"}
          aria-label={state.startsWith("not running") ? "Start claudio" : "Restart claudio"}
          className="pointer-events-auto relative grid size-10 shrink-0 place-items-center rounded-full bg-[#101110] ring-1 ring-white/10 transition hover:ring-white/30"
        >
          <Sun className="size-7" />
          <span className={cn("absolute bottom-0 right-0 size-2.5 rounded-full ring-2 ring-[#232523]", dot)} />
        </button>
        <span className="min-w-0 leading-tight">
          <span className="block text-[15px] font-semibold tracking-tight">claudio</span>
          <span className="block truncate text-xs text-white/50">{state}</span>
        </span>
        </div>
      </header>
      <div
        className="flex min-h-0 flex-1 flex-col"
        style={{
          backgroundColor: "#151916",
          backgroundImage:
            "radial-gradient(rgba(255,255,255,0.075) 1px, transparent 1.3px), linear-gradient(180deg, #171a17 0%, #142416 60%, #12301a 100%)",
          backgroundSize: "22px 22px, 100% 100%",
        }}
      >
      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3.5 pb-4 pt-[4.75rem] text-[14px] leading-relaxed">
        {items(entries).map((item, i) =>
          item.kind === "you" ? (
            <div
              key={i}
              className="ml-auto w-fit max-w-[85%] rounded-[20px] rounded-br-md bg-gradient-to-b from-[#74c870] to-[#58ad55] px-4 py-2 text-white shadow-[0_1px_2px_rgba(0,0,0,0.35)]"
            >
              {item.text}
              <span className="ml-2 align-baseline text-[11px] text-white/65">{clock(item.at)}</span>
            </div>
          ) : item.kind === "me" ? (
            <div
              key={i}
              className="w-fit max-w-[90%] space-y-2 rounded-[20px] rounded-bl-md bg-[#2a2b2a] px-4 py-2.5 shadow-[0_1px_2px_rgba(0,0,0,0.35)] ring-1 ring-white/[0.04]"
            >
              {item.text.trim() ? <Markdown content={item.text.trim()} className="text-[#e9e9e7]" /> : null}
              {item.tools.map((tool, j) => (
                <code key={j} className="block truncate rounded-xl bg-[#1d1e1d] px-3 py-2 font-mono text-[12.5px] text-white/70">
                  {tool}
                </code>
              ))}
            </div>
          ) : item.kind === "event" ? (
            <div key={i} className="w-fit max-w-[90%] rounded-[20px] bg-[#2a2b2a] px-4 py-3 shadow-[0_1px_2px_rgba(0,0,0,0.35)] ring-1 ring-white/[0.04]">
              <span className="flex items-center gap-2 text-xs text-white/50">
                <Sun className="size-3.5" /> Thread <span className="text-[#7aa7e3]">{item.what}</span> · {clock(item.at)}
              </span>
              <span className="mt-1.5 block text-[15px] font-semibold">{item.text}</span>
            </div>
          ) : (
            item.kind === "rule" ? (   // a divider, as the terminal draws one: a start, a gap of minutes, a fresh start
              <div key={i} className="flex items-center gap-3 py-1 text-[11px] text-white/35">
                <span className="h-px flex-1 bg-white/[0.08]" />
                {item.text}
                <span className="h-px flex-1 bg-white/[0.08]" />
              </div>
            ) : (
              <Note key={i} text={item.text} warn={item.kind === "warn"} commands={hello?.commands ?? []} />
            )
          ),
        )}
        <div ref={end} />
      </div>
      <form onSubmit={send} className="px-3 pb-3 pt-1">
        <div className="rounded-2xl border border-white/[0.09] bg-[#1c1d1c]/95 shadow-[0_4px_20px_rgba(0,0,0,0.35)] backdrop-blur transition-[border-color,box-shadow] duration-200 hover:border-[#ea5a0c]/35 focus-within:border-[#ea5a0c]/60 focus-within:shadow-[0_0_0_3px_rgba(234,90,12,0.14),0_0_26px_-6px_rgba(234,90,12,0.45)]">
          {error ? <div className="px-4 pt-2.5 text-xs text-[#ef8a82]">{error}</div> : null}
          {files.length || uploading ? (
            <div className="flex flex-wrap gap-1.5 px-3 pt-3">
              {uploading ? <span className="rounded-lg bg-white/[0.07] px-2.5 py-1 text-xs text-white/50">attaching {uploading}…</span> : null}
              {files.map((f) => (
                <span key={f.path} className="flex items-center gap-1.5 rounded-lg bg-white/[0.07] py-1 pl-2.5 pr-1 text-xs text-white/80">
                  <Icon name="Paperclip" className="size-3.5 text-white/50" />
                  {f.name}
                  <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles((old) => old.filter((x) => x !== f))}
                          className="grid size-5 place-items-center rounded-md text-white/45 hover:bg-white/10 hover:text-white">
                    <Icon name="X" className="size-3" />
                  </button>
                </span>
              ))}
            </div>
          ) : null}
          <textarea
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
            }}
            rows={2}
            maxLength={MAX}
            placeholder="Talk, or type. / for commands"
            aria-label="Message claudio"
            className="block max-h-40 min-h-[3.25rem] w-full resize-none bg-transparent px-4 pt-3 text-[14px] leading-relaxed text-[#e9e9e7] outline-none [field-sizing:content] placeholder:text-white/35"
          />
          <div className="flex items-center gap-1.5 px-2.5 pb-2.5 pt-1">
            <input ref={picker} type="file" multiple hidden onChange={(e) => (attach(e.target.files), (e.target.value = ""))} />
            <button
              type="button"
              aria-label="Attach files"
              title="Attach files: claudio can read them, images too"
              onClick={() => picker.current?.click()}
              className="grid size-9 place-items-center rounded-xl text-white/55 transition hover:bg-white/[0.06] hover:text-white/85 active:scale-95"
            >
              <Icon name="Plus" className="size-[18px]" />
            </button>
            <Menu
              label="Commands"
              trigger={<span className="font-mono text-[15px] leading-none">/</span>}
              triggerClass="grid size-9 place-items-center rounded-xl text-white/55 hover:bg-white/[0.06] hover:text-white/85"
              items={COMMANDS.filter(([, cmd]) => hello?.commands.includes(cmd.trim().slice(1))).map(([title, cmd]) => ({
                title,
                hint: cmd.trim(),
                run: () => (cmd.endsWith(" ") ? setTyped(cmd) : say(cmd)),
              }))}
            />
            {hello ? <ModelPicker brain={hello} say={say} /> : null}
            <button
              type="button"
              onClick={() => say(muted ? "/unmute" : "/mute")}
              aria-label={muted ? "Unmute claudio" : "Mute claudio"}
              title={muted ? "claudio is muted: it neither listens nor speaks. Click to unmute" : "Mute claudio: it stops listening and speaking"}
              className={cn(
                "ml-auto grid size-9 place-items-center rounded-xl transition active:scale-95",
                muted
                  ? "bg-[#d0605f]/20 text-[#ef8a82] ring-1 ring-[#d0605f]/40 hover:bg-[#d0605f]/30"
                  : "text-white/60 hover:bg-white/[0.06] hover:text-white/90",
              )}
            >
              {muted ? <MicOff /> : <Icon name="Mic" className="size-[18px]" />}
            </button>
            <button
              type="submit"
              aria-label="Send"
              disabled={(!typed.trim() && !files.length) || uploading > 0}
              className="grid size-9 place-items-center rounded-xl bg-[#7aa7e3] text-[#0f1a2b] shadow-[0_1px_3px_rgba(0,0,0,0.4)] transition hover:bg-[#8db5ea] active:scale-95 disabled:bg-white/[0.12] disabled:text-white/45 disabled:shadow-none"
            >
              <Icon name="ArrowUp" className="size-[18px]" />
            </button>
          </div>
        </div>
      </form>
      </div>
    </aside>
  );
}

export default definePluginApp((app) => {
  app.experimental_icons.register({ name: "claudio/sun", component: Sun });
  // a fixed tab in every thread's right panel, beside bb's own: the same chat whichever thread is open
  app.slots.experimental_tab({
    id: "claudio",
    context: { kind: "thread" },
    availability: "fixed",
    title: "claudio",
    icon: "claudio/sun",
    layout: "flush",
    component: Panel,
  });
});
