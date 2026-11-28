"""lavender: the Gold rail follows the Gold clock, downwards only (patch 1175, PLAN S3 step 2).

The Gold cores' rail is PM660 S2 + S3 (FTS426, slave 1, 0x1700 / 0x1a00; registers 0x40 / 0x41 = the set
point in mV, 0x42 / 0x43 = what is in force). XBL leaves 868 mV and nothing changed it: CPRh never ran
(docs/HARDWARE.md). S2 / S3 report status 0x94 (loaded), S1 0x84 (the Silver cores are off). This chip's
stock open-loop voltages: 1113 MHz 700 mV, 1401 MHz 755, 1747 MHz 827, 2150 MHz 937, 2208 MHz 948; above
872 mV the array power mux has to move from MX to APC first, which is not done here.
So with the governor (mk_cpudvfs.py) the rail now goes DOWN with the clock and never above what XBL
left: by default 768 mV at 1113 / 1401 MHz, 828 mV at 1747 MHz, the boot value (868) from 1958 MHz up -
at or above stock for the three lower steps; 2208 MHz stays where it has run for weeks. 768 keeps the
upper set-point byte at 0x03 for every value: one byte changes, no in-between voltage.
Up: voltage first, 500 us, then the clock. Down: the clock first, then the voltage. A write that fails
or does not read back puts the boot value back and turns this off for the boot.

  lv_cpu_volt=1         on (default 0 until tested enough)
  lv_cpu_volt=2         test only: S2 alone 4 mV down, what S2 and S3 then report, back up (are they ganged?)
  lv_cpu_mv_lo=768      mV at 1113 and 1401 MHz (768..boot)
  lv_cpu_mv_mid=828     mV at 1747 MHz (768..boot)
The LVF line ends with the rail's set point: "... cap L | R mV".

usage: python mk_cpuvolt.py XNU_TREE   (after mk_cpudvfs.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


m = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'

patch(m, '''/* SweetHID.cpp: a touch report came - the top step at once */
''', '''/* ---- the Gold rail, PM660 S2 + S3 (xnu/src/mk_cpuvolt.py) ---- */

#define CV_SID          1u
static const uint16_t cv_base[2] = { 0x1700, 0x1a00 };
static uint32_t cv_on, cv_boot, cv_now, cv_lo = 768, cv_mid = 828;

/* reg 0x40 (set point) or 0x42 (in force) of S2 (0) / S3 (1), in mV; 0 = unreadable */
static uint32_t
cv_read(unsigned which, unsigned reg)
{
	uint8_t lo = 0, hi = 0;

	if (lv_pmic_byte(0, (CV_SID << 16) | (cv_base[which] + reg), &lo) != 0 ||
	    lv_pmic_byte(0, (CV_SID << 16) | (cv_base[which] + reg + 1), &hi) != 0) {
		return 0;
	}
	return ((uint32_t)hi << 8) | lo;
}

static bool
cv_write_one(unsigned which, uint32_t mv)
{
	uint8_t lo = (uint8_t)mv, hi = (uint8_t)(mv >> 8);

	return lv_pmic_byte(1, (CV_SID << 16) | (cv_base[which] + 0x40), &lo) == 0 &&
	       lv_pmic_byte(1, (CV_SID << 16) | (cv_base[which] + 0x41), &hi) == 0 && cv_read(which, 0x40) == mv;
}

/* both phases to mv (768..the boot value: the upper byte stays 0x03); false = not done */
static bool
cv_set(uint32_t mv)
{
	if (mv < 768 || mv > cv_boot || (mv >> 8) != 3) {
		return false;
	}
	if (mv == cv_now) {
		return true;
	}
	/* up: S2 (the one XBL's sequence names first) then S3; down: the other way round */
	unsigned first = mv > cv_now ? 0 : 1;
	if (!cv_write_one(first, mv) || !cv_write_one(first ^ 1, mv)) {
		return false;
	}
	cv_now = mv;
	return true;
}

static uint32_t
cv_for(uint32_t l)
{
	uint32_t mv = l <= 73 ? cv_lo : l <= 91 ? cv_mid : cv_boot;

	return mv > cv_boot ? cv_boot : mv < 768 ? 768 : mv;
}

static void
cv_start(void)
{
	uint32_t mode = 0, s2 = cv_read(0, 0x40), s3 = cv_read(1, 0x40);

	(void)PE_parse_boot_argn("lv_cpu_volt", &mode, sizeof(mode));
	(void)PE_parse_boot_argn("lv_cpu_mv_lo", &cv_lo, sizeof(cv_lo));
	(void)PE_parse_boot_argn("lv_cpu_mv_mid", &cv_mid, sizeof(cv_mid));
	IOLog("LVF rail: S2 %u mV (in force %u), S3 %u mV (in force %u); lv_cpu_volt=%u, %u mV to 1401 MHz, %u at 1747\\n", s2,
	    cv_read(0, 0x42), s3, cv_read(1, 0x42), mode, cv_lo, cv_mid);
	if (mode == 0 || s2 == 0 || s2 != s3 || (s2 >> 8) != 3 || s2 < 800 || s2 > 872) {
		return;                                 /* off, unreadable, or not what XBL is known to leave */
	}
	cv_boot = cv_now = s2;
	if (mode == 2) {
		uint8_t lo = (uint8_t)(s2 - 4), hi = (uint8_t)((s2 - 4) >> 8);
		int w = lv_pmic_byte(1, (CV_SID << 16) | (cv_base[0] + 0x40), &lo);
		w |= lv_pmic_byte(1, (CV_SID << 16) | (cv_base[0] + 0x41), &hi);
		IODelay(2000);
		IOLog("LVF rail test: S2 written %u mV (%s): S2 set %u in force %u, S3 set %u in force %u\\n", s2 - 4,
		    w == 0 ? "ok" : "REFUSED", cv_read(0, 0x40), cv_read(0, 0x42), cv_read(1, 0x40), cv_read(1, 0x42));
		lo = (uint8_t)s2;
		hi = (uint8_t)(s2 >> 8);
		w = lv_pmic_byte(1, (CV_SID << 16) | (cv_base[0] + 0x40), &lo);
		w |= lv_pmic_byte(1, (CV_SID << 16) | (cv_base[0] + 0x41), &hi);
		IODelay(2000);
		IOLog("LVF rail test: S2 back (%s): S2 set %u in force %u, S3 set %u in force %u\\n", w == 0 ? "ok" : "REFUSED",
		    cv_read(0, 0x40), cv_read(0, 0x42), cv_read(1, 0x40), cv_read(1, 0x42));
		return;
	}
	cv_on = 1;
}

/* the governor's step: the rail before the clock on the way up, after it on the way down */
static int
cv_gold_step(uint32_t from, uint32_t to)
{
	uint32_t mv = cv_for(to);
	int r;

	if (cv_on && mv > cv_now) {
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
	{
		uint8_t lo = (uint8_t)cv_boot, hi = (uint8_t)(cv_boot >> 8);
		for (unsigned i = 0; i < 2; i++) {
			(void)lv_pmic_byte(1, (CV_SID << 16) | (cv_base[i] + 0x40), &lo);
			(void)lv_pmic_byte(1, (CV_SID << 16) | (cv_base[i] + 0x41), &hi);
		}
	}
	IODelay(500);
	IOLog("LVF rail: a write failed going L %u -> %u: back to %u mV (S2 %u, S3 %u), voltage steps off\\n", from, to, cv_boot,
	    cv_read(0, 0x40), cv_read(1, 0x40));
	cv_now = cv_boot;
	return gold_set_how(to, true);
}

/* SweetHID.cpp: a touch report came - the top step at once */
''')

patch(m, '''			if (gold_set_how(want, true) == 0) {
				ups += want > cd_cur;
''', '''			if (cv_gold_step(cd_cur, want) == 0) {
				ups += want > cd_cur;
''')
patch(m, '''				    "%u touch | top %u%% cap %u\\n", ns / 1000000, at[0] * 100 / all, at[1] * 100 / all, at[2] * 100 / all,
				    at[3] * 100 / all, at[4] * 100 / all, at[5] * 100 / all, ups, downs, boosts, top, (uint32_t)gold_cap);
''', '''				    "%u touch | top %u%% cap %u | %u mV\\n", ns / 1000000, at[0] * 100 / all, at[1] * 100 / all, at[2] * 100 / all,
				    at[3] * 100 / all, at[4] * 100 / all, at[5] * 100 / all, ups, downs, boosts, top, (uint32_t)gold_cap,
				    cv_on ? cv_now : cv_read(0, 0x40));
''')
patch(m, '''	cd_cur = pll_gold[1] & 0xffff;
	cd_running = true;
''', '''	cd_cur = pll_gold[1] & 0xffff;
	cv_start();                             /* the rail (xnu/src/mk_cpuvolt.py): at the boot value until a step down */
	cd_running = true;
''')

# lv:gold / lv_gold_set_l while the governor runs: it becomes the governor's range, so the rail stays right
patch(m, '''extern "C" int
lv_gold_set_l(uint32_t l)
{
	int r = gold_set(l);
''', '''static bool cd_pin(uint32_t l);         /* mk_cpuvolt.py: below, with the governor */

extern "C" int
lv_gold_set_l(uint32_t l)
{
	if (cd_pin(l)) {
		return 0;
	}
	int r = gold_set(l);
''')
patch(m, '''static void
cpu_dvfs_thread(__unused void *arg, __unused wait_result_t w)
{''', '''/* lv:gold while the governor runs: it owns the clock (and the rail) - its range becomes the step at or below l */
static bool
cd_pin(uint32_t l)
{
	uint32_t to = cd_step[0];

	if (!cd_running) {
		return false;
	}
	for (unsigned i = 0; i < CD_STEPS; i++) {
		if (cd_step[i] <= l) {
			to = cd_step[i];
		}
	}
	cd_min = cd_max = to;
	IOLog("LV GOLD: the governor is on: its range is now L %u (%u MHz)\\n", to, to * 192 / 10);
	return true;
}

static void
cpu_dvfs_thread(__unused void *arg, __unused wait_result_t w)
{''')
patch(m, '''		if (want > limit) {
			want = limit;
		}
		if (want != cd_cur) {''', '''		if (want < cd_min) {
			want = cd_min;                  /* (a range pinned from outside, cd_pin()) */
		}
		if (want > limit) {
			want = limit;
		}
		if (want != cd_cur) {''')
print('ok')
