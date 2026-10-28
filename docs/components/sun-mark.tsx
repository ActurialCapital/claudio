// claudio's mark: the hero's sun, a sphere lit from the top left and dithered with a 4x4 Bayer matrix, on a
// 32x32 grid of round dots, as the terminal draws it in braille (claudio/ui.py sun()). Same maths as
// public/img/sun.svg (docs/scripts/gen_sun.py).
const N = 32;
const BAYER = [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5];

const CELLS: [number, number][] = [];
for (let y = 0; y < N; y++) {
  for (let x = 0; x < N; x++) {
    const nx = (x + 0.5) / (N / 2) - 1;
    const ny = (y + 0.5) / (N / 2) - 1;
    const r2 = nx * nx + ny * ny;
    if (r2 > 1) continue;
    const nz = Math.sqrt(1 - r2);
    const lit = Math.max(0, (-0.5 * nx - 0.6 * ny + 0.62 * nz) / 0.98); // light from the top left
    const tone = 0.18 + 0.82 * lit;
    if (tone > (BAYER[(y % 4) * 4 + (x % 4)] + 0.5) / 16) CELLS.push([x, y]);
  }
}

export function SunMark({ size = 24, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${N} ${N}`}
      aria-hidden
      className={`shrink-0 text-[#fa8023] [.dark_&]:text-[#DF3F00] ${className}`}
    >
      {CELLS.map(([x, y]) => (
        <circle key={`${x}-${y}`} cx={x + 0.5} cy={y + 0.5} r="0.42" fill="currentColor" />
      ))}
    </svg>
  );
}
