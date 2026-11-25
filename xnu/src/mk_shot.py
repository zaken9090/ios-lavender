"""lavender: lv:shot sends what the MDP scans, not always the splash buffer (patch 1022).

With frames shown by the MDP itself (patch 1020) the splash buffer (/sweet-fbcon) only holds the
kernel console, so lv:shot showed the console and tools/bench.py could not see the home screen.
Now lv:shot reads VIG0 (0xc905000, mapped at USB start): when it fetches something other than
the splash, the shot is that: SRC0_ADDR, YSTRIDE and SRC_SIZE (the presented 1125x2436 while
QSEED3 scales, patch 1021). The host side reads width, height and stride from the header.

usage: python mk_shot.py XNU_TREE
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
{''', '''static volatile uint32_t *ud_vig0;        /* lavender: MDP VIG0, what the panel shows (xnu/src/mk_shot.py) */

static bool
ud_tx_shot(void)
{''')
sub('''		ud.shot_pa = reg[0];
		ud.shot_left = (uint64_t)*stride * *h;
		uint32_t n = (uint32_t)snprintf((char *)(ud.dma + UD_TX), UD_BUF_MAX, "\\n@@LVSHOT %u %u %u %llu@@\\n",
		    *w, *h, *stride, ud.shot_left);''', '''		ud.shot_pa = reg[0];
		uint32_t sw = *w, sh = *h, ss = *stride;
		/* lavender: the MDP may scan a frame of its own (direct frames, patch 1020): send that */
		uint32_t src = ud_vig0 != NULL ? ud_vig0[0x14 / 4] : 0, vsz = ud_vig0 != NULL ? ud_vig0[0x00 / 4] : 0;
		if (src != 0 && src != (uint32_t)reg[0] && (vsz & 0xffff) != 0 && (vsz >> 16) != 0) {
			ud.shot_pa = src;
			sw = vsz & 0xffff;
			sh = vsz >> 16;
			ss = ud_vig0[0x24 / 4] & 0xffff;
		}
		ud.shot_left = (uint64_t)ss * sh;
		uint32_t n = (uint32_t)snprintf((char *)(ud.dma + UD_TX), UD_BUF_MAX, "\\n@@LVSHOT %u %u %u %llu@@\\n",
		    sw, sh, ss, ud.shot_left);''')
sub('''	ud.dwc = ml_io_map(DWC3_PA, DWC3_SIZE);
''', '''	ud.dwc = ml_io_map(DWC3_PA, DWC3_SIZE);
	ud_vig0 = (volatile uint32_t *)ml_io_map(0x0c905000, 0x1000);       /* lavender: for lv:shot */
''')
open(path, 'w', newline='\n').write(s)
print('ok')
