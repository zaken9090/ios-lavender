#!/usr/bin/env python3
"""Screenshots of the running phone: the lock screen, then the screen after an unlock swipe.

Wakes the display (Power, until the kernel logs "display on"), saves the lock screen, swipes up,
saves what is there (an alert is left alone so that it is in the picture), then runs the optional
steps and saves a picture after each. Every picture is saved whole and as a crop of its top
200 rows (the status bar), in RedmiNote7\\screenshots.

usage: uishot.py TAG [--log FILE] [--steps "tap 736 1373; swipe 540 2200 540 900 250; wait 2"]
"""
import argparse
import os
import sys
import time

import bench
import usblog

SHOTS = bench.SHOTS


def save(shot, name):
    raw, w, h, stride = shot
    os.makedirs(SHOTS, exist_ok=True)
    usblog.save_png(os.path.join(SHOTS, name + ".png"), raw, w, h, stride)
    usblog.save_png(os.path.join(SHOTS, name + "_top.png"), raw[:200 * stride], w, 200, stride)
    print(os.path.join(SHOTS, name + ".png"))


def wake(phone, rd):
    """Power until iOS says the display is on (it locks an awake screen, so look at the answer)."""
    for _ in range(2):
        m = rd.mark()
        bench.cmd(phone, "lv:power", 0.5)
        got = b""
        for _ in range(12):
            got = rd.since(m)
            if b"display on" in got or b"display off" in got:
                break
            time.sleep(0.5)
        if b"display on" in got:
            time.sleep(1.5)
            return True
        if b"display off" not in got:
            return False
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--log")
    ap.add_argument("--steps", default="")
    a = ap.parse_args()

    path = usblog.device_path()
    if path is None:
        print("uishot: no device", file=sys.stderr)
        return 2
    phone = usblog.Phone(path)
    log = open(a.log, "ab") if a.log else None
    rd = bench.Reader(phone, log)
    rd.start()
    try:
        time.sleep(1.0)
        # the display goes off ~10 s after a wake, and a picture takes seconds over USB: unlock first
        wake(phone, rd)
        bench.cmd(phone, "lv:swipe 540 2200 540 900 250", 4.5)
        shot = bench.screenshot(phone, rd, None)
        if shot:
            save(shot, f"ui_{a.tag}_2_unlocked")
        bench.cmd(phone, "lv:power", 2.0)               # lock, then wake for the lock screen
        wake(phone, rd)
        shot = bench.screenshot(phone, rd, None)
        if shot:
            save(shot, f"ui_{a.tag}_1_lock")
        n = 3
        for step in [s.strip() for s in a.steps.split(";") if s.strip()]:
            if step.startswith("wait"):
                time.sleep(float(step.split()[1]))
                continue
            bench.cmd(phone, "lv:" + step, 2.0)
            shot = bench.screenshot(phone, rd, None)
            if shot:
                save(shot, f"ui_{a.tag}_{n}_{step.split()[0]}")
            n += 1
    finally:
        phone.close()
        if log:
            log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
