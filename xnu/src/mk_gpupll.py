"""lavender: the GPU's own PLL for clocks above 300 MHz, up to this chip's 647 MHz (patch 1177, PLAN S4).

Facts (2026-11-28, docs/GPU-PLAN.md):
  - Speed bin: fuse 0x7841a0 = 0x10f80000, bits 28:21 = 0x87 -> stock table 160 / 266 / 370 / 465 / 588 /
    647 MHz (qcom,gpu-pwrlevels with speed-bin 0x87); 700 and 750 are other bins'.
  - The GPU has no rail of its own: gfx_corner's vdd is a stub, the core sits on CX through the GX head
    switch, and stock asks the RPM for a CX level per clock (rwcx 0: 0x100 at 588 MHz, 0x140 at 647).
    CX reads 848-852 mV whatever we ask (swen + vlvl 0x180 on rwcx 0 or on smpb 3): it is held at the top
    already (the DDR at its top clock and the others). So the voltage for 647 MHz is there.
  - What was not as stock: 600 MHz was GPLL0 / 1, and the governor changed the RCG's divider on a running
    source (2 of 13 boots hung right after a 300 -> 600 step). Stock takes each clock from one of the two
    GPU PLLs (VCO = 2 x clock, RCG / 2) and moves the RCG between two running sources.
Now:
  lv_gpu_mhz=N     a fixed clock: 300 (GPLL0 / 2, the default), 600 (GPLL0 / 1, as before) or any other N
                   up to 647 from GPU PLL0 (588 and 647 are the stock steps)
  lv_gpu_dvfs=1    the governor (mk_gpudvfs.py) steps between 300 MHz (GPLL0 / 2) and lv_gpu_hi
  lv_gpu_hi=647    the governor's top clock, from GPU PLL0 kept running (600: GPLL0 / 1 as before)
The CX vote also goes to the stock resource (rwcx 0, swen 1 + vlvl 0x180) - upwards only, and only when a
clock above 300 MHz is asked for. The LVM line's GPU clock is the real one for any source.

usage: python mk_gpupll.py XNU_TREE   (after mk_cpuvolthi.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


r = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'

patch(r, '''/* GDSC: clear SW_COLLAPSE, wait for PWR_ON */
''', '''/*
 * lavender (mk_gpupll.py): the GPU PLLs (alpha PLLs at gpucc + 0x00 and + 0x40: +0 mode, +4 L, +8 / +0xc
 * alpha, +0x10 user control) as Linux's clk-alpha-pll.c runs them, and the gfx3d root's source.
 */
extern "C" volatile uint32_t lv_gpu_now_mhz;    /* the gfx3d clock now (LavenderMetrics.cpp) */
volatile uint32_t lv_gpu_now_mhz = 300;
static uint32_t lv_gpu_hi_mhz = 647;            /* lv_gpu_hi: the governor's top clock */
static bool lv_gpu_pll_ok;                      /* GPU PLL0 runs at 2 x lv_gpu_hi_mhz */

/* GPU PLL `which` to 2 x mhz and on; false: no lock, left off */
static bool
lv_gpu_pll(unsigned which, uint32_t mhz)
{
	uint32_t base = which ? 0x40 : 0x00, khz = 2 * mhz * 1000, l = khz / 19200;
	uint64_t alpha = ((uint64_t)(khz % 19200) << 40) / 19200;
	uint32_t mode = lv_r(lv_gpucc, base), user;

	if (mhz < 125 || mhz > 750) {
		return false;
	}
	lv_w(lv_gpucc, base, mode & ~1u);               /* output off */
	IODelay(2);
	mode &= ~7u;
	lv_w(lv_gpucc, base, mode);                     /* bypassed, in reset */
	lv_w(lv_gpucc, base + 0x04, l);
	lv_w(lv_gpucc, base + 0x08, (uint32_t)alpha);
	lv_w(lv_gpucc, base + 0x0c, (uint32_t)(alpha >> 32));
	user = lv_r(lv_gpucc, base + 0x10) & ~((3u << 20) | (0xfu << 8));       /* VCO range, post divider 1 */
	user |= (khz >= 1000000 ? 0u : khz >= 500000 ? 2u : 3u) << 20;
	user |= (1u << 24) | 1u;                        /* alpha on, main output */
	lv_w(lv_gpucc, base + 0x10, user);
	lv_w(lv_gpucc, base, mode | 2u);                /* BYPASSNL */
	IODelay(10);                                    /* (5 us at least before the reset goes) */
	lv_w(lv_gpucc, base, mode | 6u);                /* RESET_N */
	for (int i = 0; i < 1000 && !(lv_r(lv_gpucc, base) & 0x80000000u); i++) {
		IODelay(1);
	}
	if (!(lv_r(lv_gpucc, base) & 0x80000000u)) {
		lv_w(lv_gpucc, base, mode);
		LOG("LVGPU PLL%u: NO LOCK at %u MHz x 2 (L %u, mode %#x): left off", which, mhz, l, lv_r(lv_gpucc, base));
		return false;
	}
	lv_w(lv_gpucc, base, mode | 7u);                /* OUTCTRL */
	LOG("LVGPU PLL%u: %u MHz x 2 locked (L %u alpha %#llx, mode %#x user %#x)", which, mhz, l, alpha, lv_r(lv_gpucc, base),
	    lv_r(lv_gpucc, base + 0x10));
	return true;
}

/* the gfx3d root: source 5 = GPLL0 (600 MHz), 1 / 3 = GPU PLL0 / PLL1; div 1 = / 1, 3 = / 2 */
static void
lv_gpu_rcg(uint32_t src, uint32_t div, uint32_t mhz)
{
	lv_w(lv_gpucc, 0x1074, (src << 8) | div);
	lv_w(lv_gpucc, 0x1070, lv_r(lv_gpucc, 0x1070) | 1u);
	for (int i = 0; i < 500 && (lv_r(lv_gpucc, 0x1070) & 1u); i++) {
		IODelay(1);
	}
	lv_gpu_now_mhz = mhz;
}

/* GDSC: clear SW_COLLAPSE, wait for PWR_ON */
''')

patch(r, '''	if (mhz >= 600 || dvfs) {
		lvl = 0x180;                    /* lv_gpu_dvfs (mk_gpudvfs.py): the rail for 600 from the start */
	}
''', '''	if (mhz > 300 || dvfs) {
		lvl = 0x180;                    /* lv_gpu_dvfs (mk_gpudvfs.py): the rail for the top clock from the start */
	}
	PE_parse_boot_argn("lv_gpu_hi", &lv_gpu_hi_mhz, sizeof(lv_gpu_hi_mhz));
	if (lv_gpu_hi_mhz <= 300 || lv_gpu_hi_mhz > 647) {
		lv_gpu_hi_mhz = 647;            /* this chip's bin (fuse 0x7841a0: 0x87) ends at 647 MHz */
	}
''')
patch(r, '''		if (mhz >= 600 && en && lv && lvl >= 0x180) {
			IODelay(3000);                                  /* the rail settles before the clock goes up */
			lv_w(lv_gpucc, 0x1074, (5u << 8) | 1u);         /* GPLL0 / 1 = 600 MHz */
			lv_w(lv_gpucc, 0x1070, lv_r(lv_gpucc, 0x1070) | 1u);
			for (int i = 0; i < 200 && (lv_r(lv_gpucc, 0x1070) & 1u); i++) {
				IODelay(10);
			}
			LOG("LVGPU gfx3d 600 MHz: rcg cmd %#x cfg %#x", lv_r(lv_gpucc, 0x1070), lv_r(lv_gpucc, 0x1074));
		}
''', '''		if (lvl >= 0x180) {
			/* mk_gpupll.py: stock's resource for CX as well (upwards only: nothing else of ours votes it) */
			bool cen = topaz_rpm_write(0, 0x78637772u /* rwcx */, 0, 0x6e657773u /* swen */, 1);
			bool clv = topaz_rpm_write(0, 0x78637772u, 0, 0x6c766c76u /* vlvl */, lvl);
			LOG("LVGPU CX rwcx 0 swen %s vlvl %#x %s", cen ? "acked" : "FAILED", lvl, clv ? "acked" : "FAILED");
			IODelay(3000);                                  /* the rail settles before the clock goes up */
		}
		if (mhz > 647) {
			mhz = 647;
		}
		if (mhz == 600 && en && lv && lvl >= 0x180) {
			lv_gpu_rcg(5, 1, 600);                          /* GPLL0 / 1 */
		} else if (mhz > 300 && en && lv && lvl >= 0x180) {
			lv_gpu_hi_mhz = mhz;
			lv_gpu_pll_ok = lv_gpu_pll(0, mhz);             /* GPU PLL0 at 2 x mhz, RCG / 2 */
			if (lv_gpu_pll_ok) {
				lv_gpu_rcg(1, 3, mhz);
			}
		} else if (dvfs && lv_gpu_hi_mhz != 600 && en && lv) {
			lv_gpu_pll_ok = lv_gpu_pll(0, lv_gpu_hi_mhz);   /* kept running for the governor's steps */
		}
		LOG("LVGPU gfx3d %u MHz: rcg cmd %#x cfg %#x", (uint32_t)lv_gpu_now_mhz, lv_r(lv_gpucc, 0x1070), lv_r(lv_gpucc, 0x1074));
''')

patch(r, '''static void
lv_gpu_clock(bool high)
{
	lv_w(lv_gpucc, 0x1074, (5u << 8) | (high ? 1u : 3u));
	lv_w(lv_gpucc, 0x1070, lv_r(lv_gpucc, 0x1070) | 1u);
	for (int i = 0; i < 200 && (lv_r(lv_gpucc, 0x1070) & 1u); i++) {
		IODelay(1);
	}
}
''', '''/* mk_gpupll.py: the top clock is GPU PLL0 / 2 (a second running source), 600 MHz without it; down is GPLL0 / 2 */
static void
lv_gpu_clock(bool high)
{
	if (!high) {
		lv_gpu_rcg(5, 3, 300);
	} else if (lv_gpu_pll_ok) {
		lv_gpu_rcg(1, 3, lv_gpu_hi_mhz);
	} else {
		lv_gpu_rcg(5, 1, 600);
	}
}
''')
patch(r, '''	LOG("LVDVFS on: %u ms, up above %u %% at 300, down below %u %% at 600", period, up, down);
''', '''	LOG("LVDVFS on: %u ms, up above %u %% at 300, down below %u %% at %u MHz (%s)", period, up, down,
	    lv_gpu_pll_ok ? lv_gpu_hi_mhz : 600, lv_gpu_pll_ok ? "GPU PLL0" : "GPLL0");
''')
patch(r, '''			uint64_t share = (busy - was) * 100000 / ((uint64_t)(high ? 600 : 300) * ns);
''', '''			uint64_t share = (busy - was) * 100000 / ((uint64_t)lv_gpu_now_mhz * ns);
''')
patch(r, '''				LOG("LVDVFS: %u ups, %u downs, %llu %% of the time at 600%s", ups, downs, at_high * 100 / span,
				    lv_gpu_hot ? " (hot: held at 300)" : "");
''', '''				LOG("LVDVFS: %u ups, %u downs, %llu %% of the time at %u MHz%s", ups, downs, at_high * 100 / span,
				    lv_gpu_pll_ok ? lv_gpu_hi_mhz : 600, lv_gpu_hot ? " (hot: held at 300)" : "");
''')

m = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'
patch(m, '''			if (((cfg >> 8) & 7) == 5) {
				mhz = 1200 / ((cfg & 0x1f) + 1);        /* GPLL0 600 MHz, divider (d + 1) / 2 */
			}
''', '''			if (((cfg >> 8) & 7) == 5) {
				mhz = 1200 / ((cfg & 0x1f) + 1);        /* GPLL0 600 MHz, divider (d + 1) / 2 */
			} else if (lv_gpu_now_mhz != 0) {
				mhz = lv_gpu_now_mhz;                   /* a GPU PLL (xnu/src/mk_gpupll.py) */
			}
''')
patch(m, '''extern "C" volatile uint32_t lv_gpu_hot;        /* TopazRpm.cpp GPU DVFS (mk_gpudvfs.py): 1 = hold 300 MHz */
''', '''extern "C" volatile uint32_t lv_gpu_hot;        /* TopazRpm.cpp GPU DVFS (mk_gpudvfs.py): 1 = hold 300 MHz */
extern "C" volatile uint32_t lv_gpu_now_mhz;    /* TopazRpm.cpp: the gfx3d clock now (mk_gpupll.py) */
''')
print('ok')
