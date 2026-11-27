"""lavender: a swapped surface can name another surface to be shown in its place (patch 1167).

87 % of CoreAnimation's display frames began in the surface the panel was still showing (two display
surfaces, SwapEnd returns at once): the copy of the last frame and the drawing happened in view - the
trembling bottom of the screen, torn rows (docs/GPU-PLAN.md, 2026-11-28). The fix is in user space
(userland/gpu/patch_scanout.py): the finished frame is copied into a scanout surface of its own that
CoreAnimation never draws into, and the surface it swaps carries that one's ID as the IOSurface value
"lv-show". Here the swap shows the named surface: its ID replaces the swapped one's in the swap
record, so the holds, the wait for the GPU and the MDP address are all the scanout surface's.

sweetfb_show=0 ignores the value (the swapped surface is shown, as before).

usage: python mk_scanout.py XNU_TREE   (after mk_gpurecover2.py)
"""
import sys

tree = sys.argv[1]
NL = chr(92) + 'n'


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


h = f'{tree}/iokit/Kernel/arm/SweetSurface.h'
patch(h, '''	uint32_t                  drawn;        /* topaz GPU: last submission naming this surface (RedwoodGPU.cpp) */
''', '''	uint32_t                  drawn;        /* topaz GPU: last submission naming this surface (RedwoodGPU.cpp) */
	uint32_t                  showID;       /* lavender: IOSurface value "lv-show" - the surface shown in this one's place (mk_scanout.py) */
''')
patch(h, '''drawn = 0;''', '''drawn = 0; showID = 0;''')

patch(f'{tree}/iokit/Kernel/arm/SweetSurface.cpp', '''			s->values->setObject(key, array->getObject(0));
			ret = kIOReturnSuccess;''', '''			s->values->setObject(key, array->getObject(0));
			if (key->isEqualTo("lv-show")) {                /* lavender: mk_scanout.py */
				OSNumber *show = OSDynamicCast(OSNumber, array->getObject(0));
				s->showID = show != NULL ? show->unsigned32BitValue() : 0;
			}
			ret = kIOReturnSuccess;''')

patch(f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp', '''AppleCLCD::swap(const uint8_t *rec)
{
	sweet_fps_count();
''', '''AppleCLCD::swap(const uint8_t *rec)
{
	/*
	 * lavender (mk_scanout.py): a surface that names another one ("lv-show") is shown as that one -
	 * the finished frame's copy, which CoreAnimation never draws into.
	 */
	uint8_t shownRec[SWEET_FB_SWAP_REC_SIZE];
	static int show = -1;
	if (show < 0) {
		show = 1;
		PE_parse_boot_argn("sweetfb_show", &show, sizeof(show));
	}
	if (show != 0) {
		bool changed = false;
		memcpy(shownRec, rec, sizeof(shownRec));
		for (uint32_t i = 0; i < 4 && i < SWEET_FB_LAYERS; i++) {
			uint32_t sid = get32(shownRec, 0x54 + 4 * i);
			SweetSurface *s = sid != 0 ? sweet_surface_copy(sid) : NULL;
			uint32_t other = s != NULL ? s->showID : 0;
			SweetSurface *z = other != 0 && other != sid ? sweet_surface_copy(other) : NULL;
			if (z != NULL && z->gpuPool && z->width == s->width && z->height == s->height) {
				static uint32_t told;
				memcpy(&shownRec[0x54 + 4 * i], &other, sizeof(other));
				changed = true;
				if (told++ < 3) {
					IOLog("SWEET FB: surface %u is shown as surface %u (lv-show)''' + NL + '''", sid, other);
				}
			}
			if (z != NULL) {
				z->release();
			}
			if (s != NULL) {
				s->release();
			}
		}
		if (changed) {
			rec = shownRec;
		}
	}
	sweet_fps_count();
''')
print('ok')
