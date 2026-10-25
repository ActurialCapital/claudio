import type { ReactNode, Ref } from 'react';

// claudio's transcript lines, as the terminal prints them: › you, ◆ claudio, ▸ a session, → a tool, ⚙ a setting.
// Every window on the landing is the same dark terminal, in both themes, so the glyphs use the terminal's own inks.
export type Line =
  | { kind: 'you'; text: string; typing?: boolean; tag?: string }
  | { kind: 'me'; text: string; first: boolean; typing?: boolean; tag?: string }
  | { kind: 'tool'; text: string }
  | { kind: 'set'; key: string; value: string }
  | { kind: 'note'; text: string }
  | { kind: 'event'; who: string; what: string; asked?: string };

// a state word claudio prints beside a line (· paused, · eager 0.3); it fades in where it changes
function Tag({ text }: { text?: string }) {
  if (!text) return null;
  return (
    <span key={text} className="state-swap text-(--t-dim)">
      {'  · '}
      {text}
    </span>
  );
}

// `fresh` lines arrived while the visitor watched, so they ease in; the first paint never animates.
export function TranscriptLine({ line, fresh = false }: { line: Line; fresh?: boolean }) {
  const enter = fresh ? ' line-in' : '';
  switch (line.kind) {
    case 'you':
      return (
        <div className={`mt-3 whitespace-pre-wrap pl-[2ch] -indent-[2ch] first:mt-0${enter}`}>
          <span className="font-bold text-(--t-you)">› </span>
          {line.text}
          {line.typing && <span className="caret text-(--t-you)">▍</span>}
          <Tag text={line.tag} />
        </div>
      );
    case 'me':
      return (
        <div className={`whitespace-pre-wrap pl-[2ch] -indent-[2ch]${enter}`}>
          <span className="font-bold text-(--t-me)">{line.first ? '◆ ' : '  '}</span>
          {line.text}
          {line.typing && <span className="caret text-(--t-me)">▍</span>}
          <Tag text={line.tag} />
        </div>
      );
    case 'tool':
      return <div className={`whitespace-pre-wrap text-(--t-dim)${enter}`}>{'  → '}{line.text}</div>;
    case 'set':
      return (
        <div className={`whitespace-pre-wrap${enter}`}>
          <span className="text-(--t-dim)">⚙ </span>{/* taste-skill-ignore: claudio's setting glyph */}
          {line.key} <span className="text-(--t-dim)">→</span> {line.value}
        </div>
      );
    case 'note':
      return <div className={`whitespace-pre-wrap pl-[2ch] -indent-[2ch] text-(--t-dim)${enter}`}>{line.text}</div>;
    case 'event':
      return (
        <div className={`mt-3 whitespace-pre-wrap first:mt-0${enter}`}>
          <span className="font-bold text-(--t-ses)">▸ </span>
          <span className="text-(--t-ses)">{line.who}</span>
          <span className="text-(--t-dim)">
            {'  '}
            {line.what}
            {line.asked && <>{'  ·  '}for &quot;{line.asked}&quot;</>}
          </span>
        </div>
      );
  }
}

// The window's frame, shared by every terminal on the page: the dark ground, a faint edge, the state line.
export const termFrame = 'term-window flex flex-col overflow-hidden rounded-xl border-2 border-(--t-line) bg-(--t-bg) text-(--t-fg)';
export const termBar = 'flex items-center gap-3 border-b border-(--t-line) bg-(--t-bar) px-4 py-2.5 font-mono text-xs text-(--t-dim)'; // taste-skill-ignore: the window's own state-line edge
export const termBody = 'block px-5 py-4 font-mono text-[13px] leading-[1.7]'; // taste-skill-ignore: real terminal output in a data-ui fragment

// The claudio window: a state line on top, the transcript under it. Its root is a real interface fragment (data-ui).
export function Term({
  status,
  children,
  className = '',
  bodyClassName = '',
  bodyRef,
}: {
  status: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  bodyRef?: Ref<HTMLElement>;
}) {
  return (
    <div data-ui className={`${termFrame} ${className}`}>
      <samp className={termBar}>{status}</samp> {/* taste-skill-ignore: the window's own state-line edge */}
      <samp ref={bodyRef} className={`${termBody} ${bodyClassName}`}>{children}</samp> {/* taste-skill-ignore: real terminal output in a data-ui fragment */}
    </div>
  );
}
