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
        for attempt in range(4):
            shot = screenshot(phone, rd, None)
            if shot and is_home(shot):
                home = True
                break
            if attempt % 2 == 1 or attempt == 0:
                cmd(phone, "lv:power", 1.5)
            cmd(phone, "lv:swipe 540 2320 540 1100 250", 2.5)
        screenshot(phone, rd, f"bench_{a.tag}_{stamp}_home.png")
        if not home:
            print("bench: NOT UNLOCKED (see the screenshot)", file=sys.stderr)

        m = rd.mark()
        for _ in range(3):
            cmd(phone, "lv:swipe 950 1300 150 1300 400", 2.0)   # to the widgets page
            cmd(phone, "lv:swipe 150 1300 950 1300 400", 2.0)   # back
        home_log = rd.since(m)

        cmd(phone, "lv:tap %d %d" % SETTINGS_ICON, 3.0)
        m = rd.mark()
        for _ in range(3):
            cmd(phone, "lv:swipe 540 1900 540 600 500", 1.5)
            cmd(phone, "lv:swipe 540 600 540 1900 500", 1.5)
        settings_log = rd.since(m)
        screenshot(phone, rd, f"bench_{a.tag}_{stamp}_settings.png")
        cmd(phone, "lv:swipe 540 2330 540 1500 200", 2.0)     # home
    finally:
        phone.close()
        if log:
            log.close()

    line = (f"BENCH {a.tag} {stamp} {'' if home else 'NOT-UNLOCKED '}"
            f"home: {fps_stats(home_log)} | settings: {fps_stats(settings_log)}")
    print(line)
    with open(a.results, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return 0 if home else 1


if __name__ == "__main__":
    sys.exit(main())
