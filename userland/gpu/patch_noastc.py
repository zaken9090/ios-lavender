"""lavender: Mesa offers no ASTC to CoreAnimation (eagl.c; boot-arg glastc=1: offered as before).

The app switcher's cards of apps that are not running are snapshots, which CoreAnimation uploads as
ASTC 4x4 textures (glCompressedTexImage2D 0x93b0, up to 1125 x 2436). Drawn from the A509's ASTC
through Mesa freedreno they came out tinted purple/pink (white -> lavender; run ac5). With
MESA_EXTENSION_OVERRIDE=-GL_KHR_texture_compression_astc_ldr the cards are right (run ac6, same
build). The override goes into the environment before the library starts, unless glastc=1 or a
glenv= sets the variable itself.

usage: python patch_noastc.py EAGL_C   (after patch_sysmem.py; .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()
NL = chr(92) + 'n'
old = '''			say("redwood-gl: in the environment by default: FD_MESA_DEBUG=sysmem (glgmem=1: tiles)''' + NL + '''");
		}
'''
assert s.count(old) == 1, s.count(old)
s = s.replace(old, old + '''		if (strstr(arguments, "glastc=1") == NULL) {
			/* lavender: ASTC snapshots came out purple from the A509 (patch_noastc.py) */
			setenv("MESA_EXTENSION_OVERRIDE", "-GL_KHR_texture_compression_astc_ldr", 0);
			say("redwood-gl: in the environment by default: MESA_EXTENSION_OVERRIDE=-GL_KHR_texture_compression_astc_ldr (glastc=1: ASTC)''' + NL + '''");
		}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
