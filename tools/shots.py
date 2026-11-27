#!/usr/bin/env python3
"""Screenshots only: N pictures, one every INTERVAL seconds, nothing pressed or swiped (for the user's
own gestures). usage: shots.py TAG [-n 30] [--interval 0.2]"""
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
    ap.add_argument("-n", type=int, default=30)
    ap.add_argument("--interval", type=float, default=0.2)
    a = ap.parse_args()
    path = usblog.device_path()
    if path is None:
        print("shots: no device", file=sys.stderr)
        return 2
    phone = usblog.Phone(path)
    rd = bench.Reader(phone, None)
    rd.start()
    t0 = time.time()
    try:
        for i in range(a.n):
            bench.screenshot(phone, rd, f"ui_{a.tag}_{i:02d}_{int((time.time() - t0) * 1000):05d}.png")
            time.sleep(a.interval)
    finally:
        phone.close()
    print(f"shots: {a.n} in {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
