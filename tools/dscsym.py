#!/usr/bin/env python3
"""Name the profiler's busiest pieces of shared-cache images (SPF ... in IMAGE +0xOFF n N lines, xnu 1149).

usage: dscsym.py LOG SYMDIR
SYMDIR holds `ipsw dyld symaddr CACHE --image NAME` outputs named sym_NAME.txt (made in WSL from the
iOS 20H392 SystemOS dyld cache). The slide comes from the image's run-time base (SPF img line) minus the
lowest symbol's text page... no: minus the cache address of its __TEXT, given as the first symbol's page
is not exact, so the base is taken from `ipsw dyld macho` and passed in sym_NAME.base (one hex number).
"""
import bisect
import collections
import os
import re
import sys

log = open(sys.argv[1], 'rb').read().decode('utf-8', 'replace')
symdir = sys.argv[2]
bases = {m.group(1): int(m.group(2), 16) for m in re.finditer(r'SPF \S+ img (\S+) n \d+ base (0x[0-9a-f]+)', log)}
for f in sorted(os.listdir(symdir)):
    if not f.startswith('sym_') or not f.endswith('.txt'):
        continue
    name = f[4:-4]
    basefile = os.path.join(symdir, f'sym_{name}.base')
    if name not in bases or not os.path.exists(basefile):
        continue
    cache_base = int(open(basefile).read().strip(), 16)
    syms = []
    for line in open(os.path.join(symdir, f), errors='replace'):
        m = re.match(r'(0x[0-9a-f]+):\s+\([^)]*\)\s+(.*?)\s+\S+$', line.rstrip())
        if m:
            syms.append((int(m.group(1), 16), m.group(2)))
    syms.sort()
    addrs = [s[0] for s in syms]
    c = collections.Counter()
    total = 0
    for m in re.finditer(r'SPF \S+ in %s \+(0x[0-9a-f]+) n (\d+)' % re.escape(name), log):
        a = cache_base + int(m.group(1), 16)
        i = bisect.bisect_right(addrs, a) - 1
        c[syms[i][1] if i >= 0 else '?'] += int(m.group(2))
        total += int(m.group(2))
    print(f'== {name} (listed pieces: {total} samples)')
    for fn, n in c.most_common(25):
        print(f'  {n:5d} {fn}')
