#!/usr/bin/env python3
"""Build the payload the shim loads: kernel image + Apple device tree + ramdisk + command line.

Layout (little endian), offsets from the start of the payload:
  0x000 char[8] "LVPAYLD1"
  0x008 u64 total_size
  0x010 u64 virt_base      kernel virtual address that maps to phys_base
  0x018 u64 entry_va
  0x020 u64 phys_base      RAM handed to the kernel
  0x028 u64 mem_size
  0x030 u64 image_off, image_size, image_va, image_memsize
  0x050 u64 adt_off, adt_size
  0x060 u64 ramdisk_off, ramdisk_size
  0x070 u64 reserved[2]
  0x080 char[608] command line
  0x1000 data

The shim copies the image to phys_base + (image_va - virt_base), zero-fills up to image_memsize,
then places ramdisk, ADT and boot_args after it on 16K boundaries.

For now only a flat image is supported (--flat): the self-test. Mach-O kernels come with stage E3.
"""
import argparse
import struct
from pathlib import Path

HEADER = 0x1000
BLOCK_32M = 0x2000000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--flat", required=True, help="flat binary, position independent")
    ap.add_argument("--image-va", type=lambda s: int(s, 0), default=0xFFFFFFF007004000)
    ap.add_argument("--memsize", type=lambda s: int(s, 0), default=0, help="size in RAM, at least the file size")
    ap.add_argument("--adt")
    ap.add_argument("--ramdisk")
    ap.add_argument("--cmdline", default="")
    ap.add_argument("--phys-base", type=lambda s: int(s, 0), default=0x100000000)
    ap.add_argument("--mem-size", type=lambda s: int(s, 0), default=0x7E000000)
    a = ap.parse_args()

    image = Path(a.flat).read_bytes()
    adt = Path(a.adt).read_bytes() if a.adt else b""
    ramdisk = Path(a.ramdisk).read_bytes() if a.ramdisk else b""
    cmdline = a.cmdline.encode()
    assert len(cmdline) < 608, "command line too long"

    def pad(b):
        return b + b"\0" * (-len(b) % 16)

    parts, off = [], HEADER
    offsets = []
    for blob in (image, adt, ramdisk):
        offsets.append(off)
        parts.append(pad(blob))
        off += len(parts[-1])
    virt_base = a.image_va & ~(BLOCK_32M - 1)       # one 16K-granule L2 block below the image
    hdr = struct.pack(
        "<8s15Q", b"LVPAYLD1", off,
        virt_base, a.image_va, a.phys_base, a.mem_size,
        offsets[0], len(image), a.image_va, max(a.memsize, len(image)),
        offsets[1], len(adt),
        offsets[2], len(ramdisk),
        0, 0,
    ) + cmdline
    Path(a.out).write_bytes(hdr.ljust(HEADER, b"\0") + b"".join(parts))
    print(f"{a.out}: {off} bytes, virt_base 0x{virt_base:x}, image 0x{len(image):x}, adt 0x{len(adt):x}, "
          f"ramdisk 0x{len(ramdisk):x}")


if __name__ == "__main__":
    main()
