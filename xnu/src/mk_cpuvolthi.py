"""lavender: the stock voltage for the top Gold clocks, with the array power mux (patch 1176, PLAN S3 step 3).

2208 MHz has run at the 868 mV XBL leaves, 80 mV under this chip's stock open-loop value (docs/HARDWARE.md:
NOM 1747 MHz 827 mV, TURBO 2150 MHz 937, TURBO_L2 2208 MHz 948; 1958 MHz interpolated ~885). Stable so far,
with no known margin (user 2026-11-28: sort out the voltage that is missing for the top clock).
Above the APM threshold (872 mV, stock DT qcom,apm-threshold-voltage) the cores' memory arrays have to be
fed from the APC rail instead of MX. Stock (cpr3_regulator_switch_apm_mode, clk-cpu-osm.c APM_* values, DT
qcom,apm-mode-ctl / qcom,apm-ctrl-status, second entries = the performance cluster):
  rail to 872 mV -> mode register 0x179d0010 = 2 (APC; 0 = MX) -> wait for 0x179d0018 & 0x1f == 3 (0 for
  MX) -> rail to the new value. The same way down.
With lv_cpu_volt=1 and lv_cpu_volt_hi=1 the governor's steps now do that: 1958 MHz 885 mV, 2150 MHz 937,
2208 MHz 948 (boot-args lv_cpu_mv_1958 / lv_cpu_mv_2150 / lv_cpu_mv_2208; nothing above 960 mV is
accepted). If the mux does not answer, the rail returns below the threshold and the top clocks stay on
the boot voltage as before. If the rail cannot be put back at all, the governor's top clock is pinned to
where the clock is.

  lv_cpu_volt_hi=1      on, the default since 2026-11-28 with the mem-acc level (runs bk1-bk3, bl1-bl2, bm1-bm2: three boots,
                        ~230 s at 948 mV, no crash, no GPU recovery; 62-72 C under load against 57-60 at 868 mV); 0: the top
                        clocks stay on the boot value. Needs lv_cpu_volt=1
  lv_cpu_acc=0          never touch the mem-acc registers (then nothing above 937 mV)
The LVF line's last field becomes "R mV apc|mx".

usage: python mk_cpuvolthi.py XNU_TREE   (after mk_cpuvolt.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


m = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'

patch(m, '''static uint32_t cv_on, cv_boot, cv_now, cv_lo = 768, cv_mid = 828;
''', '''static uint32_t cv_on, cv_boot, cv_now, cv_lo = 768, cv_mid = 828;
/* mk_cpuvolthi.py: the stock voltage above the boot value, through the array power mux */
#define CV_APM_MV       872u                    /* stock DT: qcom,apm-threshold-voltage */
#define CV_TOP_MV       960u
static volatile uint32_t *cv_apm;               /* 0x179d0000: +0x10 mode (2 = APC, 0 = MX), +0x18 status (& 0x1f: 3 / 0) */
static uint32_t cv_hi = 1, cv_top, cv_1958 = 885, cv_2150 = 937, cv_2208 = 948;
static bool cv_apc;                             /* the arrays are on the APC rail */
/*
 * The cores' memory settings ("mem-acc") have three levels by corner (stock OSM table, last column but one:
 * 1 at 1113 MHz, 2 from 1401 to 2150, 3 at 2208). The registers and values are msm8998's (the same KBSS
 * block at the same addresses): 0x179d1368 / 136c / 1370 = 0 0 0x80000000 (1), 0 0 0 (2), 0 0 1 (3). XBL
 * leaves 0 0 0. Run bf1 (2208 MHz at 948 mV with level 2): backboardd died, the GPU got garbage; run bj1
 * (1958 MHz at 885 mV on APC, level 2 as stock has it there): clean. So level 3 goes with the top step,
 * switched at the step below's voltage as stock switches such settings at their threshold.
 */
static uint32_t cv_acc = 1, cv_lvl = 2;         /* lv_cpu_acc=0: never touch them */

static void
cv_level(uint32_t lvl)
{
	apcs_common[0x368 / 4] = 0;
	apcs_common[0x36c / 4] = 0;
	apcs_common[0x370 / 4] = lvl == 3 ? 1u : 0u;
	__asm__ volatile ("dsb sy" ::: "memory");
	IODelay(50);
	cv_lvl = lvl;
}
''')

# cv_set: up to cv_top
patch(m, '''	if (mv < 768 || mv > cv_boot || (mv >> 8) != 3) {
		return false;
	}
	if (mv == cv_now) {
		return true;
	}
''', '''	if (mv < 768 || mv > cv_top || (mv >> 8) != 3) {
		return false;
	}
	if (mv == cv_now) {
		return true;
	}
''')

patch(m, '''static uint32_t
cv_for(uint32_t l)
{
	uint32_t mv = l <= 73 ? cv_lo : l <= 91 ? cv_mid : cv_boot;

	return mv > cv_boot ? cv_boot : mv < 768 ? 768 : mv;
}
''', '''/* the array power mux to APC (above 872 mV) or MX; the rail must be at 872 mV */
static bool
cv_mux(bool apc)
{
	cv_apm[0x10 / 4] = apc ? 2u : 0u;
	__asm__ volatile ("dsb sy" ::: "memory");
	for (int n = 0; n < 5000; n++) {
		if ((cv_apm[0x18 / 4] & 0x1f) == (apc ? 3u : 0u)) {
			cv_apc = apc;
			return true;
		}
		IODelay(1);
	}
	return false;
}

/* the rail to mv, through 872 mV and the mux when it crosses the threshold */
static bool
cv_goto(uint32_t mv)
{
	bool apc = mv >= CV_APM_MV;
	uint32_t lvl = cv_hi && cv_acc && mv > cv_2150 ? 3 : 2;

	if (lvl < cv_lvl) {                             /* leaving the top level: at the step below's voltage */
		if (!cv_set(cv_2150)) {
			return false;
		}
		IODelay(100);
		cv_level(2);
	}
	if (cv_hi && apc != cv_apc) {
		if (!cv_set(CV_APM_MV)) {
			return false;
		}
		IODelay(300);
		if (!cv_mux(apc)) {
			IOLog("LVF rail: the array power mux did not go to %s (status %#x): the top clocks stay on %u mV\\n",
			    apc ? "APC" : "MX", cv_apm[0x18 / 4], cv_boot);
			cv_hi = 0;
			cv_top = cv_boot;
			if (!cv_apc) {
				return cv_set(mv > cv_boot ? cv_boot : mv);
			}
			return false;                   /* (stuck on APC below the threshold: the caller pins the clock) */
		}
	}
	if (lvl > cv_lvl) {                             /* to the top level: at the step below's voltage */
		if (!cv_set(cv_2150)) {
			return false;
		}
		IODelay(300);
		cv_level(3);
	}
	return cv_set(mv);
}

static uint32_t
cv_for(uint32_t l)
{
	uint32_t mv = l <= 73 ? cv_lo : l <= 91 ? cv_mid : !cv_hi ? cv_boot : l <= 102 ? cv_1958 : l <= 112 ? cv_2150 : cv_2208;

	return mv > cv_top ? cv_top : mv < 768 ? 768 : mv;
}
''')

patch(m, '''	cv_boot = cv_now = s2;
	if (mode == 2) {
''', '''	cv_boot = cv_now = cv_top = s2;
	(void)PE_parse_boot_argn("lv_cpu_volt_hi", &cv_hi, sizeof(cv_hi));
	(void)PE_parse_boot_argn("lv_cpu_mv_1958", &cv_1958, sizeof(cv_1958));
	(void)PE_parse_boot_argn("lv_cpu_mv_2150", &cv_2150, sizeof(cv_2150));
	(void)PE_parse_boot_argn("lv_cpu_mv_2208", &cv_2208, sizeof(cv_2208));
	cv_apm = (volatile uint32_t *)ml_io_map(0x179d0000ull, 0x1000);
	if (cv_apm != NULL) {
		uint32_t st = cv_apm[0x18 / 4] & 0x1f;
		IOLog("LVF rail: array power mux mode %#x status %#x (%s), Silver's %#x / %#x; lv_cpu_volt_hi=%u: %u / %u / %u mV\\n",
		    cv_apm[0x10 / 4], cv_apm[0x18 / 4], st == 3 ? "APC" : st == 0 ? "MX" : "?", cv_apm[0x04 / 4], cv_apm[0x0c / 4],
		    cv_hi, cv_1958, cv_2150, cv_2208);
		cv_apc = st == 3;
		if (st != 0 && st != 3) {
			cv_hi = 0;                      /* neither supply: leave it alone */
		}
	} else {
		cv_hi = 0;
	}
	(void)PE_parse_boot_argn("lv_cpu_acc", &cv_acc, sizeof(cv_acc));
	IOLog("LVF rail: mem-acc 0x179d1368.. = %#x %#x %#x (lv_cpu_acc=%u)\\n", apcs_common[0x368 / 4], apcs_common[0x36c / 4],
	    apcs_common[0x370 / 4], cv_acc);
	if (apcs_common[0x368 / 4] != 0 || apcs_common[0x36c / 4] != 0 || apcs_common[0x370 / 4] != 0) {
		cv_acc = 0;                             /* not the level 2 XBL is known to leave: hands off */
	}
	if (cv_hi && mode == 1) {
		cv_top = cv_acc ? CV_TOP_MV : cv_2150;  /* without the top level, nothing above the step below's voltage */
	} else {
		cv_hi = 0;
	}
	if (mode == 2) {
''')

# the governor's step: cv_goto instead of cv_set, and a rail that cannot be put back pins the clock
patch(m, '''	if (cv_on && mv > cv_now) {
		if (!cv_set(mv)) {
			goto broken;
		}
		IODelay(500);
	}
	r = gold_set_how(to, true);
	if (r == 0 && cv_on && mv < cv_now && !cv_set(mv)) {
		goto broken;
	}
	return r;
broken:
	/* the boot value back (with the clock where it is or lower, that is always enough), and no more of this */
	cv_on = 0;
	(void)lv_pmic_word((CV_SID << 16) | (cv_base[1] + 0x40), (uint16_t)cv_boot);
	IODelay(500);
	IOLog("LVF rail: a write failed going L %u -> %u: back to %u mV (S2 %u, S3 %u), voltage steps off\\n", from, to, cv_boot,
	    cv_read(0, 0x40), cv_read(1, 0x40));
	cv_now = cv_boot;
	return gold_set_how(to, true);
}
''', '''	if (cv_on && mv > cv_now) {
		if (!cv_goto(mv)) {
			goto broken;
		}
		IODelay(500);
	}
	r = gold_set_how(to, true);
	if (r == 0 && cv_on && mv < cv_now && !cv_goto(mv)) {
		from = to;                              /* (the clock is at `to` already) */
		goto broken;
	}
	return r;
broken:
	/*
	 * The clock is still at `from` and the rail is at or above what `from` needs. Try the boot value
	 * (on MX); if even that does not take, the governor's top clock becomes where the clock is.
	 */
	cv_on = 0;
	cv_now = cv_read(0, 0x40);
	{
		bool back = (cv_lvl == 2 || (cv_set(cv_2150) && (cv_level(2), true))) &&
		    (!cv_apc || (cv_set(CV_APM_MV) && cv_mux(false))) && cv_set(cv_boot);
		IODelay(500);
		IOLog("LVF rail: a step failed going L %u -> %u: rail %s (S2 %u, S3 %u mV, %s), voltage steps off%s\\n", from, to,
		    back ? "back at the boot value" : "NOT restored", cv_read(0, 0x40), cv_read(1, 0x40), cv_apc ? "APC" : "MX",
		    back ? "" : ", top clock pinned");
		if (!back) {
			uint32_t pin = cd_step[0];
			for (unsigned i = 0; i < CD_STEPS; i++) {
				if (cd_step[i] <= from) {
					pin = cd_step[i];
				}
			}
			cd_max = pin < cd_max ? pin : cd_max;
			return -3;
		}
	}
	return from == to ? 0 : gold_set_how(to, true);
}
''')

patch(m, '''				    "%u touch | top %u%% cap %u | %u mV\\n", ns / 1000000, at[0] * 100 / all, at[1] * 100 / all, at[2] * 100 / all,
				    at[3] * 100 / all, at[4] * 100 / all, at[5] * 100 / all, ups, downs, boosts, top, (uint32_t)gold_cap,
				    cv_on ? cv_now : cv_read(0, 0x40));
''', '''				    "%u touch | top %u%% cap %u | %u mV %s acc %u\\n", ns / 1000000, at[0] * 100 / all, at[1] * 100 / all, at[2] * 100 / all,
				    at[3] * 100 / all, at[4] * 100 / all, at[5] * 100 / all, ups, downs, boosts, top, (uint32_t)gold_cap,
				    cv_on ? cv_now : cv_read(0, 0x40), cv_apc ? "apc" : "mx", cv_lvl);
''')
print('ok')
