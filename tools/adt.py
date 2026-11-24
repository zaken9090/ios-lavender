#!/usr/bin/env python3
"""Apple Device Tree (ADT) binary format: build, parse, dump.

A node is: u32 property count, u32 child count, properties, children.
A property is: char name[32], u32 length (bit 31 = "placeholder" flag), value padded to 4 bytes.

usage: adt.py FILE        dump a tree
"""
import struct
import sys

FLAG = 0x80000000


class Node:
    def __init__(self, name=None, props=(), children=()):
        self.props = []                 # list of (name, flag, value bytes)
        self.children = list(children)
        if name is not None:
            self.props.append(("name", 0, name.encode() + b"\0"))
        for key, value in props:
            self.props.append((key, 0, value))

    @property
    def name(self):
        value = self.prop("name")
        return value.rstrip(b"\0").decode() if value else ""

    def prop(self, key):
        for name, _flag, value in self.props:
            if name == key:
                return value
        return None

    def set(self, key, value):
        self.props = [p for p in self.props if p[0] != key] + [(key, 0, value)]

    def child(self, name):
        for c in self.children:
            if c.name == name:
                return c
        return None


def serialize(node):
    out = struct.pack("<II", len(node.props), len(node.children))
    for name, flag, value in node.props:
        key = name.encode()
        assert len(key) < 32, name
        out += key.ljust(32, b"\0") + struct.pack("<I", len(value) | (FLAG if flag else 0))
        out += value + b"\0" * (-len(value) % 4)
    for c in node.children:
        out += serialize(c)
    return out


def parse(buf, off=0):
    nprops, nchildren = struct.unpack_from("<II", buf, off)
    off += 8
    node = Node()
    for _ in range(nprops):
        name = buf[off:off + 32].split(b"\0")[0].decode()
        (length,) = struct.unpack_from("<I", buf, off + 32)
        flag, length = bool(length & FLAG), length & ~FLAG
        node.props.append((name, flag, bytes(buf[off + 36:off + 36 + length])))
        off += 36 + ((length + 3) & ~3)
    for _ in range(nchildren):
        child, off = parse(buf, off)
        node.children.append(child)
    return node, off


def dump(node, depth=0):
    pad = "  " * depth
    print(f"{pad}{node.name} {{")
    for name, flag, value in node.props:
        if name == "name":
            continue
        text = value.rstrip(b"\0")
        if value and value[-1:] == b"\0" and text and all(32 <= c < 127 or c == 0 for c in text):
            shown = " ".join('"%s"' % s.decode() for s in text.split(b"\0"))
        elif len(value) % 8 == 0 and 0 < len(value) <= 32:
            shown = " ".join("0x%x" % v for v in struct.unpack("<%dQ" % (len(value) // 8), value))
        elif len(value) == 4:
            shown = "0x%x" % struct.unpack("<I", value)[0]
        else:
            shown = value[:24].hex() + ("..." if len(value) > 24 else "") + f" ({len(value)} bytes)"
        print(f"{pad}  {name}{' [placeholder]' if flag else ''} = {shown}")
    for c in node.children:
        dump(c, depth + 1)
    print(f"{pad}}}")


if __name__ == "__main__":
    dump(parse(open(sys.argv[1], "rb").read())[0])
