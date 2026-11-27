#!/usr/bin/env python3
"""backboardd CPU per presented frame from a log with SMC (sweetsample=zz) and SWEET FPS lines.

usage: cpuframe.py LOG
"""
import re
import sys

t = open(sys.argv[1], 'rb').read().decode('utf-8', 'replace')
cpu = [int(m.group(1)) for m in re.finditer(r'SMC \d+ ms: all \d+ \|[^\n]*? backboardd (\d+)', t)]
fr = [int(m.group(1)) for m in re.finditer(r'SWEET FPS: (\d+) frames', t)]
if not cpu or not fr:
    print('no data', len(cpu), len(fr))
    sys.exit(1)
cpu = cpu[1:-1] or cpu          # (the windows at both ends are partly idle)
pct = sum(cpu) / len(cpu)
fps = sum(fr) / len(fr)
print(f'backboardd {pct:.1f}% of a core, {fps:.1f} fps -> {pct * 10 / max(fps, 1):.2f} ms CPU a frame ({len(cpu)} windows)')
