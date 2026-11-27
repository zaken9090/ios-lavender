#!/usr/bin/env python3
"""Press Power (lv:power) N times, GAP seconds apart, with the kernel log of that time saved to OUT.
usage: powerlog.py OUT [-n 2] [--gap 6]"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench      # noqa: E402
import usblog     # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("-n", type=int, default=2)
    ap.add_argument("--gap", type=float, default=6)
    a = ap.parse_args()
    path = usblog.device_path()
    if path is None:
        print("powerlog: no device", file=sys.stderr)
        return 2
    phone = usblog.Phone(path)
    log = open(a.out, "wb")
    rd = bench.Reader(phone, log)
    rd.start()
    try:
        time.sleep(1)
        for _ in range(a.n):
            log.write(b"\n=== lv:power ===\n")
            bench.cmd(phone, "lv:power", a.gap)
    finally:
        phone.close()
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
