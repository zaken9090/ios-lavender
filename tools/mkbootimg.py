#!/usr/bin/env python3
"""Pack an Android boot image, header v1, the way the stock lavender boot.img is laid out:
kernel = gzip(Image) + appended DTB, no ramdisk.

usage: mkbootimg.py Image dtb out.img [--cmdline "..."]
"""
import argparse
import gzip
import struct
from pathlib import Path

PAGE = 4096


def pad(b):
    return b + b"\0" * (-len(b) % PAGE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("dtb")
    ap.add_argument("out")
    ap.add_argument("--cmdline", default="")
    a = ap.parse_args()

    kernel = gzip.compress(Path(a.image).read_bytes(), 9, mtime=0) + Path(a.dtb).read_bytes()
    hdr = struct.pack(
        "<8s10I16s512s32s1024sIQI",
        b"ANDROID!",
        len(kernel), 0x8000,        # kernel size, load address
        0, 0x1000000,               # ramdisk
        0, 0xF00000,                # second
        0x100, PAGE,                # tags address, page size
        1, 0,                       # header version, os version
        b"", a.cmdline.encode(), b"", b"",
        0, 0, 1648,                 # recovery dtbo size, offset, header size
    )
    Path(a.out).write_bytes(pad(hdr) + pad(kernel))
    print(f"{a.out}: kernel+dtb 0x{len(kernel):x} bytes")


if __name__ == "__main__":
    main()
