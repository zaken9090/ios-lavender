#!/usr/bin/env python3
"""Automated smoothness bench on the phone over the USB log (xnu patches 1001, 1005, 1007; boot-arg sweetfps=1).

One process holds the WinUSB device: a reader thread keeps the log (and screenshots), the main
thread drives the UI with lv:power / lv:swipe / lv:tap and then averages the kernel's
"SWEET FPS: N frames in T ms" lines per phase (seconds with more than 2 frames only: an idle
second says nothing about smoothness).

  python bench.py TAG [--log FILE] [--settle 20] [--results ..\\dump\\bench-results.txt]

Phases: unlock (Power + swipe up, checked on a screenshot), home (6 horizontal swipes), settings
(open Settings, 6 scrolls down/up), back home. Prints and appends one line:
  BENCH <tag> <date> home: <mean> fps (max <max>, <n> s) | settings: <mean> fps (max <max>, <n> s)
"""
import argparse
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics  # noqa: E402
import usblog  # noqa: E402

FPS_LINE = re.compile(rb"SWEET FPS: (\d+) frames in (\d+) ms")
HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "..", "..", "screenshots")

# panel pixels (1080x2340); Settings is the first icon of the second row on the stock home screen
SETTINGS_ICON = (164, 565)


class Reader(threading.Thread):
    def __init__(self, phone, log):
        super().__init__(daemon=True)
        self.phone, self.log = phone, log
        self.buf = bytearray()          # whole log of this run
        self.shot = None                # bytearray while a screenshot is expected
        self.shot_done = threading.Event()
        self.shot_raw = None
        self.error = None
        self.lock = threading.Lock()

    def run(self):
        try:
            while True:
                data = self.phone.read()
                if not data:
                    continue
                if self.shot is not None:
                    self.shot += data
                    m = usblog.SHOT_HEADER.search(self.shot)
                    if m:
                        w, h, stride, size = map(int, m.groups())
                        if len(self.shot) - m.end() >= size:
                            self.shot_raw = (bytes(self.shot[m.end():m.end() + size]), w, h, stride)
                            data = bytes(self.shot[:m.start()]) + bytes(self.shot[m.end() + size:])
                            self.shot = None
                            self.shot_done.set()
                        else:
                            continue
                    else:
                        continue
                with self.lock:
                    self.buf += data
                if self.log:
                    self.log.write(data)
                    self.log.flush()
        except OSError as e:
            self.error = e

    def mark(self):
        with self.lock:
            return len(self.buf)

    def since(self, mark):
        with self.lock:
            return bytes(self.buf[mark:])


def screenshot(phone, rd, name):
    rd.shot_done.clear()
    rd.shot = bytearray()
    phone.write(b"lv:shot")
    if not rd.shot_done.wait(20):
        rd.shot = None
        print("bench: no screenshot", file=sys.stderr)
        return None
    raw, w, h, stride = rd.shot_raw
    if name:
        os.makedirs(SHOTS, exist_ok=True)
        usblog.save_png(os.path.join(SHOTS, name), raw, w, h, stride)
    return raw, w, h, stride


def pixel(shot, x, y):
    raw, w, h, stride = shot
    o = y * stride + x * 4
    b, g, r = raw[o], raw[o + 1], raw[o + 2]       # panel memory is BGRA
    return r, g, b


def is_home(shot):
    """The dock: a light band near the bottom (rows ~88-97 %), lighter than the wallpaper above."""
    raw, w, h, stride = shot

    def mean(y0, y1):
        tot = n = 0
        for y in range(int(h * y0), int(h * y1), 12):
            for x in range(80, w - 80, 24):
                tot += sum(pixel(shot, x, y))
                n += 1
        return tot / n / 3

    dock, wall = mean(0.885, 0.955), mean(0.60, 0.70)
    return dock > 150 and dock > wall + 40


def cmd(phone, text, wait):
    phone.write(text.encode())
    time.sleep(wait)


def fps_stats(log):
    vals = [int(f) * 1000.0 / int(ms) for f, ms in FPS_LINE.findall(log) if int(f) > 2 and int(ms) > 0]
    if not vals:
        return "no frames"
    return f"{sum(vals) / len(vals):.1f} fps (max {max(vals):.0f}, {len(vals)} s)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--log")
    ap.add_argument("--settle", type=float, default=20)
    ap.add_argument("--fast", action="store_true", help="the old flick swipes instead of slow finger-like drags")
    ap.add_argument("--results", default=os.path.join(HERE, "..", "..", "dump", "bench-results.txt"))
    a = ap.parse_args()

    path = usblog.device_path()
    if path is None:
        print("bench: no device", file=sys.stderr)
        return 2
    phone = usblog.Phone(path)
    log = open(a.log, "ab") if a.log else None
    rd = Reader(phone, log)
    rd.start()
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    try:
        time.sleep(a.settle)
        # unlock: Power (wakes a sleeping screen, locks an awake one, so check after each try)
        home = False
        # The swipe starts above the bottom edge band (y > 2291 is an edge contact since patch 1010,
        # which the lock screen did not take as unlock), and the unlock can take ~4 s to settle.
        # The framebuffer keeps the last frame while iOS has the display off (sweetfb_stayon), so a
        # screenshot cannot tell: Power is pressed until the kernel logs "display on" after it.
        def wake():
            for _ in range(2):
                m = rd.mark()
                cmd(phone, "lv:power", 0.5)
                got = b""
                for _ in range(12):     # iOS answers within ~2-3 s: "display on" or "display off"
                    got = rd.since(m)
                    if b"display on" in got or b"display off" in got:
                        break
                    time.sleep(0.5)
                if b"display on" in got:
                    time.sleep(1.5)
                    return
                if b"display off" not in got:
                    return              # nothing logged in 6 s: leave it
        # iOS turns an idle lock screen off within ~10 s, and a stale framebuffer still looks like
        # home: each try wakes the display, swipes at once, and counts only a home screen that new
        # frames were drawn for.
        for attempt in range(3):
            wake()
            m = rd.mark()
            cmd(phone, "lv:swipe 540 2200 540 900 250", 4.5)
            # CommCenter runs with no modem behind it (xnu 1038): iOS shows "Cellular Issue Detected"
            # once after unlock. OK is at (736, 1373); an empty spot of the home screen otherwise.
            cmd(phone, "lv:tap 736 1373", 1.5)
            shot = screenshot(phone, rd, None)
            if b"SWEET FPS" in rd.since(m) and shot and is_home(shot):
                home = True
                break
        screenshot(phone, rd, f"bench_{a.tag}_{stamp}_home.png")
        if not home:
            print("bench: NOT UNLOCKED (see the screenshot)", file=sys.stderr)

        # Default: slow drags of 2 s, a finger held on the screen the whole way, as the first lavender
        # project's bench.sh did: the app follows every step and draws each frame itself, as with the
        # user's finger. --fast: the old flicks (400/500 ms), whose rest iOS animates on its own.
        drag, wait = (400, 2.0) if a.fast else (2000, 2.6)
        m = rd.mark()
        for _ in range(3):
            cmd(phone, "lv:swipe 950 1300 150 1300 %d" % drag, wait)   # to the next page
            cmd(phone, "lv:swipe 150 1300 950 1300 %d" % drag, wait)   # back
        home_log = rd.since(m)

        cmd(phone, "lv:tap %d %d" % SETTINGS_ICON, 3.0)
        m = rd.mark()
        sdrag, swait = (500, 1.5) if a.fast else (2000, 2.6)
        for _ in range(3):
            cmd(phone, "lv:swipe 540 2000 540 500 %d" % sdrag, swait)
            cmd(phone, "lv:swipe 540 500 540 2000 %d" % sdrag, swait)
        settings_log = rd.since(m)
        screenshot(phone, rd, f"bench_{a.tag}_{stamp}_settings.png")
        cmd(phone, "lv:swipe 540 2330 540 1500 200", 2.0)     # home
    finally:
        phone.close()
        if log:
            log.close()

    # the kernel's last "temp:" line (xnu 1120/1121): GPU and hottest sensor, CPU load
    temps = re.findall(rb"temp: gpu ([-\d.]+) C, hottest ([-\d.]+) C \(sensor (\d+)\)[^,]*, load (\d+)% \(busiest cpu (-?\d+) (\d+)%\)",
                       bytes(rd.buf))
    therm = ""
    if temps:
        g, h, s, ld, c, cp = (x.decode() for x in temps[-1])
        therm = f" | gpu {g} C, hottest {h} C (s{s}), load {ld}% (cpu{c} {cp}%)"
    # per-second numbers of each phase (xnu 1160 LVM lines): CPU, busiest core, GPU, heat, battery current
    hm, sm = metrics.short(metrics.parse(home_log)), metrics.short(metrics.parse(settings_log))
    line = (f"BENCH {a.tag} {stamp} {'fast ' if a.fast else 'slow '}{'' if home else 'NOT-UNLOCKED '}"
            f"home: {fps_stats(home_log)}{' [' + hm + ']' if hm else ''} | "
            f"settings: {fps_stats(settings_log)}{' [' + sm + ']' if sm else ''}{therm}")
    print(line)
    with open(a.results, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return 0 if home else 1


if __name__ == "__main__":
    sys.exit(main())
