"""lavender: a released IOSurface view keeps only its state page, not the surface (patch 1019).

IOSurfaceRootUserClient::trapRelease (base) moves a released view to fZombies (the last 256 per
client) so that its read-only state page stays mapped: another framework client of the same
surface may still read the seed there. But the zombie also kept its retain on the SweetSurface,
so the surface's pixel buffer (wired kernel memory, up to 16 MB) stayed alive too. The SMS line
(patch 1018) showed it on lavender: CollectionsPoster held 914 MB in 266 such surfaces and
PosterBoard 300+ MB (growing), 1.2 GB of the 1.95 GB iOS has; the UI then paged its code in
from disk, throttled (GL frames 0.5-1.5 s late, no unlock).

Now the zombie lets the surface go at once; its state mapping (an IOMemoryMap, which retains
the state page's descriptor on its own) stays. Zombies are never looked up (findRef searches
fRefs only), and SweetSurfaceRef::free() already handles surface == NULL.

usage: python mk_zombie.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetSurface.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		OSSafeReleaseNULL(ref->data);
		sweet_surface_put(ref->surface);
		ref->released = true;
		ref->detached = false;
''', '''		OSSafeReleaseNULL(ref->data);
		sweet_surface_put(ref->surface);
		/*
		 * lavender: the zombie keeps the state page's mapping only (it retains that page's
		 * descriptor itself), not the surface: with it, every zombie kept its whole pixel
		 * buffer wired (1.2 GB on lavender; xnu/src/mk_zombie.py).
		 */
		ref->surface->release();
		ref->surface = NULL;
		ref->released = true;
		ref->detached = false;
''')
open(path, 'w', newline='\n').write(s)
print('ok')
