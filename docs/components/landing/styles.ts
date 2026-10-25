// Type steps shared by the landing's sections, so every heading and intro sits on the same scale.
export const heading = 'pt-[0.15em] text-fd-foreground text-[clamp(2.25rem,4.2vw,4rem)] font-medium leading-[1.02] tracking-[-0.035em]'; // the top pad holds the glyphs' ascent inside the box at this tight leading
export const intro = 'max-w-[34rem] text-lg leading-relaxed text-fd-foreground';

// The pill buttons: one shape, the brand action and the quiet one beside it.
const pill =
  'press inline-flex justify-center rounded-full px-5 py-3 font-medium tracking-tight focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fd-ring';
export const pillBrand = `${pill} bg-brand text-brand-foreground hover:bg-brand-200`;
export const pillQuiet = `${pill} border bg-fd-secondary text-fd-secondary-foreground hover:bg-fd-accent`;
