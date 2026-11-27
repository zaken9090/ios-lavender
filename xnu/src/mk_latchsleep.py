"""lavender: the presenter sleeps until the panel's frame ends instead of looking every 100 us (patch 1143).

SMT lines (1142) showed AppleCLCD's presenter thread at ~16% of a core while the UI draws: after each
direct frame it waits for the MDP to latch the new address (next panel vsync, up to a panel frame,
~8 ms) by waking every 100 us. Now it reads INTF_1's line counter, sleeps until ~200 us before the
frame ends, then looks every 100 us as before. Same latch moment, ~1/40 of the wakeups.

boot-arg sweetfb_latch_sleep=0: old way (default 1).
usage: python mk_latchsleep.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		present(rec);
		for (int t = 0; fCtl0 != NULL && t < 250 && (fCtl0[0x18 / 4] & 0x20001) != 0; t++) {''', '''		present(rec);
		/* lavender: sleep until the panel's frame is nearly over, then look (xnu/src/mk_latchsleep.py) */
		static int latch_sleep = -1;
		if (latch_sleep < 0) {
			latch_sleep = 1;
			PE_parse_boot_argn("sweetfb_latch_sleep", &latch_sleep, sizeof(latch_sleep));
		}
		/* the panel's frame time, measured with INTF_1's frame counter (~6.8 ms: 148 Hz, not fPanelUS) */
		static uint64_t cal_at;
		static uint32_t cal_frames, frame_us;
		if (latch_sleep && fIntf1 != NULL) {
			uint64_t now = mach_absolute_time(), ns;
			uint32_t frames = fIntf1[(0x800 + 0x0ac) / 4];
			if (cal_at == 0) {
				cal_at = now;
				cal_frames = frames;
			} else if (frames - cal_frames >= 300) {
				absolutetime_to_nanoseconds(now - cal_at, &ns);
				uint32_t us = (uint32_t)(ns / 1000 / (frames - cal_frames));
				frame_us = (us >= 4000 && us <= 20000) ? us : 0;
				cal_at = now;
				cal_frames = frames;
			}
		}
		if (latch_sleep && frame_us != 0 && fCtl0 != NULL && fVTotal > 100 && (fCtl0[0x18 / 4] & 0x20001) != 0) {
			uint32_t line = fIntf1[(0x800 + 0x0b0) / 4] & 0xffff;
			if (line < fVTotal) {
				uint32_t left = (uint32_t)((uint64_t)(fVTotal - line) * frame_us / fVTotal);
				if (left > 400 && left < 20000) {
					IODelay(left - 200);
				}
			}
		}
		for (int t = 0; fCtl0 != NULL && t < 250 && (fCtl0[0x18 / 4] & 0x20001) != 0; t++) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
