"""lavender: the QMUX trace shows 80 bytes of each message (patch 1074), T5.

The UIM card status (0x2F) of run e75 is cut at 40 bytes in the middle of the second slot: with a
SIM inserted the first slot reports card state "error", code 3 ("no ATR"), and the second slot's
code is beyond the cut. 80 bytes now.

usage: python mk_qmuxlog2.py XNU_TREE   (after mk_qmuxlog.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()
for old, new in (('''	char hex[3 * 40 + 1];
	uint32_t hdr = svc == 0 ? 6 : 7, n = 0;''', '''	char hex[3 * 80 + 1];
	uint32_t hdr = svc == 0 ? 6 : 7, n = 0;'''),
                 ('''	for (uint32_t i = hdr; i < len && n < 40; i++, n++) {''', '''	for (uint32_t i = hdr; i < len && n < 80; i++, n++) {''')):
    assert s.count(old) == 1, old[:60]
    s = s.replace(old, new)
open(path, 'w', newline='\n').write(s)
print('ok')
