"""lavender: the Gold clock follows the load, with a boost while the screen is touched (patch 1174, PLAN S3).

Until now the four Gold cores sat at one clock (1747 MHz from the shim, lv_gold_l). Measured 2026-11-28
(docs/CORES.md): 2208 MHz halves the late frames in Settings (4.1-4.6 % against 6.3-8.3 %), and nothing
needs the top clock while the phone idles. A thread ("lv_cpu_dvfs") now picks one of the stock steps
1113.6 / 1401.6 / 1747.2 / 1958.4 / 2150.4 / 2208 MHz (L 58 73 91 102 112 115):
  - a touch report (SweetHID) asks for the top step at once and for lv_cpu_touch_ms after the last one;
  - otherwise the busiest core's share over the last period: at or above lv_cpu_dvfs_up -> the top step;
    below it -> the lowest step that would keep that core under lv_cpu_dvfs_up, after lv_cpu_dvfs_hold
    periods in a row;
  - the thermal guard (lv_therm_hi) lowers a cap by a step while hot and lifts it when cool.
The rail is not touched here: all these clocks have run at the 868 mV XBL leaves (2208 MHz for days).
Voltage per step is the next patch.

  lv_cpu_dvfs=0          off: the clock stays where the shim or lv_gold_l put it (lv_gold_l=N also turns it off)
  lv_cpu_dvfs_ms=100     period (the load is read from the 10 ms tick counters)
  lv_cpu_dvfs_up=70      busiest core's share that asks for the top step
  lv_cpu_dvfs_hold=3     periods below before stepping down
  lv_cpu_touch_ms=1500   the top step is held this long after the last touch report
  lv_cpu_min_l=58, lv_cpu_max_l=115   the range (PLL L, x 19.2 MHz)
A line a second: "LVF <ms>: 1113 a% 1401 b% 1747 c% 1958 d% 2150 e% 2208 f% | U ups D downs T touch | top P% cap L"

usage: python mk_cpudvfs.py XNU_TREE   (after mk_vlock60.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


m = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'

patch(m, '''#include <IOKit/IOLib.h>
#include <kern/thread.h>
''', '''#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <kern/clock.h>
#include <kern/thread.h>
''')

# a quick way through gold_set for the governor: short waits, no measuring, no line
patch(m, '''static int
gold_set(uint32_t l)
{
	static IOLock *lock;
''', '''static int gold_set_how(uint32_t l, bool fast);

static int
gold_set(uint32_t l)
{
	return gold_set_how(l, false);
}

/* fast (mk_cpudvfs.py): the governor's steps - 50 us waits, no clock measurement, no line */
static int
gold_set_how(uint32_t l, bool fast)
{
	static IOLock *lock;
''')
patch(m, '''	pll_gold[0] = 2;
	__asm__ volatile ("dsb sy" ::: "memory");
	IODelay(1000);
	pll_gold[0] = 6;
	__asm__ volatile ("dsb sy" ::: "memory");
	IODelay(1000);
''', '''	pll_gold[0] = 2;
	__asm__ volatile ("dsb sy" ::: "memory");
	IODelay(fast ? 50 : 1000);
	pll_gold[0] = 6;
	__asm__ volatile ("dsb sy" ::: "memory");
	IODelay(fast ? 50 : 1000);
''')
patch(m, '''	IOLockUnlock(lock);
	core_measure();
	IOLog("LV GOLD: L %u -> %u (%u MHz): %s, measured %u %u %u %u kHz\\n", was, l, l * 192 / 10,
''', '''	IOLockUnlock(lock);
	if (fast && r == 0) {
		return 0;
	}
	core_measure();
	IOLog("LV GOLD: L %u -> %u (%u MHz): %s, measured %u %u %u %u kHz\\n", was, l, l * 192 / 10,
''')

# the governor, before the thermal guard (which moves its cap)
patch(m, '''/* ---- the Gold clock steps down when the chip is hot (xnu/src/mk_thermalguard.py) ---- */

static uint32_t therm_hi = 85, therm_lo;
''', '''/* ---- the Gold clock follows the load (xnu/src/mk_cpudvfs.py) ---- */

static const uint8_t cd_step[] = { 58, 73, 91, 102, 112, 115 };
#define CD_STEPS        ((unsigned)sizeof(cd_step))
static uint32_t cd_on = 1, cd_ms = 100, cd_up = 70, cd_hold = 3, cd_touch_ms = 1500, cd_min = 58, cd_max = 115;
static volatile uint64_t cd_touch_abs;          /* mach time of the last touch report */
static volatile uint32_t cd_cur;                /* the L now */
static volatile uint32_t gold_cap = GOLD_L_MAX; /* the thermal guard's limit */
static volatile bool cd_running;
static IOLock *cd_lock;
static int cd_event;
static bool quiet;                              /* lv_metrics=0: no lines, the guard still runs */

/* SweetHID.cpp: a touch report came - the top step at once */
extern "C" void lv_cpu_touch(void);
extern "C" void
lv_cpu_touch(void)
{
	cd_touch_abs = mach_absolute_time();
	if (cd_running && cd_cur < cd_max && cd_cur < gold_cap) {
		IOLockWakeup(cd_lock, &cd_event, true);
	}
}

static void
cpu_dvfs_thread(__unused void *arg, __unused wait_result_t w)
{
	uint32_t lb[LVM_CPUS] = {}, la[LVM_CPUS] = {}, below = 0, top = 0, ups = 0, downs = 0, boosts = 0;
	uint64_t at[CD_STEPS] = {}, period_abs, touch_abs, second_abs;
	uint64_t last = mach_absolute_time(), said = last, load_at = 0;
	bool failed_said = false;

	nanoseconds_to_absolutetime((uint64_t)cd_ms * NSEC_PER_MSEC, &period_abs);
	nanoseconds_to_absolutetime((uint64_t)cd_touch_ms * NSEC_PER_MSEC, &touch_abs);
	nanoseconds_to_absolutetime(NSEC_PER_SEC, &second_abs);
	cd_cur = pll_gold[1] & 0xffff;
	cd_running = true;
	IOLog("LVF on: Gold %u..%u MHz, every %u ms, up at %u %%, down after %u periods, touch %u ms\\n", cd_min * 192 / 10,
	    cd_max * 192 / 10, cd_ms, cd_up, cd_hold, cd_touch_ms);
	for (;;) {
		AbsoluteTime deadline;
		clock_interval_to_deadline(cd_ms, kMillisecondScale, &deadline);
		IOLockLock(cd_lock);
		(void)IOLockSleepDeadline(cd_lock, &cd_event, deadline, THREAD_UNINT);
		IOLockUnlock(cd_lock);

		uint64_t now = mach_absolute_time();
		for (unsigned i = 0; i < CD_STEPS; i++) {
			if (cd_step[i] >= cd_cur || i == CD_STEPS - 1) {
				at[i] += now - last;
				break;
			}
		}
		last = now;

		/* the busiest core's share, over a whole period (a touch may have woken us early) */
		bool sampled = false;
		if (now - load_at >= period_abs - period_abs / 8) {
			top = 0;
			for (int c = 0; c < LVM_CPUS && c <= ml_get_max_cpu_number(); c++) {
				processor_t p = cpu_to_processor(c);
				integer_t t[4] = { 0, 0, 0, 0 };
				mach_msg_type_number_t n = 4;
				host_t host = HOST_NULL;
				if (p == PROCESSOR_NULL ||
				    processor_info(p, PROCESSOR_CPU_LOAD_INFO, &host, (processor_info_t)t, &n) != KERN_SUCCESS) {
					continue;
				}
				uint32_t b = (uint32_t)t[0] + (uint32_t)t[1] + (uint32_t)t[3], a = b + (uint32_t)t[2];
				uint32_t db = b - lb[c], da = a - la[c], pct = da != 0 ? db * 100 / da : 0;
				lb[c] = b;
				la[c] = a;
				top = pct > top ? pct : top;
			}
			sampled = load_at != 0;
			load_at = now;
		}

		uint32_t limit = cd_max < gold_cap ? cd_max : gold_cap, want = cd_cur;
		bool touch = cd_touch_abs != 0 && now - cd_touch_abs < touch_abs;
		if (touch) {
			want = limit;
			below = 0;
		} else if (sampled) {
			if (top >= cd_up) {
				want = limit;
				below = 0;
			} else {
				uint32_t need = cd_cur * top / cd_up, to = cd_step[CD_STEPS - 1];
				for (unsigned i = 0; i < CD_STEPS; i++) {
					if (cd_step[i] >= need && cd_step[i] >= cd_min) {
						to = cd_step[i];
						break;
					}
				}
				if (to < cd_cur) {
					if (++below >= cd_hold) {
						want = to;
						below = 0;
					}
				} else {
					below = 0;
				}
			}
		}
		if (want > limit) {
			want = limit;
		}
		if (want != cd_cur) {
			if (gold_set_how(want, true) == 0) {
				ups += want > cd_cur;
				downs += want < cd_cur;
				boosts += touch && want > cd_cur;
				cd_cur = want;
			} else if (!failed_said) {
				failed_said = true;
				IOLog("LVF: a step to L %u failed (see LV GOLD)\\n", want);
				cd_cur = pll_gold[1] & 0xffff;
			}
		}
		if (now - said >= second_abs) {
			uint64_t all = 0, ns = 0;
			for (unsigned i = 0; i < CD_STEPS; i++) {
				all += at[i];
			}
			absolutetime_to_nanoseconds(now - said, &ns);
			if (!quiet && all != 0) {
				IOLog("LVF %llu ms: 1113 %llu%% 1401 %llu%% 1747 %llu%% 1958 %llu%% 2150 %llu%% 2208 %llu%% | %u ups %u downs "
				    "%u touch | top %u%% cap %u\\n", ns / 1000000, at[0] * 100 / all, at[1] * 100 / all, at[2] * 100 / all,
				    at[3] * 100 / all, at[4] * 100 / all, at[5] * 100 / all, ups, downs, boosts, top, (uint32_t)gold_cap);
			}
			bzero(at, sizeof(at));
			ups = downs = boosts = 0;
			said = now;
		}
	}
}

static void
cpu_dvfs_start(void)
{
	thread_t t;

	(void)PE_parse_boot_argn("lv_cpu_dvfs", &cd_on, sizeof(cd_on));
	(void)PE_parse_boot_argn("lv_cpu_dvfs_ms", &cd_ms, sizeof(cd_ms));
	(void)PE_parse_boot_argn("lv_cpu_dvfs_up", &cd_up, sizeof(cd_up));
	(void)PE_parse_boot_argn("lv_cpu_dvfs_hold", &cd_hold, sizeof(cd_hold));
	(void)PE_parse_boot_argn("lv_cpu_touch_ms", &cd_touch_ms, sizeof(cd_touch_ms));
	(void)PE_parse_boot_argn("lv_cpu_min_l", &cd_min, sizeof(cd_min));
	(void)PE_parse_boot_argn("lv_cpu_max_l", &cd_max, sizeof(cd_max));
	if (cd_ms < 20) {
		cd_ms = 20;
	}
	if (cd_up == 0 || cd_up > 100) {
		cd_up = 70;
	}
	if (cd_max > GOLD_L_MAX || cd_max < cd_step[0]) {
		cd_max = GOLD_L_MAX;
	}
	if (cd_min < cd_step[0] || cd_min > cd_max) {
		cd_min = cd_step[0];
	}
	if (!cd_on || (cd_lock = IOLockAlloc()) == NULL) {
		return;
	}
	if (kernel_thread_start(cpu_dvfs_thread, NULL, &t) == KERN_SUCCESS) {
		thread_set_thread_name(t, "lv_cpu_dvfs");
		thread_deallocate(t);
	}
}

/* ---- the Gold clock steps down when the chip is hot (xnu/src/mk_thermalguard.py) ---- */

static uint32_t therm_hi = 85, therm_lo;
''')
patch(m, '''extern "C" volatile uint32_t lv_gpu_hot;        /* TopazRpm.cpp GPU DVFS (mk_gpudvfs.py): 1 = hold 300 MHz */
static bool quiet;                              /* lv_metrics=0: no lines, the guard still runs */
''', '''extern "C" volatile uint32_t lv_gpu_hot;        /* TopazRpm.cpp GPU DVFS (mk_gpudvfs.py): 1 = hold 300 MHz */
''')
patch(m, '''	if (gold_want == 0) {
		gold_want = l;
	}
	if (hottest >= (int)therm_hi) {
		cool_s = 0;
''', '''	if (cd_running) {
		/* mk_cpudvfs.py: with the governor on, the guard moves a cap and the governor follows it */
		uint32_t cap = gold_cap;
		if (hottest >= (int)therm_hi) {
			cool_s = 0;
			for (int i = (int)sizeof(step) - 1; i >= 0; i--) {
				if (step[i] < cap) {
					IOLog("LV THERMAL: %d C, limit %u: Gold cap L %u -> %u (%u MHz)\\n", hottest, therm_hi, cap, step[i],
					    step[i] * 192 / 10);
					gold_cap = step[i];
					break;
				}
			}
		} else if (hottest <= (int)therm_lo && cap < GOLD_L_MAX) {
			if (++cool_s >= 10) {
				cool_s = 0;
				for (unsigned i = 0; i < sizeof(step); i++) {
					if (step[i] > cap) {
						IOLog("LV THERMAL: %d C, cool (%u): Gold cap L %u -> %u (%u MHz)\\n", hottest, therm_lo, cap,
						    step[i], step[i] * 192 / 10);
						gold_cap = step[i];
						break;
					}
				}
			}
		} else {
			cool_s = 0;
		}
		return;
	}
	if (gold_want == 0) {
		gold_want = l;
	}
	if (hottest >= (int)therm_hi) {
		cool_s = 0;
''')
patch(m, '''	if (PE_parse_boot_argn("lv_gold_l", &gold_l, sizeof(gold_l)) && gold_l != 0) {
		lv_gold_set_l(gold_l);                  /* (xnu/src/mk_goldclock.py) */
	}
''', '''	if (PE_parse_boot_argn("lv_gold_l", &gold_l, sizeof(gold_l)) && gold_l != 0) {
		lv_gold_set_l(gold_l);                  /* (xnu/src/mk_goldclock.py) */
	} else {
		cpu_dvfs_start();                       /* the clock follows the load (xnu/src/mk_cpudvfs.py) */
	}
''')

h = f'{tree}/iokit/Kernel/arm/hid/SweetHID.cpp'
patch(h, '''	if (was != down) {
		IOLog("SWEET HID: touch %d %s at %d,%d%s\\n", finger, down ? "down" : "up", x, y,
		    fEdge[finger] ? " edge" : "");
	}
''', '''	if (was != down) {
		IOLog("SWEET HID: touch %d %s at %d,%d%s\\n", finger, down ? "down" : "up", x, y,
		    fEdge[finger] ? " edge" : "");
	}
	lv_cpu_touch();                                 /* lavender: the Gold clock's touch boost (mk_cpudvfs.py) */
''')
s = open(h, newline='').read()
anchor = '#include '
i = s.rindex('\n#include ')
j = s.index('\n', i + 1)
s = s[:j + 1] + '\nextern "C" void lv_cpu_touch(void);              /* LavenderMetrics.cpp (mk_cpudvfs.py) */\n' + s[j + 1:]
open(h, 'w', newline='\n').write(s)
print('ok')
