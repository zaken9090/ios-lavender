#!/usr/bin/env python3
"""Where a frame's pixels go, from an eagl GL trace (boot-args gltrace_at=S gltrace_frames=N).

Every glDrawElements/glDrawArrays line of the trace is followed by "program P, framebuffer F,
textures ..." and its corners ("corner K: [0] X Y ..." - positions in the target's pixels). The area
of a draw is taken as the corners' bounding box clipped to the target (one quad per 6 indices; a draw
with more indices is counted as count/6 quads of that box - an upper bound), the scissor (glScissor /
glEnable 0xc11) applied when on. Summed by target size, per traced frame (one "---- frame" = one
flush), and the blits eagl makes itself are not in a trace (preserve, copy out).

usage: tracearea.py TRACE [--top 15]
"""
import argparse
import collections
import re

DRAW = re.compile(r"gl: glDraw(Elements|Arrays)\((0x[0-9a-f]+), (\d+)(?:, (0x[0-9a-f]+))?")
INFO = re.compile(r"gl:\s+program (\d+), framebuffer (\d+), textures (.*)")
CORNER = re.compile(r"gl:\s+corner \d: \[0\] (-?[\d.]+) (-?[\d.]+)")
FBSIZE = re.compile(r"gl:\s+framebuffer (\d+) \((\d+) x (\d+)\)")
SCISSOR = re.compile(r"gl: glScissor\((-?\d+), (-?\d+), (\d+), (\d+)\)")
ENABLE = re.compile(r"gl: gl(Enable|Disable)\((0x[0-9a-f]+)\)")
FRAME = re.compile(r"gl: ---- frame (\d+)")
TEX = re.compile(r"\[\d\] (\d+) \((\d+) x (\d+)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    lines = open(a.trace, "rb").read().decode("utf-8", "replace").splitlines()
    scissor, boxed = None, False
    frames = 0
    by_target = collections.Counter()
    draws_by_target = collections.Counter()
    by_program = collections.Counter()
    by_texture = collections.Counter()
    pending = None          # (count, mode) of the draw whose info/corners follow
    info = None
    corners = []
    total = 0

    def finish():
        nonlocal pending, info, corners, total
        if pending is None or info is None or not corners:
            pending, info, corners = None, None, []
            return
        prog, fb, w, h, tex = info
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        x0, x1 = max(0, min(xs)), min(w, max(xs))
        y0, y1 = max(0, min(ys)), min(h, max(ys))
        if boxed and scissor:
            sx, sy, sw, sh = scissor
            x0, x1 = max(x0, sx), min(x1, sx + sw)
            y0, y1 = max(y0, sy), min(y1, sy + sh)
        area = max(0, x1 - x0) * max(0, y1 - y0)
        count, mode = pending
        quads = max(1, count // 6) if mode == 4 else 1
        area *= quads
        key = f"{w}x{h}"
        by_target[key] += area
        draws_by_target[key] += 1
        by_program[prog] += area
        if tex:
            by_texture[tex] += area
        total += area
        pending, info, corners = None, None, []

    for ln in lines:
        m = FRAME.search(ln)
        if m:
            finish()
            frames += 1
            continue
        m = DRAW.search(ln)
        if m:
            finish()
            pending = (int(m.group(3)) if m.group(1) == "Elements" else int(m.group(3)), int(m.group(2), 16))
            continue
        m = INFO.search(ln)
        if m and pending is not None:
            t = TEX.findall(m.group(3))
            info = [m.group(1), m.group(2), 0, 0, f"{t[0][1]}x{t[0][2]}" if t else ""]
            continue
        m = CORNER.search(ln)
        if m and pending is not None:
            corners.append((float(m.group(1)), float(m.group(2))))
            continue
        m = FBSIZE.search(ln)
        if m and info is not None and m.group(1) == info[1]:
            info[2], info[3] = int(m.group(2)), int(m.group(3))
            finish()
            continue
        m = SCISSOR.search(ln)
        if m:
            scissor = tuple(int(g) for g in m.groups())
            continue
        m = ENABLE.search(ln)
        if m and m.group(2) == "0xc11":
            boxed = m.group(1) == "Enable"
    finish()
    screen = 1125 * 2436
    print(f"{frames} traced frames (flushes), {total / 1e6:.1f} Mpx drawn = {total / screen:.1f} screens"
          f" ({total / max(frames, 1) / 1e6:.2f} Mpx a flush)")
    print("by target size (Mpx, draws):")
    for k, v in by_target.most_common(a.top):
        print(f"  {k:>12}: {v / 1e6:7.1f} Mpx  {draws_by_target[k]:5d} draws")
    print("by program (Mpx):", ", ".join(f"{k}: {v / 1e6:.1f}" for k, v in by_program.most_common(a.top)))
    print("by first texture size (Mpx):", ", ".join(f"{k}: {v / 1e6:.1f}" for k, v in by_texture.most_common(a.top)))


if __name__ == "__main__":
    main()
