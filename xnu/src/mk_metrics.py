"""lavender: a line of numbers every second, a CPU/clock report at start, lv:peek and lv:pmic (patch 1160).

More data for the fps / power work, all read only:

  LVM <ms>: cpu a b c d | run R | gold F MHz | t a b c d gpu G max M | gpu B% F MHz sub S rec R/F |
            mem free F wired W act A inact I comp C MB lvl L | bat V mV I mA
      cpu    busy share of each core in percent (processor tick counters)
      run    the scheduler's load average (1000 = as many runnable threads as cores)
      gold   the Gold cluster clock from its PLL (L x 19.2 MHz)
      t      TSENS: the four Gold cores (sensors 3-6 in the stock DT), the GPU (8), the hottest of all 14
      gpu    busy share from RBBM_PERFCTR_RBBM_0 (countable 6, as Linux a5xx_gpu_busy), core clock,
             submissions in the period, recoveries done / failed since boot
      mem    pages as MB (16K pages), memorystatus level
      bat    PM660 fuel gauge: battery voltage and current (+ = out of the battery)
  LVP <ms>: all N | name pct ...      CPU by process, percent of one core (lv_metrics_top names, 6)
  LVK khz a b c d                     each core's clock measured: PMU cycle counter against the
                                      19.2 MHz timer over 200 us (every lv_metrics_khz lines, 10)
  LVCPU ...                           once: cores, MIDR, measured clock, PLL / RCG registers
  LVPMIC ...                          once: PM660 / PM660L switching regulators S1-S6 (type, status,
                                      registers 0x40-0x47: the voltage setting) (lv_cpuinfo=0 skips both)

boot-args: lv_metrics=MS (period, 1000; 0 = off), lv_metrics_khz=N, lv_metrics_top=N, lv_cpuinfo=0/1.

USB commands: "lv:peek HEXADDR [N]" prints N (1..16) words of device memory at a physical address,
"lv:pmic HEXADDR [N]" N PMIC bytes (address = slave << 16 | register). For looking at a register
without a kernel build; a read the hardware refuses stops the phone, so one address at a time.

usage: python mk_metrics.py XNU_TREE
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


open(f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp', 'w', newline='\n').write(r'''/*
 * lavender: a line of numbers every second (xnu/src/mk_metrics.py). Read only.
 *   LVM  cores, load, clock, temperatures, GPU, memory, battery
 *   LVP  CPU by process
 *   LVK  each core's measured clock
 *   LVCPU / LVPMIC  once at start
 */
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>

#define LVM_CPUS            4
#define TSENS_TM_PA         0x010AE000ull
#define TSENS_SENSORS       14
#define PLL_GOLD_PA         0x17816000ull       /* +0 mode, +4 L (x 19.2 MHz), +0x2c status */
#define PLL_SILVER_PA       0x17916000ull
#define GOLD_RCG_PA         0x17811000ull       /* +0x50 cmd, +0x54 cfg (bits 10:8 source) */
#define APCS_COMMON_PA      0x179d1000ull       /* +0x12c cmd, +0x130 cfg: the OSM block's clock */
#define FG_VBATT            0x41A0u             /* PM660 fuel gauge (slave 0): VBATT, then IBATT, 16 bit each */

extern "C" {
void thread_set_thread_name(struct thread *th, const char *name);
vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
processor_t cpu_to_processor(int cpu);
int ml_get_max_cpu_number(void);
int lv_pmic_byte(int write, unsigned addr, uint8_t *val);       /* bsd/dev/sweet_usb.c */
void lv_metrics_start(void);

/* kernel symbols under names of our own: no clash with what a header may declare */
struct proc;
int lvm_cpu_number(void) __asm("_cpu_number");
unsigned int lvm_xcall(boolean_t self, void (*func)(void *), void *parm) __asm("_cpu_broadcast_xcall_simple");
void lvm_proc_iterate(unsigned int flags, int (*callout)(struct proc *, void *), void *arg,
    int (*filter)(struct proc *, void *), void *filterarg) __asm("_proc_iterate");
int lvm_proc_pid(struct proc *) __asm("_proc_pid");
task_t lvm_proc_task(struct proc *) __asm("_proc_task");
void lvm_proc_name(int pid, char *buf, int size) __asm("_proc_name");
uint64_t lvm_task_cpu_time(task_t) __asm("_get_task_cpu_time");
extern unsigned int lvm_free __asm("_vm_page_free_count");
extern unsigned int lvm_wired __asm("_vm_page_wire_count");
extern unsigned int lvm_active __asm("_vm_page_active_count");
extern unsigned int lvm_inactive __asm("_vm_page_inactive_count");
extern unsigned int lvm_spec __asm("_vm_page_speculative_count");
extern int32_t lvm_compressed __asm("_c_segment_pages_compressed");
extern uint32_t lvm_load __asm("_sched_load_average");
extern unsigned int lvm_level __asm("_memorystatus_level");
}

/* TopazAdreno.cpp */
extern "C" bool redwood_gpu_stats(uint64_t *busy, uint32_t *mhz, uint32_t *submits, uint32_t *recovered, uint32_t *failed);

static volatile uint32_t *tm, *pll_gold, *pll_silver, *gold_rcg, *apcs_common;
static uint32_t period_ms = 1000, khz_every = 10, top_n = 6;

/* ---- cores: busy share from the tick counters ---- */

static uint32_t last_busy[LVM_CPUS], last_all[LVM_CPUS];

static void
core_load(unsigned pct[LVM_CPUS])
{
	for (int c = 0; c < LVM_CPUS; c++) {
		pct[c] = 0;
		if (c > ml_get_max_cpu_number()) {
			continue;
		}
		processor_t p = cpu_to_processor(c);
		integer_t t[4] = { 0, 0, 0, 0 };
		mach_msg_type_number_t n = 4;
		host_t host = HOST_NULL;
		if (p == PROCESSOR_NULL || processor_info(p, PROCESSOR_CPU_LOAD_INFO, &host, (processor_info_t)t, &n) != KERN_SUCCESS) {
			continue;
		}
		uint32_t b = (uint32_t)t[0] + (uint32_t)t[1] + (uint32_t)t[3], a = b + (uint32_t)t[2];
		uint32_t db = b - last_busy[c], da = a - last_all[c];
		last_busy[c] = b;
		last_all[c] = a;
		pct[c] = da != 0 ? db * 100 / da : 0;
	}
}

/* ---- cores: the clock measured (PMU cycle counter against the system timer), on every core at once ---- */

static struct { uint32_t khz, midr; } core[LVM_CPUS];

static void
core_xcall(__unused void *arg)
{
	int c = lvm_cpu_number();
	uint64_t v, f, t0, t1, c0, c1;

	if (c < 0 || c >= LVM_CPUS) {
		return;
	}
	__asm__ volatile ("mrs %0, pmcr_el0" : "=r"(v));
	v |= 1u | (1u << 6);                            /* counters on, 64-bit cycle counter */
	__asm__ volatile ("msr pmcr_el0, %0" : : "r"(v));
	v = 1ull << 31;
	__asm__ volatile ("msr pmcntenset_el0, %0" : : "r"(v));
	__asm__ volatile ("isb");
	__asm__ volatile ("mrs %0, cntfrq_el0" : "=r"(f));
	__asm__ volatile ("mrs %0, cntvct_el0" : "=r"(t0));
	__asm__ volatile ("mrs %0, pmccntr_el0" : "=r"(c0));
	do {
		__asm__ volatile ("mrs %0, cntvct_el0" : "=r"(t1));
	} while (t1 - t0 < f / 5000);                   /* 200 us */
	__asm__ volatile ("mrs %0, pmccntr_el0" : "=r"(c1));
	core[c].khz = (uint32_t)((c1 - c0) * (f / 1000) / (t1 - t0));
	__asm__ volatile ("mrs %0, midr_el1" : "=r"(v));
	core[c].midr = (uint32_t)v;
}

static void
core_measure(void)
{
	for (int c = 0; c < LVM_CPUS; c++) {
		core[c].khz = 0;
	}
	lvm_xcall(TRUE, core_xcall, NULL);
}

/* ---- CPU by process (as the sampler's SMC line, with a table of its own) ---- */

static struct { int pid; uint64_t last; } proc_cpu[512];
static struct { char name[20]; uint64_t d; } proc_top[8];
static uint64_t proc_sum;

static int
proc_one(struct proc *p, __unused void *arg)
{
	int pid = lvm_proc_pid(p);
	task_t task = lvm_proc_task(p);
	uint64_t t = 0, d = 0;
	unsigned slot = (unsigned)pid % 512, tries = 0;

	if (task == TASK_NULL) {
		return 0;
	}
	absolutetime_to_nanoseconds(lvm_task_cpu_time(task), &t);
	while (tries++ < 512 && proc_cpu[slot].last != 0 && proc_cpu[slot].pid != pid) {
		slot = (slot + 1) % 512;
	}
	if (proc_cpu[slot].pid == pid && proc_cpu[slot].last != 0 && t >= proc_cpu[slot].last) {
		d = t - proc_cpu[slot].last;
	}
	proc_cpu[slot].pid = pid;
	proc_cpu[slot].last = t ? t : 1;
	proc_sum += d;
	for (int i = 0; i < 8; i++) {
		if (d > proc_top[i].d) {
			for (int j = 7; j > i; j--) {
				proc_top[j] = proc_top[j - 1];
			}
			proc_top[i].d = d;
			lvm_proc_name(pid, proc_top[i].name, sizeof(proc_top[i].name));
			break;
		}
	}
	return 0;
}

static void
proc_line(uint64_t ns)
{
	char line[256];
	int n;

	bzero(proc_top, sizeof(proc_top));
	proc_sum = 0;
	lvm_proc_iterate(1 /* PROC_ALLPROCLIST */, proc_one, NULL, NULL, NULL);
	if (ns == 0) {
		return;
	}
	n = snprintf(line, sizeof(line), "LVP %llu ms: all %llu |", ns / 1000000, proc_sum * 100 / ns);
	for (unsigned i = 0; i < top_n && i < 8 && proc_top[i].d != 0 && n < (int)sizeof(line) - 32; i++) {
		n += snprintf(line + n, sizeof(line) - n, " %s %llu", proc_top[i].name, proc_top[i].d * 100 / ns);
	}
	IOLog("%s\n", line);
}

/* ---- once: what the cores and their supplies are ---- */

static void
pmic_dump(unsigned sid, const char *name)
{
	for (unsigned base = 0x1400; base <= 0x2300; base += 0x300) {
		uint8_t v[11] = { 0 };
		static const uint8_t reg[11] = { 0x04, 0x05, 0x08, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47 };
		int bad = 0;
		for (unsigned i = 0; i < 11; i++) {
			if (lv_pmic_byte(0, (sid << 16) | (base + reg[i]), &v[i]) != 0) {
				bad++;
			}
		}
		if (bad == 11) {
			continue;                               /* no such peripheral for us */
		}
		IOLog("LVPMIC %s S%u (%#x): type %02x subtype %02x status %02x | 40: %02x %02x %02x %02x %02x %02x %02x %02x (%d unread)\n",
		    name, (base - 0x1400) / 0x300 + 1, base, v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], bad);
	}
}

static void
cpu_report(void)
{
	if (khz_every != 0) {                           /* (lv_metrics_khz=0: no PMU access at all) */
		core_measure();
	}
	IOLog("LVCPU: %d cores | khz %u %u %u %u | midr %08x %08x %08x %08x\n", ml_get_max_cpu_number() + 1,
	    core[0].khz, core[1].khz, core[2].khz, core[3].khz, core[0].midr, core[1].midr, core[2].midr, core[3].midr);
	IOLog("LVCPU: gold pll mode %#x L %u status %#x, rcg cmd %#x cfg %#x | silver pll mode %#x L %u status %#x | osm clk cmd %#x cfg %#x\n",
	    pll_gold[0], pll_gold[1] & 0xffff, pll_gold[0x2c / 4], gold_rcg[0x50 / 4], gold_rcg[0x54 / 4],
	    pll_silver[0], pll_silver[1] & 0xffff, pll_silver[0x2c / 4], apcs_common[0x12c / 4], apcs_common[0x130 / 4]);
	pmic_dump(1, "pm660");
	pmic_dump(3, "pm660l");
}

/* ---- the line ---- */

static int
tsens(unsigned i, bool *valid)
{
	uint32_t v = tm[(0xA0 + 4 * i) / 4];
	int t = (int)(v & 0xfff);
	*valid = (v & (1u << 21)) != 0;
	return ((t & 0x800) ? t - 0x1000 : t) / 10;     /* signed 12 bit, tenths of a degree */
}

static void
metrics_thread(__unused void *arg, __unused wait_result_t w)
{
	uint64_t before = 0, gpu_before = 0;
	uint32_t sub_before = 0, lines = 0, info = 1;
	bool gpu_had = false;

	IOSleep(2000);
	(void)PE_parse_boot_argn("lv_cpuinfo", &info, sizeof(info));
	if (info != 0) {
		cpu_report();
	}
	for (;;) {
		uint64_t now = mach_absolute_time(), ns = 0;
		unsigned pct[LVM_CPUS];
		char line[420];
		int n, max = -1000;
		bool ok;

		absolutetime_to_nanoseconds(now - before, &ns);
		if (before == 0) {
			ns = 0;
		}
		before = now;
		core_load(pct);
		n = snprintf(line, sizeof(line), "LVM %llu ms: cpu %u %u %u %u | run %u | gold %u MHz | t", ns / 1000000,
		    pct[0], pct[1], pct[2], pct[3], lvm_load, (pll_gold[1] & 0xffff) * 192 / 10);

		for (unsigned i = 0; i < TSENS_SENSORS; i++) {
			int t = tsens(i, &ok);
			if (ok && t > max) {
				max = t;
			}
		}
		n += snprintf(line + n, sizeof(line) - n, " %d %d %d %d gpu %d max %d", tsens(3, &ok), tsens(4, &ok), tsens(5, &ok),
		    tsens(6, &ok), tsens(8, &ok), max);

		uint64_t busy = 0;
		uint32_t mhz = 0, sub = 0, rec = 0, fail = 0;
		if (redwood_gpu_stats(&busy, &mhz, &sub, &rec, &fail) && mhz != 0) {
			uint64_t share = 0;
			if (gpu_had && ns != 0 && busy >= gpu_before) {
				share = (busy - gpu_before) * 100000 / ((uint64_t)mhz * ns);    /* cycles / (MHz x ns / 1000) in percent */
			}
			n += snprintf(line + n, sizeof(line) - n, " | gpu %llu%% %u MHz sub %u rec %u/%u", share > 100 ? 100 : share, mhz,
			    gpu_had ? sub - sub_before : 0, rec, fail);
			gpu_before = busy;
			sub_before = sub;
			gpu_had = true;
		} else {
			n += snprintf(line + n, sizeof(line) - n, " | gpu -");
			gpu_had = false;
		}

		n += snprintf(line + n, sizeof(line) - n, " | mem free %u wired %u act %u inact %u comp %d MB lvl %u", lvm_free / 64, lvm_wired / 64,
		    lvm_active / 64, (lvm_inactive + lvm_spec) / 64, lvm_compressed / 64, lvm_level);

		uint8_t b[4] = { 0, 0, 0, 0 };
		int bad = 0;
		for (unsigned i = 0; i < 4; i++) {
			bad |= lv_pmic_byte(0, FG_VBATT + i, &b[i]);
		}
		if (bad == 0) {
			int mv = (int)(int16_t)(b[0] | (b[1] << 8)) * 12207 / 100000;       /* 122.07 uV a step */
			int ma = (int)((int64_t)(int16_t)(b[2] | (b[3] << 8)) * 488281 / 1000000);     /* 488.281 uA a step */
			n += snprintf(line + n, sizeof(line) - n, " | bat %d mV %d mA", mv, ma);
		} else {
			n += snprintf(line + n, sizeof(line) - n, " | bat -");
		}
		if (ns != 0) {
			IOLog("%s\n", line);
		}
		if (top_n != 0) {
			proc_line(ns);
		}
		if (khz_every != 0 && lines % khz_every == 0) {
			core_measure();
			IOLog("LVK khz %u %u %u %u\n", core[0].khz, core[1].khz, core[2].khz, core[3].khz);
		}
		lines++;
		IOSleep(period_ms);
	}
}

extern "C" void
lv_metrics_start(void)
{
	static SInt32 started;
	thread_t t;

	if (!OSCompareAndSwap(0, 1, (UInt32 *)&started)) {
		return;
	}
	(void)PE_parse_boot_argn("lv_metrics", &period_ms, sizeof(period_ms));
	(void)PE_parse_boot_argn("lv_metrics_khz", &khz_every, sizeof(khz_every));
	(void)PE_parse_boot_argn("lv_metrics_top", &top_n, sizeof(top_n));
	if (period_ms == 0) {
		return;
	}
	if (period_ms < 100) {
		period_ms = 100;
	}
	tm = (volatile uint32_t *)ml_io_map(TSENS_TM_PA, 0x1000);
	pll_gold = (volatile uint32_t *)ml_io_map(PLL_GOLD_PA, 0x1000);
	pll_silver = (volatile uint32_t *)ml_io_map(PLL_SILVER_PA, 0x1000);
	gold_rcg = (volatile uint32_t *)ml_io_map(GOLD_RCG_PA, 0x1000);
	apcs_common = (volatile uint32_t *)ml_io_map(APCS_COMMON_PA, 0x1000);
	if (tm == NULL || pll_gold == NULL || pll_silver == NULL || gold_rcg == NULL || apcs_common == NULL) {
		IOLog("LVM: map failed\n");
		return;
	}
	if (kernel_thread_start(metrics_thread, NULL, &t) == KERN_SUCCESS) {
		thread_set_thread_name(t, "lv_metrics_thread");
		thread_deallocate(t);
	}
}
''')

patch(f'{tree}/iokit/conf/files.arm64', '''iokit/Kernel/arm/LavenderThermal.cpp                             optional iokitcpp
''', '''iokit/Kernel/arm/LavenderThermal.cpp                             optional iokitcpp
iokit/Kernel/arm/LavenderMetrics.cpp                             optional iokitcpp
''')

# the GPU's numbers for the line, and a count of the recoveries
ad = f'{tree}/iokit/Kernel/arm/TopazAdreno.cpp'
patch(ad, '''	ok = cp_start();
	if (ok && mem.va != NULL) {''', '''	ok = cp_start();
	lv_gpu_recovered += ok ? 1 : 0;                 /* lavender: counted for the LVM line (mk_metrics.py) */
	lv_gpu_recover_failed += ok ? 0 : 1;
	if (ok && mem.va != NULL) {''')
patch(ad, '''bool
redwood_gpu_recover(void)
{''', '''static uint32_t lv_gpu_recovered, lv_gpu_recover_failed;

/*
 * lavender (mk_metrics.py): busy cycles (RBBM_PERFCTR_RBBM_0: countable 6 = RBBM_STATUS masked, set in
 * a5_hw_init as Linux does for devfreq), the core clock, submissions and recoveries so far.
 */
bool
redwood_gpu_stats(uint64_t *busy, uint32_t *mhz, uint32_t *submits, uint32_t *recovered, uint32_t *failed)
{
	if (!ready) {
		return false;
	}
	uint32_t hi = gpu_rd(0x3b1), lo = gpu_rd(0x3b0);
	if (gpu_rd(0x3b1) != hi) {
		hi = gpu_rd(0x3b1);
		lo = gpu_rd(0x3b0);
	}
	*busy = ((uint64_t)hi << 32) | lo;
	*mhz = core_mhz;
	*submits = seqno;
	*recovered = lv_gpu_recovered;
	*failed = lv_gpu_recover_failed;
	return true;
}

bool
redwood_gpu_recover(void)
{''')
patch(ad, '''bool redwood_gpu_recover(void);
''', '''bool redwood_gpu_recover(void);
bool redwood_gpu_stats(uint64_t *busy, uint32_t *mhz, uint32_t *submits, uint32_t *recovered, uint32_t *failed);
''')
patch(ad, '''	ready = true;
''', '''	ready = true;
	lv_metrics_start();                             /* LavenderMetrics.cpp (lv_metrics=0 off) */
''')
patch(ad, '''extern "C" void lavender_a5xx_hw_init(void);
''', '''extern "C" void lavender_a5xx_hw_init(void);
extern "C" void lv_metrics_start(void);
''')

# the same start where the temperature log starts (a boot without the GPU)
tmod = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
patch(tmod, '''extern "C" void lv_thermal_start(void);
''', '''extern "C" void lv_thermal_start(void);
extern "C" void lv_metrics_start(void);
''')
patch(tmod, '''			lv_thermal_start();                     /* LavenderThermal.cpp (lv_temp=0 off) */
''', '''			lv_thermal_start();                     /* LavenderThermal.cpp (lv_temp=0 off) */
			lv_metrics_start();                     /* LavenderMetrics.cpp (lv_metrics=0 off) */
''')

# lv:peek / lv:pmic
usb = f'{tree}/bsd/dev/sweet_usb.c'
patch(usb, '''static void
ud_rx_done(void)
{''', '''/* lavender: lv:peek HEXADDR [N], lv:pmic HEXADDR [N] (xnu/src/mk_metrics.py) */
static const char *
ud_hex(const char *s, uint64_t *v)
{
	uint64_t x = 0;
	int n = 0;

	while (*s == ' ') {
		s++;
	}
	if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
		s += 2;
	}
	for (;; s++, n++) {
		int d;
		if (*s >= '0' && *s <= '9') {
			d = *s - '0';
		} else if (*s >= 'a' && *s <= 'f') {
			d = *s - 'a' + 10;
		} else if (*s >= 'A' && *s <= 'F') {
			d = *s - 'A' + 10;
		} else {
			break;
		}
		x = (x << 4) | (uint64_t)d;
	}
	*v = x;
	return n != 0 ? s : NULL;
}

static void
ud_peek(const char *arg, bool pmic)
{
	static uint64_t page_pa;
	static vm_offset_t page_va;
	uint64_t addr = 0;
	int count = 1, n = 0;
	char line[200];
	const char *rest = ud_hex(arg, &addr);

	if (rest == NULL) {
		printf("LV USB: bad %s\\n", pmic ? "lv:pmic" : "lv:peek");
		return;
	}
	if (ud_numbers(rest, &count, 1) != 1 || count < 1) {
		count = 1;
	}
	if (count > 16) {
		count = 16;
	}
	line[0] = 0;
	if (pmic) {
		for (int i = 0; i < count; i++) {
			uint8_t b = 0;
			int r = lv_pmic_byte(0, (unsigned)addr + (unsigned)i, &b);
			n += r == 0 ? snprintf(line + n, sizeof(line) - n, " %02x", b) : snprintf(line + n, sizeof(line) - n, " -(%d)", r);
		}
		printf("LV PMIC %#llx:%s\\n", addr, line);
		return;
	}
	addr &= ~3ull;
	if (page_va == 0 || page_pa != (addr & ~0xfffull)) {
		page_pa = addr & ~0xfffull;
		page_va = ml_io_map((vm_offset_t)page_pa, 0x1000);
	}
	if (page_va == 0) {
		printf("LV PEEK %#llx: map failed\\n", addr);
		return;
	}
	for (int i = 0; i < count && (addr & 0xfff) + 4 * (uint64_t)i < 0x1000; i++) {
		n += snprintf(line + n, sizeof(line) - n, " %08x", *(volatile uint32_t *)(page_va + (addr & 0xfff) + 4 * (unsigned)i));
	}
	printf("LV PEEK %#llx:%s\\n", addr, line);
}

static void
ud_rx_done(void)
{''')
patch(usb, '''	} else if (strcmp(cmd, "lv:power") == 0) {''', '''	} else if (strncmp(cmd, "lv:peek ", 8) == 0) {
		ud_peek(cmd + 8, false);
	} else if (strncmp(cmd, "lv:pmic ", 8) == 0) {
		ud_peek(cmd + 8, true);
	} else if (strcmp(cmd, "lv:power") == 0) {''')
print('ok')
