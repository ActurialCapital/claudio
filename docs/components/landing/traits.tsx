'use client';
import dynamic from 'next/dynamic';
import { useEffect, useRef, useState } from 'react';
import { heading, intro } from './styles';
import { type Line, TranscriptLine, termBody, termFrame } from './term';
import { useDark, useInView, useStill } from './use-landing';

// The page's shader language, lazy and client only; each tile mounts its picture only as it nears the screen.
const Dithering = dynamic(() => import('@paper-design/shaders-react').then((m) => m.Dithering), { ssr: false });
const GrainGradient = dynamic(() => import('@paper-design/shaders-react').then((m) => m.GrainGradient), { ssr: false });

// A transcript file line: claudio writes each line of the conversation with the time in front of it.
type Row = Line | { kind: 'file'; time: string; line: Line };
type Beat = { ms: number; rows: Row[] };

const ASKED = 'rebase 44 on main';

// Each trait plays a few beats of the real transcript. The last beat is the finished state: the first paint,
// what shows without script, and all that shows with reduced motion.
const TRAITS: { name: string; line: string; beats: Beat[] }[] = [
  {
    name: 'Talk over it',
    line: 'Start speaking and it pauses; an “mm-hm” lets it carry on.',
    beats: [
      { ms: 700, rows: [{ kind: 'me', text: 'Rebased on main,', first: true, typing: true }] },
      { ms: 600, rows: [{ kind: 'me', text: 'Rebased on main, tests pass,', first: true, typing: true }] },
      {
        ms: 1100,
        rows: [
          { kind: 'me', text: 'Rebased on main, tests pass,', first: true, tag: 'paused' },
          { kind: 'you', text: 'mm-hm' },
        ],
      },
      {
        ms: 2800,
        rows: [
          { kind: 'me', text: 'Rebased on main, tests pass,', first: true },
          { kind: 'you', text: 'mm-hm' },
          { kind: 'me', text: 'and there is nothing to fix.', first: false, tag: 'resumed' },
        ],
      },
    ],
  },
  {
    name: 'It starts early',
    line: 'The brain starts on your words before your turn is final.',
    beats: [
      { ms: 900, rows: [{ kind: 'you', text: 'rebase 44 on', typing: true }] },
      {
        ms: 900,
        rows: [
          { kind: 'you', text: 'rebase 44 on main', typing: true },
          { kind: 'tool', text: 'eager 0.3, brain starts' },
        ],
      },
      {
        ms: 2800,
        rows: [
          { kind: 'you', text: 'rebase 44 on main' },
          { kind: 'tool', text: 'eager 0.3, brain starts' },
          { kind: 'tool', text: 'final 0.7, it speaks' },
          { kind: 'me', text: 'Sending that to Sequencer.', first: true },
        ],
      },
    ],
  },
  {
    name: 'Sessions report back',
    line: 'Done, a question or a permission: you hear it in plain words.',
    beats: [
      { ms: 1600, rows: [{ kind: 'note', text: '  Sequencer working' }] },
      { ms: 900, rows: [{ kind: 'event', who: 'Sequencer', what: 'done', asked: ASKED }] },
      {
        ms: 2800,
        rows: [
          { kind: 'event', who: 'Sequencer', what: 'done', asked: ASKED },
          { kind: 'me', text: 'Rebased on main, tests pass.', first: true },
        ],
      },
    ],
  },
  {
    name: 'It keeps the record',
    line: 'Every conversation lands in a dated Markdown file it can read back.',
    beats: [
      {
        ms: 900,
        rows: [
          { kind: 'tool', text: 'transcripts/2026-10-25.md' },
          { kind: 'file', time: '14:02', line: { kind: 'you', text: 'rebase 44 on main' } },
        ],
      },
      {
        ms: 900,
        rows: [
          { kind: 'tool', text: 'transcripts/2026-10-25.md' },
          { kind: 'file', time: '14:02', line: { kind: 'you', text: 'rebase 44 on main' } },
          { kind: 'file', time: '14:02', line: { kind: 'me', text: 'Sending that to Sequencer.', first: true } },
        ],
      },
      {
        ms: 2800,
        rows: [
          { kind: 'tool', text: 'transcripts/2026-10-25.md' },
          { kind: 'file', time: '14:02', line: { kind: 'you', text: 'rebase 44 on main' } },
          { kind: 'file', time: '14:02', line: { kind: 'me', text: 'Sending that to Sequencer.', first: true } },
          { kind: 'file', time: '14:05', line: { kind: 'event', who: 'Sequencer', what: 'done' } },
        ],
      },
    ],
  },
];

function RowLine({ row, fresh }: { row: Row; fresh: boolean }) {
  if (row.kind !== 'file') return <TranscriptLine line={row} fresh={fresh} />;
  return (
    <div className={`flex${fresh ? ' line-in' : ''}`}>
      <span className="mr-[2ch] shrink-0 text-(--t-dim)">{row.time}</span>
      <div className="min-w-0 *:mt-0">
        <TranscriptLine line={row.line} />
      </div>
    </div>
  );
}

// One small window that plays its beats while it is on screen, from the start each time round.
function Demo({ beats }: { beats: Beat[] }) {
  const last = beats.length - 1;
  const [at, setAt] = useState(last);
  const [live, setLive] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const seen = useInView(root);
  const still = useStill();

  useEffect(() => {
    if (still || !seen) return;
    const t = setTimeout(
      () => {
        setLive(true);
        setAt((a) => (a >= last ? 0 : a + 1));
      },
      live ? beats[at].ms : 900,
    );
    return () => clearTimeout(t);
  }, [at, seen, still, live, beats, last]);

  const rows = beats[still ? last : at].rows;
  // a line is new when the beat before did not have one at its place
  const before = at > 0 ? beats[at - 1].rows.length : 0;
  return (
    <div ref={root} data-ui className={`${termFrame} h-[172px] sm:h-[148px]`}>
      <samp className={`${termBody} overflow-hidden`}> {/* taste-skill-ignore: real terminal output in a data-ui fragment */}
        {rows.map((r, i) => (
          <RowLine key={`${at === 0 ? 'a' : 'b'}${i}`} row={r} fresh={live && i >= before} />
        ))}
      </samp>
    </div>
  );
}

// The shader each trait is drawn with: the hero's sun, dithered or grained, in a shape that says the trait.
// `place` is where the picture sits in its tile; text stays on the calm side.
const ART: { kind: 'dither' | 'grain'; shape: string; frame: number; place: string; span: string }[] = [
  { kind: 'dither', shape: 'ripple', frame: 9000, place: 'art-c', span: 'lg:col-span-7 lg:row-span-2 lg:min-h-[560px]' },
  { kind: 'dither', shape: 'warp', frame: 31000, place: 'art-tr', span: 'lg:col-span-5 lg:min-h-[272px]' },
  { kind: 'dither', shape: 'swirl', frame: 52000, place: 'art-tr', span: 'lg:col-span-5 lg:min-h-[272px]' },
  { kind: 'grain', shape: 'dots', frame: 0, place: 'art-r', span: 'lg:col-span-12 lg:min-h-[260px]' },
];

function Art({ i, live }: { i: number; live: boolean }) {
  const dark = useDark();
  const still = useStill();
  const a = ART[i];
  const speed = live && !still ? 0.35 : 0;
  if (a.kind === 'grain')
    return (
      <GrainGradient
        className="absolute inset-0 animate-fd-fade-in duration-700"
        colors={dark ? ['#DF3F00', '#9c2f05', '#39BE1C'] : ['#fa8023', '#ffa057', '#fcfc51']}
        colorBack="#00000000"
        softness={0.5}
        intensity={1}
        noise={0.45}
        shape="dots"
        speed={speed}
        minPixelRatio={1}
        maxPixelCount={900000}
      />
    );
  return (
    <Dithering
      className="absolute inset-0 h-full! w-full! animate-fd-fade-in duration-700"
      width={900}
      height={600}
      colorBack="#00000000"
      colorFront={dark ? '#DF3F00' : '#fa8023'}
      shape={a.shape as 'ripple'}
      type="4x4"
      size={2}
      scale={i === 0 ? 0.55 : 0.8}
      speed={speed}
      frame={a.frame}
      minPixelRatio={1}
    />
  );
}

// One tile: the trait's name and line, its picture, and its transcript on top. Under a fine pointer it leans a
// little toward the hand and a soft light follows it; with reduced motion it stays flat.
function Tile({ t, i, hot, onHot }: { t: (typeof TRAITS)[number]; i: number; hot: boolean; onHot: (on: boolean) => void }) {
  const el = useRef<HTMLLIElement>(null);
  const near = useInView(el, { margin: '120px' });
  const still = useStill();
  const a = ART[i];
  const move = (e: React.PointerEvent<HTMLLIElement>) => {
    if (e.pointerType !== 'mouse' || still || !el.current) return;
    const r = el.current.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width;
    const y = (e.clientY - r.top) / r.height;
    el.current.style.setProperty('--mx', `${(x * 100).toFixed(1)}%`);
    el.current.style.setProperty('--my', `${(y * 100).toFixed(1)}%`);
    el.current.style.setProperty('--ry', `${((x - 0.5) * 3).toFixed(2)}deg`);
    el.current.style.setProperty('--rx', `${((0.5 - y) * 3).toFixed(2)}deg`);
  };
  const leave = () => {
    onHot(false);
    el.current?.style.setProperty('--rx', '0deg');
    el.current?.style.setProperty('--ry', '0deg');
  };
  const wide = i === 3;
  return (
    <li
      ref={el}
      data-reveal
      onPointerEnter={(e) => e.pointerType === 'mouse' && onHot(true)}
      onPointerMove={move}
      onPointerLeave={leave}
      className={`tile surface relative isolate flex flex-col overflow-hidden rounded-2xl ${a.span} ${hot ? 'is-hot' : ''}`}
    >
      <div aria-hidden className={`tile-art ${a.place}`}>
        {near && <Art i={i} live={i === 0 || hot} />}
      </div>
      <div className={`relative z-1 flex h-full flex-col gap-6 p-6 md:p-8 ${wide ? 'lg:grid lg:grid-cols-12 lg:items-end lg:gap-8' : ''}`}>
        <div className={`flex max-w-[24rem] flex-col gap-2 ${wide ? 'lg:col-span-5 lg:self-start' : ''}`}>
          <h3 className="text-2xl font-medium tracking-[-0.02em]">{t.name}</h3>
          <p className="text-base leading-snug">{t.line}</p>
        </div>
        <div className={`mt-auto ${wide ? 'lg:col-span-6 lg:col-start-7' : i === 0 ? 'lg:max-w-[30rem]' : ''}`}>
          <Demo beats={t.beats} />
        </div>
      </div>
    </li>
  );
}

// Why it feels like talking: four traits in a bento, each with its picture and the transcript that shows it.
export function Traits() {
  const [hot, setHot] = useState<number | null>(null); // the tile under the pointer: its picture moves too
  return (
    <section data-stagger aria-labelledby="traits" className="mx-auto w-full max-w-[1400px] px-2 text-fd-foreground md:px-12">
      <div className="grid gap-5 lg:grid-cols-12 lg:items-end lg:gap-8">
        <h2 id="traits" data-reveal className={`${heading} lg:col-span-7`}>
          Built for talking
        </h2>
        <p data-reveal className={`${intro} lg:col-span-5`}>
          It behaves like someone on the other end of a call, not a command line waiting for input.
        </p>
      </div>
      <ul className="mt-10 grid gap-4 md:mt-14 lg:grid-cols-12">
        {TRAITS.map((t, i) => (
          <Tile key={t.name} t={t} i={i} hot={hot === i} onHot={(on) => setHot((h) => (on ? i : h === i ? null : h))} />
        ))}
      </ul>
    </section>
  );
}
