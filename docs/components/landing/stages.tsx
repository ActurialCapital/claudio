'use client';
import { useEffect, useRef, useState } from 'react';
import { heading, intro } from './styles';
import { type Line, Term, TranscriptLine } from './term';
import { useDark, useInView, useStill } from './use-landing';
import { Dithering } from './shaders';

// The hero's sun, carried down the page: a dithered sound wave that moves only while sound flows (you talking,
// the mouth speaking). Lazy, client only, mounted as it nears the screen, wide screens only.

// One turn, as a signal path: five parts, each with its one job and the setting that shapes it.
const STAGES = [
  { name: 'Mic', does: 'Apple’s echo canceller removes claudio’s own voice.', setting: 'barge_in true' },
  { name: 'Ears', does: 'Deepgram Flux writes it down and decides when you have finished.', setting: 'eot 0.7' },
  { name: 'Brain', does: 'It answers, or hands the job to a session.', setting: 'effort low' },
  { name: 'Mouth', does: 'Each sentence is spoken as soon as it is written.', setting: 'voice orion' },
  { name: 'Session', does: 'Claude Code hooks say when it is done or needs you.', setting: 'narrate handed-off' },
];

const ASKED = 'rebase 44 on main and run the tests';

// What the window shows at each part of the turn. Each moment keeps what came before, as the transcript does.
const MOMENTS: { state: string; orch: string; lines: Line[] }[] = [
  { state: 'listening', orch: 'Sequencer idle', lines: [{ kind: 'you', text: ASKED }] },
  { state: 'listening', orch: 'Sequencer idle', lines: [{ kind: 'you', text: ASKED }, { kind: 'tool', text: 'end of turn, 0.7' }] },
  {
    state: 'thinking',
    orch: 'Sequencer idle',
    lines: [{ kind: 'you', text: ASKED }, { kind: 'tool', text: 'end of turn, 0.7' }, { kind: 'me', text: '', first: true, typing: true }],
  },
  {
    state: 'speaking',
    orch: 'Sequencer working',
    lines: [
      { kind: 'you', text: ASKED },
      { kind: 'tool', text: 'end of turn, 0.7' },
      { kind: 'me', text: 'Sending that to Sequencer.', first: true },
      { kind: 'tool', text: 'cmux agent message' },
    ],
  },
  {
    state: 'speaking',
    orch: 'Sequencer idle',
    lines: [
      { kind: 'you', text: ASKED },
      { kind: 'me', text: 'Sending that to Sequencer.', first: true },
      { kind: 'tool', text: 'cmux agent message' },
      { kind: 'event', who: 'Sequencer', what: 'done', asked: 'rebase 44 on main' },
      { kind: 'me', text: 'Rebased on main, tests pass, nothing to fix.', first: true },
    ],
  },
];

const clamp = (v: number) => Math.min(1, Math.max(0, v));

// the mic meter in the window's state line: it moves while sound flows, flat otherwise
function Meter({ on }: { on: boolean }) {
  return (
    <span aria-hidden className={`meter ${on ? 'is-on' : ''}`}>
      <span />
      <span />
      <span />
    </span>
  );
}

export function Stages() {
  const still = useStill();
  const [linked, setLinked] = useState(false); // the scroll drives the path; never without script or with reduced motion
  const [p, setP] = useState(1); // how far through the held stage the reader is, 0 to 1
  const [typed, setTyped] = useState(ASKED.length);
  const wrap = useRef<HTMLDivElement>(null);
  const hold = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLDivElement>(null);
  const head = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const near = useInView(field, { margin: '200px' });
  const dark = useDark();

  useEffect(() => setLinked(!still), [still]);

  // progress is read from the page's own scroll position: the held card fills its path as the page moves on
  useEffect(() => {
    if (!linked) return setP(1);
    let raf = 0;
    const read = () => {
      raf = 0;
      const el = wrap.current;
      // wide screens hold the heading with the card; a phone lets the heading go and holds the card alone
      const wide = window.matchMedia('(min-width: 1024px)').matches;
      const st = wide ? hold.current : card.current;
      if (!el || !st || !head.current) return;
      const offset = wide ? 0 : head.current.offsetHeight;
      const travel = el.offsetHeight - offset - st.offsetHeight;
      const top = parseFloat(getComputedStyle(st).top) || 0;
      setP(travel > 0 ? clamp((top - el.getBoundingClientRect().top - offset) / travel) : 1);
    };
    const on = () => {
      if (!raf) raf = requestAnimationFrame(read);
    };
    read();
    window.addEventListener('scroll', on, { passive: true });
    window.addEventListener('resize', on);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('scroll', on);
      window.removeEventListener('resize', on);
    };
  }, [linked]);

  // the fill reaches each part in the middle of its stretch of scroll; the lit part is the nearest one
  const fill = linked ? clamp((p * 5 - 0.5) / 4) : 1;
  const at = linked ? Math.round(fill * 4) : null;
  const moment = MOMENTS[at ?? MOMENTS.length - 1];
  const flow = at === 0 || at === 3;

  // at the mic, your words arrive as you say them
  useEffect(() => {
    if (at !== 0) return setTyped(ASKED.length);
    setTyped(0);
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setTyped(i);
      if (i >= ASKED.length) clearInterval(id);
    }, 42);
    return () => clearInterval(id);
  }, [at]);

  // lines that the previous moment did not have ease in
  const prev = useRef<number | null>(null);
  const before = prev.current === null || at === null || at < prev.current ? 0 : MOMENTS[prev.current].lines.length;
  useEffect(() => {
    prev.current = at;
  }, [at]);

  const lines = moment.lines.map((l, i) => (at === 0 && i === 0 && l.kind === 'you' ? { ...l, text: ASKED.slice(0, typed), typing: typed < ASKED.length } : l));

  return (
    <section aria-labelledby="turn" data-stagger className="mx-auto w-full max-w-[1400px] text-fd-foreground">
      {/* while the card is held, the page's scroll walks the turn from the mic to the session */}
      <div ref={wrap} className={`relative ${linked ? 'stage-run' : ''}`}>
        {/* the heading is held with the card on wide screens; on a phone it scrolls away and the card stays */}
        <div ref={hold} className={linked ? 'stage-hold' : ''}>
          <div ref={head} className="grid gap-5 px-2 pb-10 md:px-12 md:pb-12 lg:grid-cols-12 lg:items-end lg:gap-8">
            <h2 id="turn" data-reveal className={`${heading} lg:col-span-7`}>
              One turn, stage by stage
            </h2>
            <p data-reveal className={`${intro} lg:col-span-5`}>
              Your words go through five parts and come back as speech. Each has one job and one setting you can change.
            </p>
          </div>
          <div ref={card} data-reveal className="stage-card surface relative overflow-hidden rounded-2xl">
            <div className="px-5 pt-6 pb-4 md:px-12 md:pt-12 md:pb-6">
              <ol
                aria-label="The five parts of a turn"
                data-linked={linked || undefined}
                className="track relative grid auto-rows-fr lg:grid-cols-5 lg:auto-rows-auto"
                style={{ '--fill': fill } as React.CSSProperties}
              >
                <span aria-hidden className="track-rail" />
                <span aria-hidden className="track-fill" />
                {STAGES.map((s, i) => (
                  <li
                    key={s.name}
                    aria-current={at === i ? 'step' : undefined}
                    data-state={at === null ? 'all' : i < at ? 'past' : i === at ? 'on' : 'next'}
                    className="stage relative grid grid-cols-[auto_1fr] content-start items-center gap-x-3 gap-y-1 pb-3 pl-9 lg:flex lg:flex-col lg:items-start lg:gap-2 lg:pb-0 lg:pl-0 lg:pt-11 lg:pr-6"
                  >
                    <span aria-hidden className="stage-node" />
                    <span className="stage-label text-lg font-medium tracking-[-0.02em] lg:text-2xl">{s.name}</span>
                    <code className="stage-chip w-fit rounded-md px-1.5 py-0.5 font-mono text-[13px] lg:order-3 lg:mt-1">{s.setting}</code>
                    <span className="stage-label col-span-2 max-w-[22rem] text-sm leading-snug lg:order-2 lg:text-base">{s.does}</span>
                  </li>
                ))}
              </ol>
            </div>

            {/* the window shows this part's moment of the turn, on the dithered wave */}
            <div ref={field} className="relative h-[230px] overflow-hidden md:h-[300px] lg:h-[290px]">
              {near && (
                <Dithering
                  width={2400}
                  height={400}
                  colorBack="#00000000"
                  colorFront={dark ? '#DF3F00' : '#fa8023'}
                  shape="wave"
                  type="4x4"
                  size={2}
                  scale={0.45}
                  speed={flow && !still ? 0.45 : 0}
                  frame={24000}
                  minPixelRatio={1}
                  className="wave-field absolute inset-x-0 top-0 h-[145%]! w-full! animate-fd-fade-in duration-700 max-lg:hidden!"
                />
              )}
              <Term
                status={
                  <span className="flex min-w-0 flex-1 items-center gap-3 whitespace-pre">
                    <Meter on={flow && linked} />
                    <span key={moment.state} className={`state-swap ${moment.state === 'speaking' ? 'text-(--t-me)' : ''}`}>
                      {moment.state}
                    </span>
                    <span className="min-w-0 truncate">
                      {'·  '}
                      <span key={moment.orch} className="state-swap">
                        {moment.orch}
                      </span>
                    </span>
                    <span className="ml-auto hidden sm:inline">~/code/myproject</span>
                  </span>
                }
                className="absolute inset-x-3 top-0 bottom-[-1rem] md:inset-x-[10%] lg:inset-x-[20%] lg:top-10"
                bodyClassName="min-h-0 flex-1 overflow-hidden"
              >
                {lines.map((l, i) => (
                  <TranscriptLine key={`${at}-${i}`} line={l} fresh={linked && i >= before} />
                ))}
              </Term>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
