'use client';
import Link from 'next/link';
import { useEffect, useId, useRef, useState } from 'react';
import { heading, intro } from './styles';
import { type Line, Term, TranscriptLine } from './term';
import { useInView, useStill } from './use-landing';

// Six things you might say, and what claudio prints for each: the lines are the formats from "On screen".
const SAID: { said: string; then: string; lines: Line[] }[] = [
  {
    said: 'what’s the sequencer doing?',
    then: 'It reads that pane and sums it up.',
    lines: [
      { kind: 'tool', text: 'cmux read-screen' },
      { kind: 'me', text: 'Sequencer is halfway through the migration tests.', first: true },
      { kind: 'me', text: 'Twelve pass, two are still running.', first: false },
    ],
  },
  {
    said: 'rebase 44 and run the tests',
    then: 'It hands the work to the orchestrator.',
    lines: [
      { kind: 'me', text: 'Sending that to Sequencer.', first: true },
      { kind: 'tool', text: 'cmux agent message' },
    ],
  },
  {
    said: 'open a session called Core',
    then: 'A new cmux workspace, running claude in the project.',
    lines: [{ kind: 'tool', text: 'new cmux workspace Core, running claude' }],
  },
  {
    said: 'use Sonnet',
    then: 'It switches the brain, and keeps it for next time.',
    lines: [
      { kind: 'tool', text: 'claudio set model sonnet' },
      { kind: 'set', key: 'model', value: 'sonnet' },
    ],
  },
  {
    said: 'slash style caveman',
    then: 'Six words a sentence, at most.',
    lines: [{ kind: 'set', key: 'style', value: 'caveman' }],
  },
  {
    said: 'what did we do today?',
    then: 'It reads today’s transcript back, in order.',
    lines: [{ kind: 'tool', text: 'transcripts/2026-10-25.md' }],
  },
];

const WORD = 230; // one spoken word
const HOLD = 2800; // how long a finished exchange stays before the next phrase is said
const BARS = 44;

type Voice = 'you' | 'me' | null;

// A voice level drawn as bars: it moves while someone speaks (you in cyan, claudio in teal) and settles flat
// in between. Driven straight on the bars' transforms, paused off screen, still with reduced motion.
function Level({ voice, live }: { voice: Voice; live: boolean }) {
  const bars = useRef<(HTMLSpanElement | null)[]>([]);
  useEffect(() => {
    if (!live) return;
    let raf = 0;
    let t = 0;
    const cur = new Array(BARS).fill(0.12);
    const tick = () => {
      t += 1;
      for (let i = 0; i < BARS; i++) {
        // a voice-like envelope: syllables come and go along the bar row, with a little grain
        const syll = Math.max(0, Math.sin(t * 0.11 + i * 0.42) * Math.sin(t * 0.047 + i * 0.13));
        const want = voice ? 0.16 + 0.84 * Math.min(1, syll * 1.6 + Math.random() * 0.25) : 0.1 + 0.12 * Math.abs(Math.sin(t * 0.018 + i * 0.3));
        cur[i] += (want - cur[i]) * (voice ? 0.35 : 0.12);
        const el = bars.current[i];
        if (el) el.style.transform = `scaleY(${cur[i].toFixed(3)})`;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [voice, live]);
  return (
    <div aria-hidden className={`level ${voice === 'me' ? 'is-me' : voice ? '' : 'is-idle'}`}>
      {Array.from({ length: BARS }, (_, i) => (
        <span
          key={i}
          ref={(el) => {
            bars.current[i] = el;
          }}
          style={{ transform: `scaleY(${(0.18 + 0.5 * Math.abs(Math.sin(i * 0.5)) * Math.abs(Math.sin(i * 0.13))).toFixed(3)})` }}
        />
      ))}
    </div>
  );
}

export function Say() {
  const [at, setAt] = useState(0);
  // where the exchange is: words spoken so far, then claudio's lines shown so far, then the note
  const [spoken, setSpoken] = useState(Infinity);
  const [shown, setShown] = useState(Infinity);
  const [moved, setMoved] = useState(false); // the visitor has seen it change, so new parts ease in
  const [held, setHeld] = useState(false); // a pointer or the keyboard is in the section
  const id = useId();
  const root = useRef<HTMLElement>(null);
  const seen = useInView(root);
  const still = useStill();
  const pick = SAID[at];
  const words = pick.said.split(' ');
  const total = pick.lines.length + 1; // claudio's lines, then the note
  const done = spoken >= words.length && shown >= total;

  const choose = (i: number) => {
    if (i === at) return;
    setMoved(true);
    setAt(i);
  };

  // the phrase is said word by word, then the window answers line by line
  useEffect(() => {
    if (still || !moved) {
      setSpoken(Infinity);
      setShown(Infinity);
      return;
    }
    const n = SAID[at].said.split(' ').length;
    const m = SAID[at].lines.length + 1;
    const timers: ReturnType<typeof setTimeout>[] = [];
    setSpoken(0);
    setShown(0);
    let t = 260;
    for (let w = 1; w <= n; w++) {
      timers.push(setTimeout(() => setSpoken(w), t));
      t += WORD;
    }
    t += 520; // the brain's moment
    for (let j = 1; j <= m; j++) {
      timers.push(setTimeout(() => setShown(j), t));
      t += j === m - 1 ? 700 : 520;
    }
    return () => timers.forEach(clearTimeout);
  }, [at, still, moved]);

  // once the exchange is done the next phrase follows; pointing at or tabbing into the section holds it
  const cycling = done && !held && seen && !still;
  useEffect(() => {
    if (!cycling) return;
    const t = setTimeout(() => {
      setMoved(true);
      setAt((a) => (a + 1) % SAID.length);
    }, HOLD);
    return () => clearTimeout(t);
  }, [cycling, at]);

  const saying = spoken < words.length;
  const replying = !saying && shown < total;
  const voice: Voice = saying && spoken > 0 ? 'you' : replying && shown > 0 && shown < total ? 'me' : null;
  const state = saying ? 'listening' : replying ? (shown === 0 ? 'thinking' : 'speaking') : 'listening';

  return (
    <section
      ref={root}
      data-stagger
      aria-labelledby={`${id}-h`}
      onPointerEnter={(e) => e.pointerType === 'mouse' && setHeld(true)}
      onPointerLeave={() => setHeld(false)}
      onFocus={() => setHeld(true)}
      onBlur={(e) => !e.currentTarget.contains(e.relatedTarget as Node) && setHeld(false)}
      className="mx-auto grid w-full max-w-[1400px] gap-x-8 gap-y-10 px-2 text-fd-foreground md:px-12 lg:grid-cols-12"
      style={{ '--hold': `${HOLD}ms` } as React.CSSProperties}
    >
      <div className="flex flex-col gap-5 lg:col-span-6 lg:row-start-1">
        <h2 id={`${id}-h`} data-reveal className={heading}>
          Say it your way
        </h2>
        <p data-reveal className={intro}>
          No wake word and nothing to memorise. Ask about the project and it answers. Ask for work and it goes to a
          session. Commands are spoken too: “slash mute”, “slash clear”.
        </p>
      </div>

      {/* the way into the full list: under the intro on wide screens, after the phrases on a phone */}
      <Link
        data-reveal
        href="/docs/guide/talking"
        className="arrow-link inline-flex w-fit items-center gap-2 self-start rounded-md text-lg font-medium max-lg:order-10 lg:col-span-6 lg:row-start-2 lg:-mt-4"
      >
        <span className="link">Everything it understands</span>
        <ArrowRight />
      </Link>

      {/* the six phrases: each is a button; pointing at it, tabbing to it or tapping it says it */}
      <ul aria-label="Things you might say" className="flex flex-col justify-end max-lg:order-9 lg:col-span-5 lg:col-start-8 lg:row-span-2 lg:row-start-1">
        {SAID.map((s, i) => (
          <li key={s.said} data-reveal>
            <button
              type="button"
              onClick={() => choose(i)}
              onPointerEnter={(e) => e.pointerType === 'mouse' && choose(i)}
              onFocus={() => choose(i)}
              aria-pressed={i === at}
              className="pick press relative flex w-full items-baseline gap-3 rounded-md py-2 text-left text-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fd-ring"
            >
              <span aria-hidden className="pick-mark font-medium text-you">
                ›
              </span>
              <span className="relative">
                {s.said}
                {i === at && cycling && <span key={`${at}`} aria-hidden className="phrase-timer" />}
              </span>
            </button>
          </li>
        ))}
      </ul>

      {/* the exchange: the phrase set large and said word by word over its voice level, and the window's answer */}
      <div data-reveal className="surface relative grid gap-8 overflow-hidden rounded-2xl p-6 md:p-10 lg:col-span-12 lg:row-start-3 lg:grid-cols-12 lg:items-center lg:gap-8 lg:p-14">
        <div className="flex min-w-0 flex-col gap-8 lg:col-span-7">
          <p key={at} aria-live="polite" className={`said ${moved ? 'said-in' : ''}`}>
            <span className="sr-only">You say: </span>
            {words.map((w, i) => (
              <span key={i} className={`said-word ${i < spoken ? 'is-said' : ''}`}>
                {w}
                {i < words.length - 1 ? ' ' : ''}
              </span>
            ))}
          </p>
          <Level voice={voice} live={seen && !still} />
        </div>
        <div className="min-w-0 lg:col-span-5">
          <Term
            status={
              <span className="flex min-w-0 flex-1 items-center gap-3 whitespace-pre">
                <span key={state} className={`state-swap ${state === 'speaking' ? 'text-(--t-me)' : ''}`}>
                  {state}
                </span>
                <span className="ml-auto truncate">~/code/myproject</span>
              </span>
            }
            className="min-h-[248px]"
          >
            {!saying && <TranscriptLine key={`you-${at}`} line={{ kind: 'you', text: pick.said }} fresh={moved} />}
            {pick.lines.slice(0, Math.max(0, shown)).map((l, i) => (
              <TranscriptLine key={`${at}-${i}`} line={l} fresh={moved} />
            ))}
            {shown >= total && <TranscriptLine key={`note-${at}`} line={{ kind: 'note', text: `· ${pick.then}` }} fresh={moved} />}
          </Term>
        </div>
      </div>
    </section>
  );
}

function ArrowRight() {
  return (
    <svg aria-hidden width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="arrow">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}
