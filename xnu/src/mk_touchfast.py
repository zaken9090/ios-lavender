"""lavender: the touch bus runs at half_us 1 by default (patch 1155).

Run sw0 (2026-11-27): sweettouch_half_us=1 read a 32-byte report in 1.3 ms (2 = 2.6 ms), 1745 reads
without a failure; the user saw Settings scroll without judder or tearing. sweettouch_half_us=2: as before.

usage: python mk_touchfast.py XNU_TREE
"""
import sys

path = f'{sys.argv[1]}/bsd/dev/sweet_touch.c'
s = open(path, newline='').read()
old = 'static uint32_t lv_half_us = 2;'
assert s.count(old) == 1
s = s.replace(old, 'static uint32_t lv_half_us = 1;    /* (1155: 1 by default, xnu/src/mk_touchfast.py) */')
old = '''	if (lv_half_us == 0 || lv_half_us > 10) {
		lv_half_us = 2;'''
assert s.count(old) == 1
s = s.replace(old, '''	if (lv_half_us == 0 || lv_half_us > 10) {
		lv_half_us = 1;''')
open(path, 'w', newline='\n').write(s)
print('ok')
