'use client';
import { type RefObject, useEffect, useState } from 'react';

// Small shared hooks for the landing's live parts: the theme, reduced motion, and whether a part is on screen.

export function useDark() {
  const [dark, setDark] = useState(true);
  useEffect(() => {
    const root = document.documentElement;
    const read = () => setDark(root.classList.contains('dark'));
    read();
    const watch = new MutationObserver(read);
    watch.observe(root, { attributes: true, attributeFilter: ['class'] });
    return () => watch.disconnect();
  }, []);
  return dark;
}

export function useStill() {
  const [still, setStill] = useState(false);
  useEffect(() => {
    const q = window.matchMedia('(prefers-reduced-motion: reduce)');
    const read = () => setStill(q.matches);
    read();
    q.addEventListener('change', read);
    return () => q.removeEventListener('change', read);
  }, []);
  return still;
}

// `margin` widens the window, so a shader can mount a little before it scrolls in
export function useInView(ref: RefObject<Element | null>, { margin = '0px', once = false } = {}) {
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || !('IntersectionObserver' in window)) return setSeen(true);
    const watch = new IntersectionObserver(
      ([e]) => {
        setSeen(e.isIntersecting);
        if (e.isIntersecting && once) watch.disconnect();
      },
      { rootMargin: margin },
    );
    watch.observe(el);
    return () => watch.disconnect();
  }, [ref, margin, once]);
  return seen;
}
