#!/usr/bin/env python3
"""Smoothness of a bench log: late frames and gaps, not the average fps.

Reads the kernel's "SWEET FPS: N frames in T ms, longest gap G ms, L late; ...; gaps a/b/c/d" lines
(a/b/c/d = frames that came 1 / 2 / 3 / more panel periods after the one before) and, for each, the
LVM line nearest before it (CPU load of the four cores, GPU busy share and clock).
Seconds are grouped by frame count: "smooth" (>= 45 frames: Settings-like scrolling) and "slow"
(8..44: the home screen / App Library). For each group: seconds, frames, share of frames that were
late (b+c+d), the worst gap, the share of seconds with no late frame, mean CPU and GPU load.
With the governor's LVF lines (xnu 1174) the share of time at each Gold clock is given.
With eagl's glsumstat=1 lines ("redwood-gl: sums: ...") the surface sums per second are added up too.

usage: late.py LOG [LOG...]
"""
import re
import sys

FPS = re.compile(r"SWEET FPS: (\d+) frames in (\d+) ms, longest gap (\d+) ms, (\d+) late.*?gaps (\d+)/(\d+)/(\d+)/(\d+)")
LVM = re.compile(r"LVM \d+ ms: cpu (\d+) (\d+) (\d+) (\d+) .*?gpu (\d+)% (\d+) MHz")
SUMS = re.compile(r"redwood-gl: sums: (.*)")
LVF = re.compile(r"LVF \d+ ms: 1113 (\d+)% 1401 (\d+)% 1747 (\d+)% 1958 (\d+)% 2150 (\d+)% 2208 (\d+)% \| (\d+) ups (\d+) downs (\d+) touch")
KIND = re.compile(r"(own small|own big|wrapped small|wrapped big) (\d+) looks (\d+) KB (\d+) us (\d+) changed")


def main():
    for path in sys.argv[1:]:
        text = open(path, "rb").read().decode("utf-8", "replace")
        groups = {"smooth": [], "slow": []}
        cpu = gpu = mhz = 0
        for line in text.splitlines():
            m = LVM.search(line)
            if m:
                cpu = sum(int(x) for x in m.groups()[:4])
                gpu, mhz = int(m.group(5)), int(m.group(6))
                continue
            m = FPS.search(line)
            if not m:
                continue
            n, ms, gap, late, a, b, c, d = map(int, m.groups())
            if n >= 45:
                groups["smooth"].append((n, gap, b + c + d, cpu, gpu, mhz))
            elif n >= 8:
                groups["slow"].append((n, gap, b + c + d, cpu, gpu, mhz))
        print(path)
        for name, rows in groups.items():
            if not rows:
                continue
            frames = sum(r[0] for r in rows)
            late = sum(r[2] for r in rows)
            clean = sum(1 for r in rows if r[2] == 0)
            print(f"  {name:6}: {len(rows):3d} s, {frames / len(rows):5.1f} fps, late {late} of {frames} frames "
                  f"({100.0 * late / frames:.1f} %), worst gap {max(r[1] for r in rows)} ms, "
                  f"{100.0 * clean / len(rows):.0f} % of seconds clean, cpu {sum(r[3] for r in rows) / len(rows):.0f} %, "
                  f"gpu {sum(r[4] for r in rows) / len(rows):.0f} %")
        kinds = {}
        seconds = 0
        for m in SUMS.finditer(text):
            seconds += 1
            for k, looks, kb, us, changed in KIND.findall(m.group(1)):
                t = kinds.setdefault(k, [0, 0, 0, 0])
                for i, v in enumerate((looks, kb, us, changed)):
                    t[i] += int(v)
        lvf = [tuple(map(int, m.groups())) for m in LVF.finditer(text)]
        if lvf:
            n = len(lvf)
            share = [sum(r[i] for r in lvf) / n for i in range(6)]
            print(f"  Gold clock over {n} s: " + ", ".join(f"{mhz} {v:.0f} %" for mhz, v in zip((1113, 1401, 1747, 1958, 2150, 2208), share))
                  + f"; {sum(r[6] for r in lvf) / n:.1f} ups {sum(r[7] for r in lvf) / n:.1f} downs a second, {sum(r[8] for r in lvf)} touch boosts")
        if seconds:
            print(f"  surface sums over {seconds} s:", "; ".join(
                f"{k} {v[0] / seconds:.0f} looks {v[1] / seconds / 1024:.1f} MB {v[2] / seconds / 1000:.1f} ms a second, "
                f"{v[3]} changed" for k, v in kinds.items()))


if __name__ == "__main__":
    main()
