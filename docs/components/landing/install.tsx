'use client';
import { useEffect, useRef, useState } from 'react';
import { termBar, termFrame } from './term';

// What you paste, as you would type it: the long install breaks after `install`, the way a shell continues a line.
const COPY = ['uv tool install git+https://github.com/ActurialCapital/claudio', 'cd ~/code/myproject && claudio'];

export function Install() {
  const [copied, setCopied] = useState(false);
  const reset = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(reset.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(COPY.join('\n'));
      setCopied(true);
      clearTimeout(reset.current);
      reset.current = setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div data-ui className={termFrame}>
      <div className={`${termBar} justify-between py-1.5 pr-1.5`}>
        <span>Install and run</span>
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? 'Copied' : 'Copy the commands'}
          className="press grid rounded-md px-2.5 py-1.5 font-sans text-[13px] font-medium text-(--t-fg) transition-colors hover:bg-(--t-hover) focus-visible:outline-2 focus-visible:outline-(--t-you)"
        >
          {/* both labels share one cell, so the button keeps its width while they cross */}
          <span className={`copy-label col-start-1 row-start-1 inline-flex items-center gap-1.5 ${copied ? 'is-off' : ''}`} aria-hidden={copied}>
            <CopyIcon /> Copy
          </span>
          <span className={`copy-label col-start-1 row-start-1 inline-flex items-center gap-1.5 text-(--t-me) ${copied ? '' : 'is-off'}`} aria-hidden={!copied}>
            <CheckIcon /> Copied
          </span>
          <span className="sr-only" aria-live="polite">
            {copied ? 'Copied to the clipboard' : ''}
          </span>
        </button>
      </div>
      {/* one command per line; what still runs past the edge scrolls inside the window, never the page */}
      <pre tabIndex={0} aria-label="Install commands" className="overflow-x-auto px-5 py-4 font-mono text-[13px] leading-[1.75] [scrollbar-width:thin] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--t-you)">
        <span className="block">
          <span className="select-none text-(--t-dim)">$ </span>uv tool install <span className="select-none text-(--t-dim)">\</span>
        </span>
        <span className="block pl-[4ch]">git+https://github.com/ActurialCapital/claudio</span>
        <span className="block">
          <span className="select-none text-(--t-dim)">$ </span>cd ~/code/myproject <span className="text-(--t-dim)">&amp;&amp;</span> claudio
        </span>
      </pre>
    </div>
  );
}

function CopyIcon() {
  return (
    <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="9" y="9" width="12" height="12" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg aria-hidden width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12 5 5 9-10" />
    </svg>
  );
}
