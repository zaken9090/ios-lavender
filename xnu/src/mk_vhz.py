"""lavender: boot-arg sweetfb_vhz=N - the display rate CoreAnimation sees (patch 1028), default 60.

CoreAnimation starts frames on vsync ticks. A Settings frame takes ~11 ms to draw and ~11 ms to
show: more than one 16.7 ms tick, so it waits for a later one (~24 fps measured, 2026-11-25). With
ticks every 8.3 ms (sweetfb_vhz=120) a frame that just missed waits 8 ms, not 17. The panel still
refreshes at 60 Hz and shows whatever was presented last. The mode list and the vsync timer use
the same rate. Idea from the user's first lavender project (its patch 1033).

usage: python mk_vhz.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()


def sub(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#define SWEET_FB_VSYNC_US               16667
''', '''/* lavender: boot-arg sweetfb_vhz=N (30..240, default 60): the rate CoreAnimation sees (xnu/src/mk_vhz.py) */
static uint32_t
sweet_vhz(void)
{
	static uint32_t vhz = 0;
	if (vhz == 0) {
		uint32_t v = 60;
		PE_parse_boot_argn("sweetfb_vhz", &v, sizeof(v));
		vhz = (v >= 30 && v <= 240) ? v : 60;
	}
	return vhz;
}
#define SWEET_FB_VSYNC_US               (1000000u / sweet_vhz())
''')
sub('''	fFlushTicks = (hz == 0 || hz >= 60) ? 1 : 60 / hz;''',
    '''	fFlushTicks = (hz == 0 || hz >= sweet_vhz()) ? 1 : sweet_vhz() / hz;
	IOLog("SWEET FB: vsync for CoreAnimation %u Hz\\n", sweet_vhz());''')
sub('''	const uint32_t rate = 60u << 16;        /* 16.16 */''', '''	const uint32_t rate = sweet_vhz() << 16; /* 16.16 */''')
open(path, 'w', newline='\n').write(s)
print('ok')
