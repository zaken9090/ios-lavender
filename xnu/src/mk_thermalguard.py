"""lavender: the Gold clock steps down when the chip is hot (patch 1165).

There was no thermal control at all (stock: msm-thermal core limit, hotplug at 105 C, reset at 115 C,
and thermal-engine above them). The metrics thread reads TSENS every second anyway: when the hottest
sensor reaches lv_therm_hi (85 C) the Gold PLL goes one stock step down (115, 112, 102, 91, 73, 58);
when it has been at or below lv_therm_lo (hi - 10) for 10 s it goes one step back up, at most to the
clock that was asked for (the shim's / lv_gold_l / the last lv:gold). Each step is logged
("LV THERMAL: ...").

  lv_therm_hi=N    limit in C (85; 0 = no guard)       lv_therm_lo=N    (hi - 10)
  lv_metrics=0 now only silences the lines: the thread keeps running for the guard.

usage: python mk_thermalguard.py XNU_TREE   (after mk_gpucounters.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'
s = open(path, newline='').read()


def sub(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:70], s.count(old))
    s = s.replace(old, new)


# lv_gold_set_l (asked for from outside) remembers the clock; the guard uses the inner one
sub('''extern "C" int
lv_gold_set_l(uint32_t l)
{
	static IOLock *lock;''', '''static uint32_t gold_want;               /* the L asked for (xnu/src/mk_thermalguard.py): the guard returns to it */

static int
gold_set(uint32_t l)
{
	static IOLock *lock;''')
sub('''	return r;
}

/* ---- CPU by process''', '''	return r;
}

extern "C" int
lv_gold_set_l(uint32_t l)
{
	int r = gold_set(l);
	if (r == 0) {
		gold_want = l;
	}
	return r;
}

/* ---- the Gold clock steps down when the chip is hot (xnu/src/mk_thermalguard.py) ---- */

static uint32_t therm_hi = 85, therm_lo;
static bool quiet;                              /* lv_metrics=0: no lines, the guard still runs */

static void
thermal_guard(int hottest)
{
	static const uint8_t step[] = { 58, 73, 91, 102, 112, 115 };
	static uint32_t cool_s;
	uint32_t l = pll_gold[1] & 0xffff, to = 0;

	if (therm_hi == 0 || hottest <= -1000) {
		return;
	}
	if (gold_want == 0) {
		gold_want = l;
	}
	if (hottest >= (int)therm_hi) {
		cool_s = 0;
		for (int i = (int)sizeof(step) - 1; i >= 0; i--) {
			if (step[i] < l) {
				to = step[i];
				break;
			}
		}
		if (to == 0) {
			return;                         /* already at the lowest step */
		}
		IOLog("LV THERMAL: %d C, limit %u: Gold L %u -> %u (%u MHz)\\n", hottest, therm_hi, l, to, to * 192 / 10);
		gold_set(to);
	} else if (hottest <= (int)therm_lo && l < gold_want) {
		if (++cool_s < 10) {
			return;
		}
		cool_s = 0;
		to = gold_want;
		for (unsigned i = 0; i < sizeof(step); i++) {
			if (step[i] > l && step[i] <= gold_want) {
				to = step[i];
				break;
			}
		}
		IOLog("LV THERMAL: %d C, cool (%u): Gold L %u -> %u (%u MHz)\\n", hottest, therm_lo, l, to, to * 192 / 10);
		gold_set(to);
	} else {
		cool_s = 0;
	}
}

/* ---- CPU by process''')

# the thread: the guard every round, lines only when not quiet
sub('''	if (info != 0) {
		cpu_report();
	}
''', '''	if (info != 0 && !quiet) {
		cpu_report();
	}
''')
sub('''		n += snprintf(line + n, sizeof(line) - n, " %d %d %d %d gpu %d max %d", tsens(3, &ok), tsens(4, &ok), tsens(5, &ok),
		    tsens(6, &ok), tsens(8, &ok), max);
''', '''		n += snprintf(line + n, sizeof(line) - n, " %d %d %d %d gpu %d max %d", tsens(3, &ok), tsens(4, &ok), tsens(5, &ok),
		    tsens(6, &ok), tsens(8, &ok), max);
		thermal_guard(max);
''')
sub('''		if (ns != 0) {
			IOLog("%s\\n", line);
		}
''', '''		if (ns != 0 && !quiet) {
			IOLog("%s\\n", line);
		}
''')
sub('''				if (had && ns != 0) {
					IOLog("LVG''', '''				if (had && ns != 0 && !quiet) {
					IOLog("LVG''')
sub('''		if (top_n != 0) {
			proc_line(ns);
		}
		if (khz_every != 0 && lines % khz_every == 0) {''', '''		if (top_n != 0 && !quiet) {
			proc_line(ns);
		}
		if (khz_every != 0 && !quiet && lines % khz_every == 0) {''')
sub('''	if (period_ms == 0) {
		return;
	}
''', '''	(void)PE_parse_boot_argn("lv_therm_hi", &therm_hi, sizeof(therm_hi));
	therm_lo = therm_hi > 10 ? therm_hi - 10 : 0;
	(void)PE_parse_boot_argn("lv_therm_lo", &therm_lo, sizeof(therm_lo));
	if (period_ms == 0) {
		if (therm_hi == 0) {
			return;
		}
		quiet = true;                           /* no lines, the thermal guard only */
		period_ms = 1000;
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
