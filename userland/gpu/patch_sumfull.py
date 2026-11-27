"""lavender: surface_changed() adds up all of a surface by default (eagl.c; glsumfull=0: the sample as before).

After patch_sum.py. Scrolling Settings at its top with short jerks (the user's repro, 2026-11-27), lv:shot
caught reused cells with stale or half-new pictures: the "Код допуску" icon as a red striped grid, its
label a grey smear (3 of 8 shots). Apps redraw a reused cell's layer in the same IOSurface without
moving its seed; a sum of a word in 512 bytes plus a sixteenth missed the change for frames. With the
full sum: 0 of 12 shots, and Settings held 60 fps in the slow-drag bench (sf1c, with glpreserve off).

usage: python patch_sumfull.py EAGL_C   (after patch_sum.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()
old = 'sum_sampled = strstr(arguments, "glsumfull=1") == NULL;'
assert s.count(old) == 1
s = s.replace(old, 'sum_sampled = strstr(arguments, "glsumfull=0") != NULL;       /* lavender: full by default (patch_sumfull.py) */')
open(path, 'w', newline='\n').write(s)
print('ok')
