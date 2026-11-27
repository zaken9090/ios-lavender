"""lavender: lv:shot sends the frame that was on the panel when asked: the presenter waits while it goes (patch 1156).

lv:shot sends the buffer VIG0 scans over USB, 11 MB in ~0.3-0.5 s. Meanwhile the panel moved on to newer
frames and CoreAnimation drew again into the buffer being sent (it is released one latch later), so shots
taken in motion mixed several frames: rows twice, stale bands, half-new icons - which also misled the
2026-11-27 analysis of glpreserve and the surface sum. Now from lv:shot until its last byte has gone
the presenter does not show new frames (up to 3 s; frames wait in its queue); the buffer on the panel
stays held, so the picture is exactly one frame. The UI stands still for that half second.
boot-arg lv_shot_freeze=0: as before.

usage: python mk_shotfreeze.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_usb.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static bool
ud_tx_shot(void)
{''', '''/* lavender: while a screenshot goes out the presenter shows no new frame (xnu/src/mk_shotfreeze.py) */
volatile int sweet_shot_busy;

static bool
ud_tx_shot(void)
{''')
sub('''	if (ud.shot_left == 0) {
		return false;
	}''', '''	if (ud.shot_left == 0) {
		sweet_shot_busy = 0;            /* (the last piece has gone) */
		return false;
	}''')
sub('''		ud.shot_pending = true;''', '''		ud.shot_pending = true;
		static int freeze = -1;
		if (freeze < 0) {
			freeze = 1;
			PE_parse_boot_argn("lv_shot_freeze", &freeze, sizeof(freeze));
		}
		sweet_shot_busy = freeze;''')
open(path, 'w', newline='\n').write(s)

path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()
sub('''		sweet_hold_set(dropped, false);
		uint64_t waited = mach_absolute_time(), wns = 0;  /* (present waits for the GPU too) */''', '''		sweet_hold_set(dropped, false);
		/* lavender: a screenshot is going out: the frame on the panel stays (xnu/src/mk_shotfreeze.py) */
		for (int t = 0; sweet_shot_busy && t < 1500; t++) {
			IOSleep(2);
		}
		uint64_t waited = mach_absolute_time(), wns = 0;  /* (present waits for the GPU too) */''')
sub('''extern "C" int sweet_console_copy_dirty(void *dst);''', '''extern "C" int sweet_console_copy_dirty(void *dst);
extern "C" volatile int sweet_shot_busy;           /* bsd/dev/sweet_usb.c (xnu/src/mk_shotfreeze.py) */''')
open(path, 'w', newline='\n').write(s)
print('ok')
