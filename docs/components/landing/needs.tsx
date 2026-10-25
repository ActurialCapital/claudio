'use client';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { Install } from './install';
import { heading } from './styles';
import { termBar, termBody, termFrame } from './term';
import { useDark, useInView, useStill } from './use-landing';

// The close returns to the hero's light: the same grain gradient, so the page ends where it began.
const GrainGradient = dynamic(() => import('@paper-design/shaders-react').then((m) => m.GrainGradient), { ssr: false });

const NEEDS = ['A Mac', 'cmux, with the workspace you send work to', 'Claude Code, signed in', 'A Deepgram API key', 'Python 3.11 and uv'];

const DOCTOR = [
  'claude on PATH',
  'cmux reachable',
  "orchestrator 'Sequencer' is a live workspace",
  'Deepgram key accepted',
  'the three Claude Code hooks installed',
  'echo canceller built or buildable',
  'microphone: MacBook Pro Microphone',
];
const CMD = 'claudio doctor';
const ROWS = DOCTOR.length + 3; // the checks, the typed turn, its answer, all good

const pill =
  'press inline-flex justify-center rounded-full px-5 py-3 font-medium tracking-tight focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fd-ring';

// The doctor's check, as the first screen you will see. It runs once as the section arrives: the command is
// typed, then each check prints. Before that, without script and with reduced motion, it is the finished output.
function Doctor() {
  const root = useRef<HTMLDivElement>(null);
  const [typed, setTyped] = useState(CMD.length);
  const [rows, setRows] = useState(ROWS);
  const [armed, setArmed] = useState(false);
  const seen = useInView(root, { once: true, margin: '0px 0px -15% 0px' });
  const still = useStill();

  // only a window that starts below the fold is cleared to be played; one already on screen stays finished
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const el = root.current;
    if (!el || el.getBoundingClientRect().top < window.innerHeight) return;
    setArmed(true);
    setTyped(0);
    setRows(0);
  }, []);

  useEffect(() => {
    if (!armed || !seen || still) return;
    const timers: ReturnType<typeof setTimeout>[] = [];
    let t = 350;
    for (let i = 1; i <= CMD.length; i++) {
      t += 45 + ((i * 29) % 30);
      timers.push(setTimeout(() => setTyped(i), t));
    }
    t += 420;
    for (let r = 1; r <= ROWS; r++) {
      timers.push(setTimeout(() => setRows(r), t));
      t += r === DOCTOR.length ? 700 : r === DOCTOR.length + 1 ? 900 : 150;
    }
    return () => timers.forEach(clearTimeout);
  }, [armed, seen, still]);

  const show = (r: number) => (r < rows ? 'doc-row is-on' : 'doc-row');
  return (
    <div ref={root} data-ui className={`${termFrame} w-full`}>
      <samp className={termBar}> {/* taste-skill-ignore: the window's own state-line edge */}
        <span className="min-w-0 flex-1 truncate">~/code/myproject</span>
        <span className={rows >= ROWS ? 'text-(--t-ok)' : ''}>{rows >= ROWS ? 'all good' : typed < CMD.length ? 'ready' : 'checking'}</span>
      </samp>
      <samp className={`${termBody} overflow-x-auto md:py-5 md:text-sm md:leading-[1.9]`}> {/* taste-skill-ignore: real terminal output in a data-ui fragment */}
        <span className="block">
          <span className="text-(--t-dim)">$ </span>
          {CMD.slice(0, typed)}
          {typed < CMD.length && <span className="caret text-(--t-you)">▍</span>}
        </span>
        {DOCTOR.map((d, i) => (
          <span key={d} className={`${show(i)} block whitespace-pre-wrap pl-[4ch] -indent-[4ch] sm:whitespace-pre sm:pl-0 sm:indent-0`}>
            <span className="text-(--t-ok)">
              {'  '}
              <Tick />
              {' '}
            </span>
            {d}
          </span>
        ))}
        <span className={`${show(DOCTOR.length)} mt-2 block text-(--t-dim)`}>  one typed turn through brain and mouth…</span>
        <span className={`${show(DOCTOR.length + 1)} block`}>
          <span className="font-bold text-(--t-me)">◆ </span>The doctor is in.
        </span>
        <span className={`${show(DOCTOR.length + 2)} mt-2 block text-(--t-ok)`}>  all good</span>
      </samp>
    </div>
  );
}

// the doctor's tick, drawn one character wide so the checks stay in their column
function Tick() {
  return (
    <svg aria-label="passed" role="img" viewBox="0 0 24 24" className="inline-block h-[0.9em] w-[1ch] -translate-y-px align-middle" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12 5 5 9-10" />
    </svg>
  );
}

// What it takes, how to get it, and the first screen you will see: the page's close, lit like the hero.
export function Needs() {
  const card = useRef<HTMLElement>(null);
  const near = useInView(card, { margin: '200px' });
  const dark = useDark();
  const still = useStill();
  return (
    <section
      ref={card}
      data-stagger
      aria-labelledby="needs"
      className="surface relative mx-auto w-full max-w-[1400px] overflow-hidden rounded-2xl text-fd-foreground"
    >
      {near && (
        <GrainGradient
          className="absolute inset-0 animate-fd-fade-in duration-800"
          colors={dark ? ['#39BE1C', '#9c2f05', '#7A2A0000'] : ['#fcfc51', '#ffa057', '#7A2A0020']}
          colorBack="#00000000"
          softness={1}
          intensity={0.9}
          noise={0.5}
          speed={still ? 0 : 0.6}
          shape="wave"
          minPixelRatio={1}
          maxPixelCount={1600000}
        />
      )}
      <div className="relative z-1 grid gap-12 px-6 py-12 md:px-12 md:py-16 lg:grid-cols-12 lg:gap-8 lg:py-20">
        <div className="flex min-w-0 flex-col gap-7 lg:col-span-5">
          <h2 id="needs" data-reveal className={heading}>
            What you need
          </h2>
          <ul data-reveal className="flex flex-col gap-2 text-lg font-medium text-fd-foreground">
            {NEEDS.map((n) => (
              <li key={n} className="flex items-baseline gap-3">
                <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 translate-y-[1px] text-brand">
                  <path d="m5 12 5 5 9-10" />
                </svg>
                {n}
              </li>
            ))}
          </ul>
          <div data-reveal>
            <Install />
          </div>
          <div data-reveal className="flex flex-wrap items-center gap-3">
            <Link href="/docs/guide/getting-started" className={`${pill} bg-brand text-black hover:bg-brand-200`}>
              Install claudio
            </Link>
            <Link href="/docs" className={`${pill} border bg-fd-secondary text-fd-secondary-foreground hover:bg-fd-accent`}>
              Read the docs
            </Link>
          </div>
        </div>
        <div data-reveal className="flex min-w-0 items-start lg:col-span-6 lg:col-start-7">
          <Doctor />
        </div>
      </div>
    </section>
  );
}
