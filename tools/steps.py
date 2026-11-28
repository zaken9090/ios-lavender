#!/usr/bin/env python3
"""Drive the running phone through a list of steps, logging everything (bench.py's reader).

iOS turns the display off after ~10 s idle and the framebuffer keeps the last frame, so a screenshot
looks normal while touches only wake the screen: "wake" presses Power until the kernel logs
"display on" (or finds it on already: then a touch keeps it on).

usage: steps.py TAG --log FILE "wake; unlock; tap 894 524; wait 10; shot msg; cmd lv:swipe ...; fastboot"
steps: wake | unlock (wake, swipe up, tap the cellular alert's OK) | tap X Y | swipe X1 Y1 X2 Y2 MS [HOLD]
       | cmd TEXT | wait S | shot NAME (screenshots\\ui_TAG_NAME.png) | fastboot
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench      # noqa: E402
import usblog     # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("steps")
    ap.add_argument("--log")
    a = ap.parse_args()
    path = usblog.device_path()
    if path is None:
        print("steps: no device", file=sys.stderr)
        return 2
    phone = usblog.Phone(path)
    log = open(a.log, "ab") if a.log else None
    rd = bench.Reader(phone, log)
    rd.start()

    def wake():
        # Power wakes a dark screen but locks an awake one: pressed only when the kernel's last word
        # (the log since connecting holds the backlog) was "display off"
        time.sleep(0.5)
        everything = rd.since(0)
        if everything.rfind(b"display off") <= everything.rfind(b"display on"):
            return
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
                return

    try:
        time.sleep(1)
        for step in [s.strip() for s in a.steps.split(";") if s.strip()]:
            w = step.split()
            print("step:", step, flush=True)
            if w[0] == "wake":
                wake()
            elif w[0] == "unlock":
                wake()
                bench.cmd(phone, "lv:swipe 540 2200 540 900 250", 4.5)
                bench.cmd(phone, "lv:tap 736 1373", 1.5)
            elif w[0] in ("tap", "swipe"):
                # the kernel moves the finger inside the USB handler: the next command waits for it
                held = (int(w[5]) + int(w[6] if len(w) > 6 else 0)) / 1000.0 if w[0] == "swipe" else 0
                bench.cmd(phone, "lv:" + step, 0.6 + held)
            elif w[0] == "cmd":
                bench.cmd(phone, step[4:], 0.5)
            elif w[0] == "wait":
                time.sleep(float(w[1]))
            elif w[0] == "shot":
                bench.screenshot(phone, rd, f"ui_{a.tag}_{w[1]}.png")
            elif w[0] == "fastboot":
                bench.cmd(phone, "lv:fastboot", 2)
                break
            else:
                print("steps: unknown step", step, file=sys.stderr)
    finally:
        phone.close()
        if log:
            log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
