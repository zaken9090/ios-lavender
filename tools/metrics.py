#!/usr/bin/env python3
"""The kernel's per-second numbers (patch 1160: LVM / LVP / LVK lines, with SWEET FPS) as a table.

usage: metrics.py LOG [--csv OUT.csv] [--rows] [--from N] [--to N]
Prints mean / min / max of every number over the log (or its seconds N..M), the processes by mean
CPU, and with --rows every second. --csv writes one row a second for a spreadsheet.

  cpu0-3  busy share of each Gold core, %      run     load average (1000 = runnable threads == cores)
  gold    Gold cluster clock, MHz              t0-3    core temperatures, tgpu, tmax (hottest sensor)
  gpu     GPU busy share, %                    sub     GPU submissions in the second
  free/wired/act/inact/comp  memory, MB        lvl     memorystatus level
  mv/ma   battery voltage and current (+ = discharging)
  fps/late/wait  from the SWEET FPS line of the same second (frames, late frames, GPU wait us a frame)
  g_*     the GPU's own counters (LVG line): g_lat = cycles a memory request waits, g_misspct = texture
          cache misses, g_alupct = share of the shader's busy time it computes, g_kbeat_f / g_kpix_f =
          thousand memory beats read / thousand pixels passed per frame
"""
import argparse
import csv
import re
import sys

LVM = re.compile(
    rb"LVM (\d+) ms: cpu (\d+) (\d+) (\d+) (\d+) \| run (\d+) \| gold (\d+) MHz \| t (-?\d+) (-?\d+) (-?\d+) (-?\d+) gpu (-?\d+) max (-?\d+)"
    rb" \| gpu (?:(\d+)% (\d+) MHz sub (\d+) rec (\d+)/(\d+)|-)"
    rb" \| mem free (\d+) wired (\d+) act (\d+) inact (\d+) comp (-?\d+) MB lvl (\d+)"
    rb" \| bat (?:(-?\d+) mV (-?\d+) mA|-)")
LVM_KEYS = ("ms", "cpu0", "cpu1", "cpu2", "cpu3", "run", "gold", "t0", "t1", "t2", "t3", "tgpu", "tmax",
            "gpu", "gpumhz", "sub", "rec", "recfail", "free", "wired", "act", "inact", "comp", "lvl", "mv", "ma")
LVP = re.compile(rb"LVP (\d+) ms: all (\d+) \|(.*)")
LVG = re.compile(rb"LVG (\d+) ms: (.*)")
LVK = re.compile(rb"LVK khz (\d+) (\d+) (\d+) (\d+)")
FPS = re.compile(rb"SWEET FPS: (\d+) frames in (\d+) ms, longest gap (\d+) ms, (\d+) late;.*?GPU waited (\d+) us a frame")


def parse(data):
    """One dict a second (an LVM line closes the second; FPS / LVP / LVK lines before it belong to it)."""
    rows, cur = [], {}
    for line in data.splitlines():
        m = FPS.search(line)
        if m:
            f, ms, gap, late, wait = map(int, m.groups())
            cur.update(fps=round(f * 1000.0 / ms, 1) if ms else 0, gapms=gap, late=late, wait=wait)
            continue
        m = LVK.search(line)
        if m:
            for i, v in enumerate(m.groups()):
                cur[f"khz{i}"] = int(v)
            continue
        m = LVP.search(line)
        if m:
            words = m.group(3).decode("ascii", "replace").split()
            top = {}
            for name, pct in zip(words[0::2], words[1::2]):
                if pct.isdigit():
                    top[name] = int(pct)
            if rows:
                rows[-1]["all"] = int(m.group(2))
                rows[-1]["top"] = top
            continue
        m = LVG.search(line)
        if m:
            # the GPU's own counters (xnu 1164), change over the second: g_<name>
            words = [w for w in m.group(2).decode("ascii", "replace").split() if w != "|"]
            if rows:
                for name, val in zip(words[0::2], words[1::2]):
                    if val.isdigit():
                        rows[-1]["g_" + name] = int(val)
                g = rows[-1]
                frames = g.get("fps", 0) * g.get("ms", 1000) / 1000.0
                if g.get("g_latn"):
                    g["g_lat"] = round(g["g_latcyc"] / g["g_latn"], 1)            # cycles a memory request
                if g.get("g_tpreq"):
                    g["g_misspct"] = round(100.0 * g["g_tpmiss"] / g["g_tpreq"], 1)
                if g.get("g_spbusy"):
                    g["g_alupct"] = round(100.0 * g.get("g_spalu", 0) / g["g_spbusy"], 1)
                if frames >= 3:
                    g["g_kbeat_f"] = round((g.get("g_tpbeat", 0) + g.get("g_spbeat", 0)) / frames / 1000)
                    g["g_kpix_f"] = round(g.get("g_rbpass", 0) / frames / 1000)
            continue
        m = LVM.search(line)
        if m:
            for k, v in zip(LVM_KEYS, m.groups()):
                if v is not None:
                    cur[k] = int(v)
            cur["cpu"] = cur["cpu0"] + cur["cpu1"] + cur["cpu2"] + cur["cpu3"]
            cur["core"] = max(cur["cpu0"], cur["cpu1"], cur["cpu2"], cur["cpu3"])
            rows.append(cur)
            cur = {}
    return rows


COLS = ("fps", "late", "wait", "cpu", "core", "cpu0", "cpu1", "cpu2", "cpu3", "all", "run", "gold", "gpu", "sub",
        "t0", "t1", "t2", "t3", "tgpu", "tmax", "free", "wired", "act", "inact", "comp", "lvl", "mv", "ma", "rec", "recfail")


def stats(rows, key):
    vals = [r[key] for r in rows if key in r]
    if not vals:
        return None
    return sum(vals) / len(vals), min(vals), max(vals), len(vals)


def short(rows):
    """A few numbers of a phase for the BENCH line."""
    out = []
    for key, fmt in (("cpu", "cpu %.0f%%"), ("core", "top core %.0f%%"), ("gpu", "gpu %.0f%%"), ("tmax", "%.0f C"), ("ma", "%.0f mA")):
        s = stats(rows, key)
        if s:
            out.append(fmt % s[0])
    # the GPU's work per frame (xnu 1164), compared from run to run (user, 2026-11-27): million pixels
    # passed a frame, cycles a memory request waits, texture cache misses
    s = stats(rows, "g_kpix_f")
    if s:
        out.append("%.1f Mpx/frame" % (s[0] / 1000))
    s = stats(rows, "g_lat")
    if s:
        out.append("mem wait %.0f cyc" % s[0])
    s = stats(rows, "g_misspct")
    if s:
        out.append("tex miss %.0f%%" % s[0])
    return ", ".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--csv")
    ap.add_argument("--rows", action="store_true")
    ap.add_argument("--from", dest="first", type=int, default=0)
    ap.add_argument("--to", dest="last", type=int)
    a = ap.parse_args()
    rows = parse(open(a.log, "rb").read())[a.first:a.last]
    if not rows:
        print("metrics: no LVM lines")
        return 1
    print(f"{len(rows)} seconds")
    gkeys = sorted({k for r in rows for k in r if k.startswith("g_")})
    for key in COLS + tuple(gkeys):
        s = stats(rows, key)
        if s:
            print(f"  {key:8} mean {s[0]:9.1f}   min {s[1]:7.0f}   max {s[2]:7.0f}   ({s[3]} s)")
    khz = [[r[f"khz{i}"] for r in rows if f"khz{i}" in r] for i in range(4)]
    if khz[0]:
        print("  measured clock, MHz: " + "  ".join(f"cpu{i} {min(k) / 1000:.0f}..{max(k) / 1000:.0f}" for i, k in enumerate(khz) if k))
    tot = {}
    for r in rows:
        for name, pct in r.get("top", {}).items():
            tot[name] = tot.get(name, 0) + pct
    if tot:
        print("  CPU by process (mean % of one core): " +
              ", ".join(f"{n} {v / len(rows):.0f}" for n, v in sorted(tot.items(), key=lambda x: -x[1])[:10]))
    if a.rows:
        show = ("fps", "late", "cpu0", "cpu1", "cpu2", "cpu3", "run", "gpu", "tmax", "free", "comp", "ma")
        print("  " + " ".join(f"{k:>5}" for k in show))
        for r in rows:
            print("  " + " ".join(f"{r.get(k, ''):>5}" for k in show))
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(COLS + ("khz0", "khz1", "khz2", "khz3", "top"))
            for r in rows:
                w.writerow([r.get(k, "") for k in COLS] + [r.get(f"khz{i}", "") for i in range(4)] +
                           [" ".join(f"{n}={v}" for n, v in r.get("top", {}).items())])
    return 0


if __name__ == "__main__":
    sys.exit(main())
