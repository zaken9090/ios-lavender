"""lavender: sweetfb_lock=1 on a 60 Hz panel - no tick thrown away for being under 12 ms away (patch 1173).

vsyncNext() (the base's, for a 127 Hz panel: "every second panel frame") never waits less than 12 ms:
on lavender's 60 Hz panel (16.6 ms a frame, SWEET INTF1) a timer handler that ran 4.4 ms late pushed
the next tick a whole panel frame out, and CoreAnimation lost a frame (sweetfb_lock=1 in runs at1 / at2:
Settings 48-56 fps against 59 without). Now the least wait is a quarter of the panel's frame when the
panel is slower than ~83 Hz, 12 ms as before otherwise.

  sweetfb_lock_min_us=N   the least wait to the next tick (default 0: as above)
Without sweetfb_lock=1 nothing changes: the free-running timer is re-armed 16.67 ms after its handler
ends, so CoreAnimation gets ~57-58 ticks a second against the panel's 60 (300 ticks, 308-314 frames).

usage: python mk_vlock60.py XNU_TREE   (after mk_contigbackoff.py)
"""
import sys

tree = sys.argv[1]
p = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(p, newline='').read()
old = '''	uint32_t next = left + lock_us;
	while (next < 12000) {
		next += fPanelUS;
	}
	return next;
'''
new = '''	uint32_t next = left + lock_us;
	/* lavender (mk_vlock60.py): 12 ms was for a 127 Hz panel (every second frame); a 60 Hz one gets every frame */
	static uint32_t min_arg, min_read;
	if (!min_read) {
		min_read = 1;
		PE_parse_boot_argn("sweetfb_lock_min_us", &min_arg, sizeof(min_arg));
	}
	uint32_t least = min_arg != 0 ? min_arg : fPanelUS > 12000 ? fPanelUS / 4 : 12000;
	while (next < least) {
		next += fPanelUS;
	}
	return next;
'''
assert s.count(old) == 1
open(p, 'w', newline='\n').write(s.replace(old, new))
print('ok')
