"""lavender: backboardd draws every frame in full: CA_DISABLE_DIRTY_REGIONS=1 (bbd_wrap.c; boot-arg bbddirty=1: off).

After patch_bbdnano.py. The user filmed the App Library pulled down (2026-11-27): when the search
keyboard slides away, some frames keep an old picture of the keyboard at the bottom of the screen
("ЙЦУКЕН" over the list), alternating with right ones: the bottom flickers. The same kind of stale part
showed in Settings when overscrolled and in the app switcher. QuartzCore renders only the dirty region
of a frame and copies the rest forward from an older buffer ("copy forward area"); somewhere in that
path (old buffers, other contexts) parts come out stale here. QuartzCore reads CA_DISABLE_DIRTY_REGIONS
from the environment: every frame is then drawn whole. More GPU work a frame, no stale parts.

usage: python patch_bbdfull.py BBD_WRAP_C   (after patch_bbdnano.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()
old = '''	if (strstr(bootargs, "bbdnano=0") == NULL) {
		setenv("MallocNanoZone", "1", 1);
	}
'''
assert s.count(old) == 1
s = s.replace(old, old + '''	/* lavender: whole frames, no dirty regions (patch_bbdfull.py) */
	if (strstr(bootargs, "bbddirty=1") == NULL) {
		setenv("CA_DISABLE_DIRTY_REGIONS", "1", 1);
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
