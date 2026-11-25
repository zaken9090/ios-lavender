"""lavender: boot-arg sweetfb_lock_us=N - how long after the panel's frame start the vsync tick goes out (patch 1034).

With sweetfb_lock=1 the tick followed the panel's frame start by 0.3 ms. The MDP latches a new
frame at that same moment and only then is the other display surface free again (the presenter
thread sees the latch within ~0.2 ms): CoreAnimation, woken 0.3 ms after the latch, often found
no free surface and waited a whole tick - frames at exactly every second refresh (30 fps) though a
frame takes ~4.5 ms to hand over with Mesa's driver thread (2026-11-25). A later tick (2-3 ms)
lets the surface come free first. Default stays 300.

usage: python mk_lockus.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()
old = '''	uint32_t next = left + 300;'''
assert s.count(old) == 1
s = s.replace(old, '''	/* lavender: sweetfb_lock_us - the tick this long after the panel's frame starts (xnu/src/mk_lockus.py) */
	static uint32_t lock_us;
	if (lock_us == 0) {
		lock_us = 300;
		PE_parse_boot_argn("sweetfb_lock_us", &lock_us, sizeof(lock_us));
		if (lock_us == 0 || lock_us > 12000) {
			lock_us = 300;
		}
	}
	uint32_t next = left + lock_us;''')
open(path, 'w', newline='\n').write(s)
print('ok')
