'use client';
// The docs pages' motion that CSS cannot do alone (the CSS is in app/global.css):
// - blocks below the fold rise once as they arrive; a transcript prints line by line; settings rows arrive row by row.
//   Only blocks still below the fold are armed, so nothing on screen ever blinks out, and with no script nothing is hidden.
// - the theme switch crossfades through a view transition.
// Both stand down when the reader asks for reduced motion.
import { usePathname } from 'next/navigation';
import { useEffect } from 'react';

const TARGETS: [selector: string, kind: string][] = [
  ['#nd-page .prose > h2', 'rise'],
  ['#nd-page .prose > .docs-transcript', 'lines'],
  ['#nd-page .prose > :is(figure, table, div):not(.docs-transcript, .docs-panel, .fd-steps, .docs-accordions)', 'settle'],
  ['#nd-page .prose > .docs-accordions > *', 'rise'],
  ['#nd-page .prose .fd-step', 'fade'],
  ['#nd-page .prose .docs-panel > .docs-row', 'rise'],
  ['#nd-page > .\\@container', 'settle'],
];

function reduced() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function useReveals(pathname: string) {
  useEffect(() => {
    if (reduced() || !('IntersectionObserver' in window)) return;
    const io = new IntersectionObserver(
      (entries) => {
        let step = 0;
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          const el = e.target as HTMLElement;
          el.style.setProperty('--reveal-step', String(Math.min(step++, 3)));
          el.dataset.reveal = 'in';
          io.unobserve(el);
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0 },
    );
    const fold = window.innerHeight;
    const armed: HTMLElement[] = [];
    for (const [selector, kind] of TARGETS) {
      for (const el of document.querySelectorAll<HTMLElement>(selector)) {
        if (el.dataset.reveal || el.getBoundingClientRect().top < fold) continue;
        el.dataset.reveal = 'wait';
        el.dataset.revealKind = kind;
        armed.push(el);
        io.observe(el);
      }
    }
    // printing or leaving the page shows everything
    const showAll = () => armed.forEach((el) => (el.dataset.reveal = 'in'));
    window.addEventListener('beforeprint', showAll);
    return () => {
      io.disconnect();
      window.removeEventListener('beforeprint', showAll);
    };
  }, [pathname]);
}

type FlaggedButton = HTMLButtonElement & { __docsFading?: boolean };

function useThemeFade() {
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const button = (event.target as Element | null)?.closest?.('button') as FlaggedButton | null;
      if (!button || !button.closest('[data-theme-toggle]') || button.__docsFading) return;
      if (!('startViewTransition' in document) || reduced()) return;
      event.preventDefault();
      event.stopPropagation();
      const root = document.documentElement;
      document.startViewTransition(
        () =>
          new Promise<void>((resolve) => {
            const done = () => {
              observer.disconnect();
              clearTimeout(timer);
              resolve();
            };
            const observer = new MutationObserver(done);
            observer.observe(root, { attributes: true, attributeFilter: ['class'] });
            const timer = setTimeout(done, 400);
            button.__docsFading = true;
            button.click();
            button.__docsFading = false;
          }),
      );
    };
    window.addEventListener('click', onClick, true);
    return () => window.removeEventListener('click', onClick, true);
  }, []);
}

export function DocsMotion() {
  const pathname = usePathname();
  useReveals(pathname);
  useThemeFade();
  return null;
}
