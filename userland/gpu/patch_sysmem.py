"""lavender: Mesa renders straight into memory by default (FD_MESA_DEBUG=sysmem), boot-arg glgmem=1: tiles.

Measured 2026-11-25 on lavender (gpu=1, MDP direct frames): home 6.8 -> 8.7 fps, Settings 22.8 -> 24.2
with glenv=FD_MESA_DEBUG=sysmem (the first lavender project saw the same direction). CoreAnimation's
frames are a few big quads over big surfaces: binning and tile load/store cost more than they save.
glenv=FD_MESA_DEBUG=... still overrides.

usage: python patch_sysmem.py EAGL_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		for (argument = arguments; (argument = strstr(argument, "glenv=")) != NULL; argument += 6) {''',
    '''		if (strstr(arguments, "glgmem=1") == NULL) {
			/* lavender: no tiles (binning, tile load/store) by default: faster here (patch_sysmem.py) */
			setenv("FD_MESA_DEBUG", "sysmem", 0);
			say("redwood-gl: in the environment by default: FD_MESA_DEBUG=sysmem (glgmem=1: tiles)\\n");
		}
		for (argument = arguments; (argument = strstr(argument, "glenv=")) != NULL; argument += 6) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
