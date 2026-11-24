#!/usr/bin/env python3
"""Show an Android boot image header (v0-v2) and split out the kernel and the DTBs appended to it.

usage: bootinfo.py boot.img [outdir]
With outdir: writes kernel.gz (or kernel) and dtbN.dtb, one per appended device tree.
"""
import struct
import sys
from pathlib import Path

FDT_MAGIC = b"\xd0\x0d\xfe\xed"


def root_props(dtb):
    """Return the properties of the root node of a flattened device tree."""
    off_struct, off_strings = struct.unpack_from(">II", dtb, 8)
    props, pos, depth = {}, off_struct, 0
    while True:
        (tok,) = struct.unpack_from(">I", dtb, pos)
        pos += 4
        if tok == 1:  # BEGIN_NODE
            end = dtb.index(b"\0", pos)
            pos = (end + 4) & ~3
            depth += 1
            if depth > 1:
                return props
        elif tok == 3:  # PROP
            length, nameoff = struct.unpack_from(">II", dtb, pos)
            pos += 8
            name_end = dtb.index(b"\0", off_strings + nameoff)
            props[dtb[off_strings + nameoff:name_end].decode()] = dtb[pos:pos + length]
            pos = (pos + length + 3) & ~3
        elif tok == 4:  # NOP
            continue
        else:  # END_NODE / END
            return props


def cells(data):
    return " ".join("0x%x" % v for v in struct.unpack(">%dI" % (len(data) // 4), data))


def main():
    img = Path(sys.argv[1]).read_bytes()
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if img[:8] != b"ANDROID!":
        sys.exit("not an Android boot image")
    (ksize, kaddr, rsize, raddr, ssize, saddr, tags, page, version, oslvl) = struct.unpack_from("<10I", img, 8)
    name = img[48:64].rstrip(b"\0").decode()
    cmdline = img[64:64 + 512].rstrip(b"\0").decode()
    print(f"header version {version}, page {page}")
    print(f"kernel  size 0x{ksize:x} load 0x{kaddr:x}")
    print(f"ramdisk size 0x{rsize:x} load 0x{raddr:x}")
    print(f"second  size 0x{ssize:x} load 0x{saddr:x}, tags 0x{tags:x}")
    print(f"name '{name}'\ncmdline: {cmdline}")

    kernel = img[page:page + ksize]
    kind = "gzip" if kernel[:2] == b"\x1f\x8b" else "raw"
    # appended DTBs: every FDT magic whose totalsize chains exactly to the next one / to the end
    dtbs, pos = [], kernel.find(FDT_MAGIC)
    while pos != -1:
        (total,) = struct.unpack_from(">I", kernel, pos + 4)
        if 0x100 < total <= len(kernel) - pos and struct.unpack_from(">I", kernel, pos + 20)[0] in (16, 17):
            dtbs.append((pos, total))
            pos += total
            if kernel[pos:pos + 4] != FDT_MAGIC:
                pos = kernel.find(FDT_MAGIC, pos)
        else:
            pos = kernel.find(FDT_MAGIC, pos + 4)
    first = dtbs[0][0] if dtbs else len(kernel)
    print(f"kernel is {kind}, 0x{first:x} bytes before {len(dtbs)} appended DTB(s)")
    if out:
        out.mkdir(parents=True, exist_ok=True)
        (out / ("kernel.gz" if kind == "gzip" else "kernel")).write_bytes(kernel[:first])
    for i, (off, total) in enumerate(dtbs):
        blob = kernel[off:off + total]
        p = root_props(blob)
        model = p.get("model", b"").rstrip(b"\0").decode()
        print(f"dtb{i}: 0x{total:x} bytes  msm-id [{cells(p.get('qcom,msm-id', b''))}]"
              f"  board-id [{cells(p.get('qcom,board-id', b''))}]  {model}")
        if out:
            (out / f"dtb{i}.dtb").write_bytes(blob)


if __name__ == "__main__":
    main()
