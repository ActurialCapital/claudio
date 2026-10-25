'use client';
import { type RefObject, useEffect, useRef, useState } from 'react';
import { type Line, TranscriptLine, termBar, termFrame } from './term';

// One real exchange, as claudio prints it. `me` lines show sentence by sentence as their audio starts.
type Step =
  | { kind: 'you'; text: string }
  | { kind: 'me'; sentences: string[]; clip: string; ms: number; latency: string }
  | { kind: 'tool'; text: string }
  | { kind: 'event'; who: string; what: string; asked?: string }
  | { kind: 'orch'; text: string }
  | { kind: 'wait'; ms: number };

const SCRIPT: Step[] = [
  { kind: 'orch', text: 'Sequencer working' },
  { kind: 'wait', ms: 700 },
  { kind: 'you', text: "what's the sequencer doing?" },
  { kind: 'tool', text: 'cmux read-screen' },
  { kind: 'me', sentences: ['Sequencer is halfway through the migration tests.', 'Twelve pass, two are still running.'], clip: 'status', ms: 6300, latency: '0.9 s' },
  { kind: 'wait', ms: 900 },
  { kind: 'you', text: 'rebase 44 on main and run the tests' },
  { kind: 'me', sentences: ['Sending that to Sequencer.'], clip: 'handoff', ms: 1800, latency: '1.1 s' },
  { kind: 'tool', text: 'cmux agent message' },
  { kind: 'wait', ms: 2200 },
  { kind: 'orch', text: 'Sequencer idle' },
  { kind: 'event', who: 'Sequencer', what: 'done', asked: 'rebase 44 on main and run the tests' },
  { kind: 'me', sentences: ['Rebased on main, tests pass, nothing to fix.'], clip: 'done', ms: 4000, latency: '1.0 s' },
  { kind: 'wait', ms: 1600 },
  { kind: 'orch', text: 'Sequencer waiting on you' },
  { kind: 'event', who: 'Sequencer', what: 'needs permission' },
  { kind: 'me', sentences: ['Sequencer wants to push the branch to origin.', 'Answer it in its pane.'], clip: 'permission', ms: 5600, latency: '1.2 s' },
];

// the finished transcript: what renders before any script runs, and with reduced motion
const finalOf = (script: Step[]): Line[] => script.flatMap((s): Line[] => {
  if (s.kind === 'you') return [{ kind: 'you', text: s.text }];
  if (s.kind === 'tool') return [{ kind: 'tool', text: s.text }];
  if (s.kind === 'event') return [{ kind: 'event', who: s.who, what: s.what, asked: s.asked }];
  if (s.kind === 'me') return s.sentences.map((text, i) => ({ kind: 'me' as const, text, first: i === 0 }));
  return [];
});
const lastOf = <K extends Step['kind']>(script: Step[], kind: K) =>
  script.findLast((s): s is Extract<Step, { kind: K }> => s.kind === kind);
const NOOP = () => {};

type State = 'listening' | 'thinking' | 'speaking';

// what the replay is doing right now, for a section that follows it (the stages light up in step with the window)
type Cue = 'reset' | 'typing' | 'heard' | 'thinking' | 'speaking' | 'spoken' | 'tool' | 'working' | 'event' | 'end';
const BARS = ' ▁▂▃▄▅▆▇';

// The replay window. The hero's plays the whole exchange and may speak; other sections pass their own script, silent.
export function Broadcast({
  script = SCRIPT,
  sound = false,
  audio,
  onSpeaking = NOOP,
  onToggleSound,
  onCue = NOOP,
  className = '',
}: {
  script?: Step[];
  sound?: boolean;
  audio?: RefObject<HTMLAudioElement | null>;
  onSpeaking?: (on: boolean) => void;
  onToggleSound?: () => void;
  onCue?: (cue: Cue) => void;
  className?: string;
}) {
  const [lines, setLines] = useState<Line[]>(() => finalOf(script));
  const [state, setState] = useState<State>('listening');
  const [latency, setLatency] = useState(() => lastOf(script, 'me')?.latency ?? '1.0 s');
  const [orch, setOrch] = useState(() => lastOf(script, 'orch')?.text ?? 'Sequencer idle');
  const root = useRef<HTMLDivElement>(null);
  const visible = useRef(true); // the loop waits while the window is off screen
  const [level, setLevel] = useState(0);
  // live: the replay has taken over from the finished transcript, so new lines and states ease in
  const [live, setLive] = useState(false);
  const [fading, setFading] = useState(false);
  const screen = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let alive = true;
    const tick = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
    const sleep = tick;
    // a run only starts once the window has been in view for a beat, so a visitor always arrives at a finished
    // transcript, never at a cleared window; off screen it waits between runs, never in the middle of one
    const seen = async (ms: number) => {
      for (let held = 0; alive && held < ms; ) {
        await tick(200);
        held = visible.current ? held + 200 : 0;
      }
    };
    const watch = new IntersectionObserver(([e]) => (visible.current = e.isIntersecting));
    if (root.current) watch.observe(root.current);

    const speak = async (step: Extract<Step, { kind: 'me' }>) => {
      setState('thinking');
      onCue('thinking');
      await sleep(sound ? 350 : 700);
      if (!alive) return;
      setLatency(step.latency);
      setState('speaking');
      onCue('speaking');
      onSpeaking(true);
      const total = step.sentences.join(' ').length;
      let done: Promise<void> = sleep(step.ms);
      const el = audio?.current;
      if (sound && el) {
        el.src = `/audio/${step.clip}.mp3`;
        done = new Promise<void>((r) => {
          el.onended = () => r();
          el.onerror = () => r();
          el.play().catch(() => r());
        });
      }
      // each sentence prints when its audio starts, as in the real transcript
      const shown = (async () => {
        for (let i = 0; i < step.sentences.length; i++) {
          if (!alive) return;
          const text = step.sentences[i];
          setLines((l) => [...l, { kind: 'me', text, first: i === 0 }]);
          if (i < step.sentences.length - 1) await sleep((step.ms * text.length) / total);
        }
      })();
      await Promise.all([done, shown]);
      onSpeaking(false);
      onCue('spoken');
      setState('listening');
    };

    const run = async () => {
      while (alive) {
        await seen(2400); // the finished transcript first, so the window never opens empty
        // the old transcript fades out before the window clears, then the next run fills it again
        setFading(true);
        await sleep(320);
        if (!alive) return;
        setLive(true);
        setLines([]);
        setFading(false);
        setOrch(script.find((s) => s.kind === 'orch')?.text ?? 'Sequencer working');
        setState('listening');
        onCue('reset');
        for (const step of script) {
          if (!alive) return;
          if (step.kind === 'wait') await sleep(step.ms);
          else if (step.kind === 'orch') {
            setOrch(step.text);
            if (step.text.endsWith('working')) onCue('working');
          } else if (step.kind === 'tool') {
            onCue('tool');
            setLines((l) => [...l, { kind: 'tool', text: step.text }]);
            await sleep(500);
          } else if (step.kind === 'event') {
            onCue('event');
            setLines((l) => [...l, { kind: 'event', who: step.who, what: step.what, asked: step.asked }]);
            await sleep(500);
          } else if (step.kind === 'you') {
            onCue('typing');
            setLines((l) => [...l, { kind: 'you', text: '', typing: true }]);
            for (let i = 1; i <= step.text.length && alive; i++) {
              const text = step.text.slice(0, i);
              setLines((l) => [...l.slice(0, -1), { kind: 'you', text, typing: true }]);
              await sleep(38 + Math.random() * 40);
            }
            setLines((l) => [...l.slice(0, -1), { kind: 'you', text: step.text }]);
            onCue('heard');
          } else if (step.kind === 'me') await speak(step);
        }
        onCue('end');
        await sleep(4500);
      }
    };
    run();
    return () => {
      alive = false;
      watch.disconnect();
      audio?.current?.pause();
      onSpeaking(false);
    };
  }, [script, sound, audio, onSpeaking, onCue]);

  // the mic meter: a quick rise while you talk, idle flicker otherwise; still with reduced motion
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const last = lines.at(-1);
    const typing = last?.kind === 'you' && last.typing;
    const id = setInterval(() => visible.current && setLevel(typing ? 4 + Math.floor(Math.random() * 4) : Math.floor(Math.random() * 2)), 120);
    return () => clearInterval(id);
  }, [lines]);

  useEffect(() => {
    screen.current?.scrollTo({ top: screen.current.scrollHeight, behavior: live ? 'smooth' : 'auto' });
  }, [lines, live]);

  return (
    <div ref={root} data-ui data-live={live || undefined} className={`replay ${termFrame} ${className}`}>
      <samp className={termBar}> {/* taste-skill-ignore: the window's own state-line edge */}
        <span className="w-3 text-(--t-you)">{BARS[level]}</span>
        <span className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-pre">
          <span key={state} className={`state-in inline-block ${state === 'speaking' ? 'text-(--t-me)' : ''}`}>
            {state}
          </span>
          {'  ·  '}
          <span key={latency} className="state-in inline-block">{latency}</span>
          {' to first word  ·  '}
          <span key={orch} className="state-in inline-block">{orch}</span>
        </span>
        <span className="hidden sm:inline">~/code/myproject</span>
        {/* the replay's voice: off by default, one small control on the window itself */}
        {onToggleSound && <button
          type="button"
          onClick={onToggleSound}
          aria-pressed={sound}
          aria-label={sound ? 'Mute the replay' : 'Play the replay with sound'}
          title={sound ? 'Mute the replay' : 'Hear the replay'}
          className={`press -my-1 -mr-1.5 grid size-7 shrink-0 place-items-center rounded-md transition-colors hover:bg-(--t-hover) hover:text-(--t-fg) focus-visible:outline-2 focus-visible:outline-(--t-you) ${sound ? 'text-(--t-me)' : ''}`}
        >
          <SpeakerIcon on={sound} />
        </button>}
      </samp>
      <samp
        ref={screen}
        className={`block min-h-0 flex-1 overflow-y-auto px-5 py-4 font-mono text-[13px] leading-[1.7] transition-opacity duration-300 ease-out [scrollbar-width:none] ${fading ? 'opacity-0' : ''}`} /* taste-skill-ignore: real terminal output in a data-ui fragment */
      >
        {lines.map((l, i) => (
          <TranscriptLine key={i} line={l} fresh={live} />
        ))}
      </samp>
    </div>
  );
}

function SpeakerIcon({ on }: { on: boolean }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M11 5 6 9H2v6h4l5 4V5z" fill="currentColor" />
      {on ? (
        <>
          <path d="M15.5 8.5a5 5 0 0 1 0 7" />
          <path d="M19 5a10 10 0 0 1 0 14" />
        </>
      ) : (
        <path d="m22 9-6 6M16 9l6 6" />
      )}
    </svg>
  );
}
