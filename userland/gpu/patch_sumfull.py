"""lavender: surface_changed() adds up all of a small surface; only big ones by sample (eagl.c).

After patch_sum.py, which sampled every surface from 64 KB up (a word in 512 bytes and a sixteenth).
Scrolling Settings, reused cells came out with stale or half-new pictures (icons, labels: small surfaces
an app redraws without moving the seed) and the sample missed the redraw for frames. Adding up all of
every surface (glsumfull=1) cost too much on the home screen (wallpaper-sized surfaces, ~11 MB each,
every frame: judder, the user 2026-11-27). Now surfaces below 1 MB are added up in full, bigger ones by
the sample as before. glsumfull=1: everything in full; glsummb=N: the limit in MB (default 1).

usage: python patch_sumfull.py EAGL_C   (after patch_sum.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	if (sum_sampled && size >= (64u << 10)) {''', '''	if (sum_sampled && size >= sum_full_below) {      /* lavender: patch_sumfull.py (was 64 KB) */''')
sub('''static int sum_sampled = 1;''', '''static size_t sum_full_below = 1u << 20;       /* lavender: below this a surface is added up in full (patch_sumfull.py) */
static int sum_sampled = 1;''')
sub('''		sum_sampled = strstr(arguments, "glsumfull=1") == NULL;''', '''		sum_sampled = strstr(arguments, "glsumfull=1") == NULL;
		if ((argument = strstr(arguments, "glsummb=")) != NULL) {        /* lavender: patch_sumfull.py */
			long mb = strtol(argument + 8, NULL, 10);
			if (mb >= 0 && mb <= 64) {
				sum_full_below = (size_t)mb << 20;
			}
		}''')
open(path, 'w', newline='\n').write(s)
print('ok')
