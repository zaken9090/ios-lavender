#!/usr/bin/env python3
"""Send lv: commands to the phone one after another and print each one's answer line.

usage: lvcmd.py "lv:peek 17812c00 12" "lv:pmic 1006 3" ...   [--wait 3] [--log FILE]
The answer is the first log line after the command that starts with "LV " (LV PEEK, LV PMIC, LV GOLD,
LV USB: ...). The log keeps running every second (LVM lines), so this does not wait for silence.
--log appends everything received to FILE.
"""
import argparse
import re
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import usblog  # noqa: E402

ANSWER = re.compile(rb"^(LV (?:PEEK|PMIC|GOLD|USB)[^\n]*)$", re.M)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmds", nargs="+")
    ap.add_argument("--wait", type=float, default=3)
    ap.add_argument("--log")
    a = ap.parse_args()
    path = usblog.device_path()
    if path is None:
        print("lvcmd: no device", file=sys.stderr)
        return 2
    phone = usblog.Phone(path)
    log = open(a.log, "ab") if a.log else None
    try:
        # the backlog the kernel sends on connect: read until it has gone quiet for a moment
        last = time.time()
        while time.time() - last < 0.4:
            data = phone.read()
            if data:
                last = time.time()
                if log:
                    log.write(data)
        for c in a.cmds:
            phone.write(c.encode())
            buf, end = b"", time.time() + a.wait
            m = None
            while time.time() < end and m is None:
                data = phone.read()
                if data:
                    buf += data
                    if log:
                        log.write(data)
                    m = ANSWER.search(buf)
                    if m and not buf[m.end():m.end() + 1]:      # the line may still be arriving
                        m = None if b"\n" not in buf[m.start():] else m
            print(f"{c} -> {m.group(1).decode('ascii', 'replace') if m else 'no answer'}")
    finally:
        phone.close()
        if log:
            log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
