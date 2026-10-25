"""Write public/img/sun.svg, the favicon: the same dithered sun as components/sun-mark.tsx."""
import math, os

N, BAYER = 16, [0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5]
cells = []
for y in range(N):
    for x in range(N):
        nx, ny = (x + 0.5) / (N / 2) - 1, (y + 0.5) / (N / 2) - 1
        r2 = nx * nx + ny * ny
        if r2 > 1:
            continue
        lit = max(0, (-0.5 * nx - 0.6 * ny + 0.62 * math.sqrt(1 - r2)) / 0.98)
        if 0.18 + 0.82 * lit > (BAYER[(y % 4) * 4 + x % 4] + 0.5) / 16:
            cells.append(f'<rect x="{x}" y="{y}" width="1" height="1"/>')
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {N} {N}" shape-rendering="crispEdges" fill="#ea5a0c">'
       + "".join(cells) + "</svg>\n")
open(os.path.join(os.path.dirname(__file__), "..", "public", "img", "sun.svg"), "w").write(svg)
