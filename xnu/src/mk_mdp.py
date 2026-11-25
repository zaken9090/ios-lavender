"""lavender: frames shown by pointing the MDP at them, not copied by the CPU (patch 1020).

AppleCLCD (SweetFramebuffer.cpp) had no MDP access on lavender: every frame (11 MB) was copied by
the CPU into the splash buffer the panel keeps scanning. The panel showed the copy as it went, a
slow top-to-bottom wipe, and with gpu=1 the source is write-combined GPU pool memory, so the copy
read uncached memory (frames ~0.9 s after the vsync tick).

SDM660's MDP5 (0xc900000): ABL scans the splash (0x9d400000) with source pipe VIG0 (mdp+0x5000)
on CTL0 (mdp+0x2000); SRC0_ADDR +0x14, YSTRIDE +0x24 and CTL FLUSH +0x18 = 0x20001 (VIG0 + CTL,
latched at the next vsync) as on topaz's DPU, so the base's direct path works as it is: a frame
that is one GPU pool surface (backboardd's display surfaces with gpu=1) is shown by scanFrom().
The MDP takes 32-bit addresses (the pool is at 0xA1000000). Other frames keep the copy path.
Only if VIG0 still scans the splash when we start; boot-arg sweetfb_mdp=0: no MDP access.
Idea from the user's first lavender project (its patch 0995); code written for this tree.

usage: python mk_mdp.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	fVig0 = NULL;
	fCtl0 = NULL;
	topaz_adreno_init();''', '''	fVig0 = NULL;
	fCtl0 = NULL;
	{
		/*
		 * lavender: SDM660 MDP5 - VIG0 (0xc905000) scans the splash on CTL0 (0xc902000), registers
		 * as on topaz's DPU: one GPU pool surface is shown by pointing VIG0 at it (xnu/src/mk_mdp.py).
		 * Only if VIG0 still scans the splash; boot-arg sweetfb_mdp=0: the CPU copies every frame.
		 */
		uint32_t mdp = 1;
		PE_parse_boot_argn("sweetfb_mdp", &mdp, sizeof(mdp));
		if (mdp) {
			volatile uint32_t *vig0 = (volatile uint32_t *)ml_io_map(0x0c905000, 0x1000);
			volatile uint32_t *ctl0 = (volatile uint32_t *)ml_io_map(0x0c902000, 0x1000);
			uint32_t src = vig0 != NULL ? vig0[0x14 / 4] : 0;
			if (vig0 != NULL && ctl0 != NULL && src == 0x9d400000u) {
				fVig0 = vig0;
				fCtl0 = ctl0;
			}
			IOLog("SWEET FB: lavender MDP VIG0 src %#x stride %u ctl0 flush %#x -> %s\\n", src,
			    vig0 != NULL ? vig0[0x24 / 4] : 0, ctl0 != NULL ? ctl0[0x18 / 4] : 0,
			    fVig0 != NULL ? "direct frames" : "left alone, frames copied");
		}
	}
	topaz_adreno_init();''')
open(path, 'w', newline='\n').write(s)
print('ok')
