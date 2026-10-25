'use client';
import { useEffect } from 'react';

// Section entrances, choreographed per group. Each [data-stagger] group arrives once as its top passes 88% of the
// screen; its [data-reveal] parts follow in reading order, 75ms apart, four steps at most.
// Only groups below the fold are ever hidden, and only by this script: without it, or with reduced motion, all shows.
// Browsers with scroll-driven animations get the scroll-linked entrances in landing.css instead.
export function Reveal() {
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    if (!('IntersectionObserver' in window)) return;
    // where the browser can tie an entrance to the scroll itself (landing.css), it does; this is the fallback
    if (CSS.supports('animation-timeline: view()')) return;
    const groups = [...document.querySelectorAll<HTMLElement>('[data-stagger]')];
    const fold = window.innerHeight;
    const watch = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          e.target.setAttribute('data-in', '');
          watch.unobserve(e.target);
        }
      },
      { rootMargin: '0px 0px -12% 0px' },
    );
    for (const g of groups) {
      if (g.getBoundingClientRect().top < fold) continue; // already on screen: never hide it
      const parts = [...g.querySelectorAll<HTMLElement>('[data-reveal]')].filter((el) => el.closest('[data-stagger]') === g);
      parts.forEach((el, i) => el.style.setProperty('--i', String(Math.min(i, 4))));
      g.setAttribute('data-armed', '');
      watch.observe(g);
    }
    return () => watch.disconnect();
  }, []);
  return null;
}
