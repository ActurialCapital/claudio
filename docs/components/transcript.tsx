import type { CSSProperties } from 'react';

// A static claudio transcript for the docs: each line coloured by its glyph, as the terminal shows it.
// It is a real fragment of claudio's interface (data-ui), and each line is program output, so it is set as <samp>
// in the terminal's own monospace.
const STYLE: Record<string, string> = {
  '›': 'text-term-you',
  '◆': 'text-term-me',
  '▸': 'text-term-event',
  '→': 'text-term-dim',
  '·': 'text-term-dim',
  '⚙': 'text-term-dim',
  '!': 'text-[hsl(45,95%,62%)]',
  '▃': 'text-term-dim',
};
const DIM = new Set(['→', '·', '⚙', '▃']);

// long lines wrap under their text, not under the glyph
const LINE = 'block whitespace-pre-wrap break-words ps-[2ch] -indent-[2ch]';

export function Transcript({ children }: { children: string }) {
  const lines = children.replace(/^\n+|\n+$/g, '').split('\n');
  return (
    <div
      data-ui
      role="group"
      aria-label="claudio transcript"
      className="docs-transcript not-prose my-6 rounded-xl bg-term px-5 py-4 font-mono text-[13px] leading-[1.7] text-term-fg"
    >
      {lines.map((line, i) => {
        const at = { '--i': i } as CSSProperties;
        if (!line.trim()) return <samp key={i} data-line style={at} className="block">&nbsp;</samp>;
        const glyph = line.trimStart()[0];
        const style = STYLE[glyph];
        if (!style) return <samp key={i} data-line style={at} className={LINE}>{line}</samp>;
        const pos = line.indexOf(glyph);
        return (
          <samp key={i} data-line style={at} className={`${LINE} ${DIM.has(glyph) ? 'text-term-dim' : ''}`}>
            {line.slice(0, pos)}
            <span className={`font-bold ${style}`}>{glyph}</span>
            {line.slice(pos + 1)}
          </samp>
        );
      })}
    </div>
  );
}
