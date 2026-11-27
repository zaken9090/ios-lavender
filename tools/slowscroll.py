#!/usr/bin/env python3
"""Frame pacing from SWEET FPS lines: usage slowscroll.py LOG (seconds with at least 20 frames only)."""
import re
import sys

t = open(sys.argv[1], 'rb').read().decode('utf-8', 'replace')
rows = []
for m in re.finditer(r'SWEET FPS: (\d+) frames in (\d+) ms, longest gap (\d+) ms, (\d+) late;.*?gaps (\d+)/(\d+)/(\d+)/(\d+)', t):
    f, ms, lg, late, g1, g2, g3, g4 = map(int, m.groups())
    if f >= 20:
        rows.append((f, lg, late, g1, g2, g3, g4))
if not rows:
    print('no data')
    sys.exit(1)
n = len(rows)
fr = sum(r[0] for r in rows)
g = [sum(r[k] for r in rows) for k in range(3, 7)]
print(f'{n} s: {fr / n:.1f} fps, longest gap avg {sum(r[1] for r in rows) / n:.0f} ms, late {100 * sum(r[2] for r in rows) / fr:.0f}%,'
      f' gaps 1/2/3/more periods {g[0]}/{g[1]}/{g[2]}/{g[3]}')
