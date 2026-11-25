"""lavender: a texture copied from an IOSurface remembers the surface's seed from before the copy (eagl.c).

surface_to_texture() copied the pixels and only then read the surface's seed (its change count)
for the texture. An application that drew into the surface and unlocked it while the copy ran
moved the seed meanwhile: the texture took the new seed with the old pixels and was never filled
again until the next change - Settings showed rows of earlier frames while scrolling ("Sounds"
twice, the old large title; RedwoodGPU's counters showed applications' surfaces are never shared,
always copied, 2026-11-25). Now the seed is read before the pixels: a change during the copy
leaves the texture behind, and it is filled again at the next use.

usage: python patch_seed.py EAGL_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	if (image->shared) {
		return;
	}
	if (IOSurfaceLock(surface, kIOSurfaceLockReadOnly, NULL) != 0) {
		say("redwood-gl: an IOSurface cannot be locked\\n");
		return;
	}''', '''	if (image->shared) {
		return;
	}
	uint32_t seed_before = IOSurfaceGetSeed(surface);       /* lavender: before the pixels (patch_seed.py) */
	if (IOSurfaceLock(surface, kIOSurfaceLockReadOnly, NULL) != 0) {
		say("redwood-gl: an IOSurface cannot be locked\\n");
		return;
	}''')
sub('''	free(flipped);
	image->seed = IOSurfaceGetSeed(surface);
	e->uploads++;''', '''	free(flipped);
	image->seed = seed_before;      /* lavender: a change during the copy shows as a seed that moved */
	e->uploads++;''')
open(path, 'w', newline='\n').write(s)
print('ok')
