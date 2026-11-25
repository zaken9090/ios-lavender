#!/usr/bin/env python3
"""Name the kernel addresses of SMK lines (patch 1017) with the kernel's own symbol table.

usage: ksym.py KERNEL LOG [--grep backboardd]
Prints each SMK line with every 0x... after "k" as symbol+offset (the addresses are unslid, as in
the Mach-O).
"""
import argparse
import bisect
import re
import struct
from pathlib import Path

LC_SYMTAB = 0x2


def symbols(path):
    buf = Path(path).read_bytes()
    _magic, _cpu, _sub, _type, ncmds = struct.unpack_from("<5I", buf, 0)
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", buf, off)
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, _strsize = struct.unpack_from("<4I", buf, off + 8)
            out = []
            for i in range(nsyms):
                strx, ntype, _sect, _desc, value = struct.unpack_from("<IBBHQ", buf, symoff + 16 * i)
                if ntype & 0xE0 or (ntype & 0x0E) != 0x0E or value == 0:    # defined in a section, no stabs
                    continue
                end = buf.index(b"\0", stroff + strx)
                out.append((value, buf[stroff + strx:end].decode(errors="replace")))
            out.sort()
            return out
        off += size
    raise SystemExit("no symbol table")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kernel")
    ap.add_argument("log")
    ap.add_argument("--grep", default="")
    a = ap.parse_args()
    syms = symbols(a.kernel)
    addrs = [s[0] for s in syms]

    def name(v):
        i = bisect.bisect_right(addrs, v) - 1
        if i < 0 or v - addrs[i] > 0x100000:
            return hex(v)
        return f"{syms[i][1]}+0x{v - addrs[i]:x}"

    for line in Path(a.log).read_text(errors="replace").splitlines():
        if "SMK " not in line or a.grep not in line:
            continue
        line = line[line.index("SMK "):]
        head, _, frames = line.partition(" k ")
        print(head)
        for f in re.findall(r"0x[0-9a-f]+", frames):
            print("    " + name(int(f, 16)))


if __name__ == "__main__":
    main()
