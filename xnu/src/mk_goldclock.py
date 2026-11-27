"""lavender: the Gold cluster clock can be set while iOS runs (patch 1161): lv:gold L, lv_gold_l=L.

The shim leaves the four Gold cores at L=115 (2208 MHz, the top of speed bin 1) for good. To see what
the clock costs and gives (fps, heat, battery current: the LVM line of patch 1160), it can now be
changed at run time, the way the shim does it: the cluster's RCG parks on GPLL0, the PLL relocks at
the new L (rate = L x 19.2 MHz), the RCG goes back to the PLL. The voltage is not touched (it stays
where the boot loader left it, which already carries 2208 MHz), so only going down from 115 is new.

  boot-arg lv_gold_l=L     set once when the metrics start (absent or 0 = leave the shim's clock)
  USB      lv:gold L       set now; the answer is "LV GOLD: L .. -> .. , measured .. kHz"
  L from 16 (307 MHz) to 115 (2208 MHz); the stock table uses 58, 73, 91, 102, 112, 115.

usage: python mk_goldclock.py XNU_TREE   (after mk_metrics.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


m = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'
patch(m, '''void lv_metrics_start(void);
''', '''void lv_metrics_start(void);
int lv_gold_set_l(uint32_t l);
''')
patch(m, '''/* ---- CPU by process (as the sampler's SMC line, with a table of its own) ---- */
''', r'''/* ---- the Gold clock set at run time (xnu/src/mk_goldclock.py) ---- */

#define GOLD_L_MIN          16u                 /* 307 MHz */
#define GOLD_L_MAX          115u                /* 2208 MHz: the top of speed bin 1 (stock DT) */
#define GOLD_SRC_PLL        3u
#define GOLD_SRC_GPLL0      4u

static void
gold_source(uint32_t src)
{
	gold_rcg[0x54 / 4] = (gold_rcg[0x54 / 4] & ~0x71fu) | (src << 8) | 1u;
	__asm__ volatile ("dsb sy" ::: "memory");
	gold_rcg[0x50 / 4] = 3;                         /* update, root on */
	__asm__ volatile ("dsb sy" ::: "memory");
	for (int n = 0; (gold_rcg[0x50 / 4] & 1) && n < 100000; n++) {
	}
}

/* 0 = set; -1 = bad L or not mapped; -2 = the PLL did not lock (the cores stay on GPLL0, 600 MHz) */
extern "C" int
lv_gold_set_l(uint32_t l)
{
	static IOLock *lock;
	uint32_t was;
	int r = 0;

	if (pll_gold == NULL || gold_rcg == NULL || l < GOLD_L_MIN || l > GOLD_L_MAX) {
		return -1;
	}
	if (lock == NULL) {
		IOLock *made = IOLockAlloc();
		if (!OSCompareAndSwapPtr(NULL, made, (void * volatile *)&lock)) {
			IOLockFree(made);
		}
	}
	IOLockLock(lock);
	was = pll_gold[1] & 0xffff;
	gold_source(GOLD_SRC_GPLL0);
	pll_gold[0] = 0;
	__asm__ volatile ("dsb sy" ::: "memory");
	pll_gold[1] = l;
	__asm__ volatile ("dsb sy" ::: "memory");
	pll_gold[0] = 2;
	__asm__ volatile ("dsb sy" ::: "memory");
	IODelay(1000);
	pll_gold[0] = 6;
	__asm__ volatile ("dsb sy" ::: "memory");
	IODelay(1000);
	pll_gold[0] = 7;
	__asm__ volatile ("dsb sy" ::: "memory");
	for (int n = 0; !(pll_gold[0x2c / 4] & (1u << 16)) && n < 100000; n++) {
	}
	if (pll_gold[0x2c / 4] & (1u << 16)) {
		gold_source(GOLD_SRC_PLL);
	} else {
		r = -2;
	}
	IOLockUnlock(lock);
	core_measure();
	IOLog("LV GOLD: L %u -> %u (%u MHz): %s, measured %u %u %u %u kHz\n", was, l, l * 192 / 10,
	    r == 0 ? "set" : "PLL DID NOT LOCK, cores on GPLL0", core[0].khz, core[1].khz, core[2].khz, core[3].khz);
	return r;
}

/* ---- CPU by process (as the sampler's SMC line, with a table of its own) ---- */
''')
patch(m, '''	if (info != 0) {
		cpu_report();
	}
''', '''	if (info != 0) {
		cpu_report();
	}
	uint32_t gold_l = 0;
	if (PE_parse_boot_argn("lv_gold_l", &gold_l, sizeof(gold_l)) && gold_l != 0) {
		lv_gold_set_l(gold_l);                  /* (xnu/src/mk_goldclock.py) */
	}
''')

usb = f'{tree}/bsd/dev/sweet_usb.c'
patch(usb, '''	} else if (strncmp(cmd, "lv:pmic ", 8) == 0) {
		ud_peek(cmd + 8, true);
''', '''	} else if (strncmp(cmd, "lv:pmic ", 8) == 0) {
		ud_peek(cmd + 8, true);
	} else if (strncmp(cmd, "lv:gold ", 8) == 0) {
		int l = 0;
		if (ud_numbers(cmd + 8, &l, 1) != 1 || lv_gold_set_l((uint32_t)l) == -1) {
			printf("LV USB: bad lv:gold (L 16..115)\\n");
		}
''')
patch(usb, '''/* lavender: lv:peek HEXADDR [N], lv:pmic HEXADDR [N] (xnu/src/mk_metrics.py) */
''', '''extern int lv_gold_set_l(uint32_t l);          /* LavenderMetrics.cpp (xnu/src/mk_goldclock.py) */

/* lavender: lv:peek HEXADDR [N], lv:pmic HEXADDR [N] (xnu/src/mk_metrics.py) */
''')
print('ok')
