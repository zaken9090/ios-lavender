"""lavender: a frame does not start from a copy of the last one by default (eagl.c; glpreserve=1: as before).

After patch_preserve.py. The user filmed Settings while scrolling (2026-11-27): rows doubled and smeared
in the upper part; lv:shot during momentum scrolls caught a band of stale rows ("Екранний час" under
"Шпалери") at the same place of the screen in 2 of 8 shots. With glpreserve=0: 0 of 16. The first lavender
project also ended with its preserve off by default ("did not help the flicker, costs a blit a frame").
The ordering fixes (patch_order.py) cover what preserve was added for. Also saves a full-screen blit a frame.

usage: python patch_nopreserve.py EAGL_C   (after patch_preserve.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()
old = 'preserve_frames = strstr(arguments, "glpreserve=0") == NULL;'
assert s.count(old) == 1
s = s.replace(old, 'preserve_frames = strstr(arguments, "glpreserve=1") != NULL;      /* lavender: off by default (patch_nopreserve.py) */')
open(path, 'w', newline='\n').write(s)
print('ok')
