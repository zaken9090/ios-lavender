#!/usr/bin/env python3
"""Build the payload the shim loads: kernel image + Apple device tree + ramdisk + command line.

usage: mkpayload.py OUT --kernel kernel.development.sweet --adt lavender.adt --cmdline "..."
       mkpayload.py OUT --flat fake.bin --cmdline "selftest=1"          (loader self-test)

Layout (little endian), offsets from the start of the payload:
  0x000 char[8] "LVPAYLD1"
  0x008 u64 total_size
  0x010 u64 virt_base      kernel virtual address that maps to phys_base
  0x018 u64 entry_va
  0x020 u64 phys_base      RAM handed to the kernel (the ADT's /chosen dram-base, dram-size)
  0x028 u64 mem_size
  0x030 u64 image_off, image_size, image_va, image_memsize
  0x050 u64 adt_off, adt_size
  0x060 u64 ramdisk_off, ramdisk_size
  0x070 u64 reserved[2]
  0x080 char[608] command line
  0x1000 data

The shim copies the image to phys_base + (image_va - virt_base), zero-fills up to image_memsize,
then places ramdisk, ADT and boot_args after it on 16K boundaries.

A Mach-O kernel is flattened here: its segments are laid out by address into one image and its
chained fixups (the linker's compact list of pointers to rebase) are resolved, because the kernel
is entered with nothing to do that for it.
"""
import argparse
import struct
from pathlib import Path

import adt

HEADER = 0x1000
BLOCK_32M = 0x2000000
PAGE_16K = 0x4000
LC_SEGMENT_64, LC_UNIXTHREAD, LC_DYLD_CHAINED_FIXUPS = 0x19, 0x5, 0x80000034


def parse_macho(buf):
    magic, _cpu, _sub, _type, ncmds = struct.unpack_from("<5I", buf, 0)
    if magic != 0xFEEDFACF:
        raise SystemExit("kernel is not a 64-bit Mach-O")
    segs, entry, fixups = [], None, None
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", buf, off)
        if cmd == LC_SEGMENT_64:
            name = buf[off + 8:off + 24].split(b"\0")[0].decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4Q", buf, off + 24)
            segs.append(dict(name=name, vmaddr=vmaddr, vmsize=vmsize, fileoff=fileoff, filesize=filesize))
        elif cmd == LC_UNIXTHREAD:
            (entry,) = struct.unpack_from("<Q", buf, off + 16 + 32 * 8)     # pc in arm_thread_state64
        elif cmd == LC_DYLD_CHAINED_FIXUPS:
            fixups = struct.unpack_from("<I", buf, off + 8)[0]
        off += size
    return segs, entry, fixups


def chained_target(raw, fmt, image_base):
    """(target address, links to the next pointer) for one plain-arm64 chained rebase."""
    if raw >> 63:
        raise SystemExit("kernel has a bind fixup: unsupported")
    nxt = (raw >> 51) & 0xFFF
    if fmt in (2, 6):                           # DYLD_CHAINED_PTR_64, _64_OFFSET
        target = (raw & ((1 << 36) - 1)) | (((raw >> 36) & 0xFF) << 56)
        return target + (image_base if fmt == 6 else 0), nxt
    if fmt == 8:                                # DYLD_CHAINED_PTR_64_KERNEL_CACHE
        return image_base + (raw & ((1 << 30) - 1)), nxt
    raise SystemExit(f"chained pointer format {fmt}: unsupported (arm64e kernel?)")


def apply_chained_fixups(buf, segs, data_off):
    _ver, starts_off, _imp_off, _sym_off, imports = struct.unpack_from("<5I", buf, data_off)
    if imports:
        raise SystemExit("kernel has imports: unsupported")
    image_base = segs[0]["vmaddr"]
    table = data_off + starts_off
    (seg_count,) = struct.unpack_from("<I", buf, table)
    count = 0
    for i in range(seg_count):
        (seg_info,) = struct.unpack_from("<I", buf, table + 4 + 4 * i)
        if not seg_info:
            continue
        base = table + seg_info
        _size, page_size, fmt, _seg_off, _max, page_count = struct.unpack_from("<IHHQIH", buf, base)
        for page, start in enumerate(struct.unpack_from("<%dH" % page_count, buf, base + 22)):
            if start == 0xFFFF:
                continue
            if start & 0x8000:
                raise SystemExit("multi-start fixup page: unsupported")
            loc = segs[i]["fileoff"] + page * page_size + start
            while True:
                (raw,) = struct.unpack_from("<Q", buf, loc)
                target, nxt = chained_target(raw, fmt, image_base)
                struct.pack_into("<Q", buf, loc, target)
                count += 1
                if not nxt:
                    break
                loc += nxt * 4
    return count


def flatten_kernel(path):
    """Return (image bytes, image_va, memsize, entry_va) for a Mach-O kernel."""
    buf = bytearray(Path(path).read_bytes())
    segs, entry, fixups = parse_macho(buf)
    nfix = apply_chained_fixups(buf, segs, fixups) if fixups else 0
    if segs[0]["name"] != "__TEXT" or segs[0]["fileoff"] != 0:
        raise SystemExit("unexpected kernel layout: first segment is not __TEXT at file offset 0")
    live = [s for s in segs if s["vmsize"]]
    image_va = min(s["vmaddr"] for s in live)
    end = max(s["vmaddr"] + s["vmsize"] for s in live)
    file_end = max(s["vmaddr"] + s["filesize"] for s in live)
    image = bytearray(file_end - image_va)
    for s in live:
        image[s["vmaddr"] - image_va:s["vmaddr"] - image_va + s["filesize"]] = buf[s["fileoff"]:s["fileoff"] + s["filesize"]]
    memsize = (end - image_va + PAGE_16K - 1) & ~(PAGE_16K - 1)
    print(f"kernel: {len(live)} segments, {nfix} fixups, va 0x{image_va:x}..0x{end:x}, entry 0x{entry:x}")
    return bytes(image), image_va, memsize, entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--kernel", help="Mach-O kernel built by CI")
    ap.add_argument("--flat", help="flat position-independent binary (self-test)")
    ap.add_argument("--image-va", type=lambda s: int(s, 0), default=0xFFFFFFF007004000, help="with --flat")
    ap.add_argument("--memsize", type=lambda s: int(s, 0), default=0, help="with --flat: size in RAM")
    ap.add_argument("--adt")
    ap.add_argument("--ramdisk")
    ap.add_argument("--cmdline", default="")
    a = ap.parse_args()

    if a.kernel:
        image, image_va, memsize, entry = flatten_kernel(a.kernel)
    elif a.flat:
        image = Path(a.flat).read_bytes()
        image_va, memsize, entry = a.image_va, max(a.memsize, len(image)), a.image_va
    else:
        ap.error("--kernel or --flat is required")

    phys_base, mem_size = 0x100000000, 0x7E000000
    adt_blob = b""
    if a.adt:
        adt_blob = Path(a.adt).read_bytes()
        chosen = adt.parse(adt_blob)[0].child("chosen")
        phys_base, = struct.unpack("<Q", chosen.prop("dram-base"))
        mem_size, = struct.unpack("<Q", chosen.prop("dram-size"))
    ramdisk = Path(a.ramdisk).read_bytes() if a.ramdisk else b""
    cmdline = a.cmdline.encode()
    if len(cmdline) >= 608:
        raise SystemExit("command line too long")

    parts, offsets, off = [], [], HEADER
    for blob in (image, adt_blob, ramdisk):
        offsets.append(off)
        parts.append(blob + b"\0" * (-len(blob) % 16))
        off += len(parts[-1])
    virt_base = image_va & ~(BLOCK_32M - 1)     # the kernel's first 32 MB block starts at phys_base
    hdr = struct.pack(
        "<8s15Q", b"LVPAYLD1", off,
        virt_base, entry, phys_base, mem_size,
        offsets[0], len(image), image_va, memsize,
        offsets[1], len(adt_blob),
        offsets[2], len(ramdisk),
        0, 0,
    ) + cmdline
    Path(a.out).write_bytes(hdr.ljust(HEADER, b"\0") + b"".join(parts))
    print(f"{a.out}: {off} bytes, virt_base 0x{virt_base:x}, phys_base 0x{phys_base:x}, image 0x{len(image):x} "
          f"(0x{memsize:x} in RAM), adt 0x{len(adt_blob):x}, ramdisk 0x{len(ramdisk):x}")


if __name__ == "__main__":
    main()
