"""lavender: GPU clock follows the load, 300 <-> 600 MHz (patch 1171).

The home screen is GPU-bound now (busy 93-100 %) and 600 MHz gives +14 % there (run ah6: 21.6 ->
24.6 fps), Settings and idle need no more than 300. Linux's msm-adreno-tz governor does this with the
stock OPPs; here only GPLL0 / 1 and / 2 are used (no GPU PLL): the GX rail is voted once at boot to the
600 MHz level (0x180, gfx corner 7 - the rail is never lowered from the AP: lv:rpm votes down broke the
GPU) and only the gfx3d RCG divider moves.

  lv_gpu_dvfs=1        on (default 0: as before, fixed lv_gpu_mhz)
  lv_gpu_dvfs_ms=50    sampling period
  lv_gpu_dvfs_up=85    busy % at 300 MHz above which it goes to 600
  lv_gpu_dvfs_down=40  busy % at 600 MHz below which it goes back to 300 (= 80 % of 300)
The thermal guard (lv_therm_hi, LavenderMetrics) holds it at 300 while the chip is hot. LVM shows the
clock at the moment of the line; its busy share is approximate while the clock moves. A line a second
"LVDVFS: N ups, M downs, X % of the time at 600" when on.

usage: python mk_gpudvfs.py XNU_TREE   (after mk_gpuvbif.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


r = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
patch(r, '''	uint32_t lvl = 0x80, mhz = 300;
	/* lavender: lv_gpu_mhz=600 - GPLL0 / 1 on rail level 0x180 (gfx corner 7, good to 647 MHz); mk_gpu600.py */
	PE_parse_boot_argn("lv_gpu_mhz", &mhz, sizeof(mhz));
	if (mhz >= 600) {
		lvl = 0x180;
	}
''', '''	uint32_t lvl = 0x80, mhz = 300, dvfs = 0;
	/* lavender: lv_gpu_mhz=600 - GPLL0 / 1 on rail level 0x180 (gfx corner 7, good to 647 MHz); mk_gpu600.py */
	PE_parse_boot_argn("lv_gpu_mhz", &mhz, sizeof(mhz));
	PE_parse_boot_argn("lv_gpu_dvfs", &dvfs, sizeof(dvfs));
	if (mhz >= 600 || dvfs) {
		lvl = 0x180;                    /* lv_gpu_dvfs (mk_gpudvfs.py): the rail for 600 from the start */
	}
''')

patch(r, '''extern "C" void
lavender_perf_start(void)
{''', '''/*
 * lavender (mk_gpudvfs.py): the gfx3d clock follows the GPU's busy share, GPLL0 / 2 = 300 or / 1 = 600
 * MHz (the rail is at the 600 level already). Busy = RBBM_PERFCTR_RBBM_0 (countable 6, a5_hw_init).
 */
extern "C" volatile uint32_t lv_gpu_hot;        /* LavenderMetrics thermal guard: hold 300 */
volatile uint32_t lv_gpu_hot;

static void
lv_gpu_clock(bool high)
{
	lv_w(lv_gpucc, 0x1074, (5u << 8) | (high ? 1u : 3u));
	lv_w(lv_gpucc, 0x1070, lv_r(lv_gpucc, 0x1070) | 1u);
	for (int i = 0; i < 200 && (lv_r(lv_gpucc, 0x1070) & 1u); i++) {
		IODelay(1);
	}
}

static void
lv_gpu_dvfs_loop(void)
{
	uint32_t period = 50, up = 85, down = 40;
	PE_parse_boot_argn("lv_gpu_dvfs_ms", &period, sizeof(period));
	PE_parse_boot_argn("lv_gpu_dvfs_up", &up, sizeof(up));
	PE_parse_boot_argn("lv_gpu_dvfs_down", &down, sizeof(down));
	if (period < 10) {
		period = 10;
	}
	bool high = false;
	uint64_t was = 0, t0 = 0, said = 0, at_high = 0, span = 0;
	uint32_t ups = 0, downs = 0;
	LOG("LVDVFS on: %u ms, up above %u %% at 300, down below %u %% at 600", period, up, down);
	for (;;) {
		IOSleep(period);
		uint32_t hi = g_r(0x3b1), lo = g_r(0x3b0);
		if (g_r(0x3b1) != hi) {
			hi = g_r(0x3b1);
			lo = g_r(0x3b0);
		}
		uint64_t busy = ((uint64_t)hi << 32) | lo, now, ns;
		absolutetime_to_nanoseconds(mach_absolute_time(), &now);
		ns = now - t0;
		if (t0 != 0 && busy >= was && ns != 0) {
			uint64_t share = (busy - was) * 100000 / ((uint64_t)(high ? 600 : 300) * ns);
			bool want = high;
			if (lv_gpu_hot) {
				want = false;
			} else if (!high && share > up) {
				want = true;
			} else if (high && share < down) {
				want = false;
			}
			if (want != high) {
				lv_gpu_clock(want);
				high = want;
				ups += want;
				downs += !want;
			}
			span += ns;
			at_high += high ? ns : 0;
		}
		was = busy;
		t0 = now;
		if (now - said >= 1000000000ull) {
			if (span != 0) {
				LOG("LVDVFS: %u ups, %u downs, %llu %% of the time at 600%s", ups, downs, at_high * 100 / span,
				    lv_gpu_hot ? " (hot: held at 300)" : "");
			}
			said = now;
			ups = downs = 0;
			at_high = span = 0;
		}
	}
}

extern "C" void
lavender_perf_start(void)
{''')

patch(r, '''		if (gpu >= 11) {
			lavender_gpu_cp();
		}
	}
}
''', '''		if (gpu >= 11) {
			lavender_gpu_cp();
		}
		uint32_t dvfs = 0;
		PE_parse_boot_argn("lv_gpu_dvfs", &dvfs, sizeof(dvfs));
		if (gpu >= 11 && dvfs) {
			lv_gpu_dvfs_loop();             /* (never returns: this thread's work is done) */
		}
	}
}
''')

m = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'
patch(m, '''static uint32_t therm_hi = 85, therm_lo;
''', '''static uint32_t therm_hi = 85, therm_lo;
extern "C" volatile uint32_t lv_gpu_hot;        /* TopazRpm.cpp GPU DVFS (mk_gpudvfs.py): 1 = hold 300 MHz */
''')
patch(m, '''	if (therm_hi == 0 || hottest <= -1000) {
		return;
	}
''', '''	if (therm_hi == 0 || hottest <= -1000) {
		return;
	}
	if (hottest >= (int)therm_hi) {
		lv_gpu_hot = 1;
	} else if (hottest <= (int)therm_lo) {
		lv_gpu_hot = 0;
	}
''')
print('ok')
