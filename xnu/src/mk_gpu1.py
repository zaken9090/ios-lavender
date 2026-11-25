"""lavender GPU step 1-2: power the Adreno 512 up and see that it answers (boot-arg lv_gpu=1).

Runs in the lavender_perf thread (TopazRpm.cpp, patch 1008). Sequence after mainline
gcc-sdm660.c / gpucc-sdm660.c (GPUCC at 0x5065000) and gdsc.c:
  GCC: gpu_cfg_ahb 0x71004, gpu_bimc_gfx 0x71010, bimc_gfx 0x7106c (bit 0), gpu_gpll0 /
       gpu_gpll0_div 0x5200c bits 4 / 3
  GPUCC: cxo 0x1020; CX GDSC 0x1004 (bit 0 SW_COLLAPSE, bit 31 PWR_ON); GX: BCR 0x1090 pulse,
       GDSC 0x1094, clamp_io_ctrl 0x130 bit 0 off (bit 4 = AON reset pulse); gfx3d RCG 0x1070
       (CFG 0x1074: GPLL0 source 5, divider 2 -> 300 MHz), branch 0x1098; rbbmtimer 0x10d0
  GPU (0x5000000): RBBM_STATUS 0x4f5, always-on counter 0x4d2 (after RBBM_PERFCTR_CNTL 0x464 = 1),
       CP_SCRATCH 0xb78 write/read back (register offsets are in 32-bit words).
Logs every register before and after, nothing else is touched. A hang here = the GX rail is
off (it is a CPR regulator, not voted yet).

usage: python mk_gpu1.py XNU_TREE
"""
import sys

tree = sys.argv[1]
p = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
s = open(p, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:60], s.count(old))
    s = s.replace(old, new)


PROBE = r'''
/* lavender GPU step 1-2 (lv_gpu=1): power up, read back. See xnu/src/mk_gpu1.py. */
static volatile uint32_t *lv_gcc, *lv_gpucc, *lv_gpu;

static uint32_t lv_r(volatile uint32_t *b, uint32_t off) { return b[off / 4]; }
static void lv_w(volatile uint32_t *b, uint32_t off, uint32_t v) { __asm__ volatile ("dsb sy" ::: "memory"); b[off / 4] = v; __asm__ volatile ("dsb sy" ::: "memory"); }

/* branch clock: bit 0 enable, bit 31 CLK_OFF */
static bool
lv_branch(volatile uint32_t *b, uint32_t off, const char *name)
{
	lv_w(b, off, lv_r(b, off) | 1);
	for (int i = 0; i < 200; i++) {
		if (!(lv_r(b, off) & 0x80000000u)) {
			return true;
		}
		IODelay(10);
	}
	LOG("LVGPU %s: still off (%#x)", name, lv_r(b, off));
	return false;
}

/* GDSC: clear SW_COLLAPSE, wait for PWR_ON */
static bool
lv_gdsc_on(uint32_t off, const char *name)
{
	uint32_t before = lv_r(lv_gpucc, off);
	lv_w(lv_gpucc, off, before & ~1u);
	for (int i = 0; i < 1000; i++) {
		if (lv_r(lv_gpucc, off) & 0x80000000u) {
			LOG("LVGPU %s GDSC on (%#x -> %#x)", name, before, lv_r(lv_gpucc, off));
			return true;
		}
		IODelay(10);
	}
	LOG("LVGPU %s GDSC NOT on (%#x -> %#x)", name, before, lv_r(lv_gpucc, off));
	return false;
}

static void
lavender_gpu_probe(void)
{
	lv_gcc = (volatile uint32_t *)ml_io_map(0x00100000, 0x80000);
	lv_gpucc = (volatile uint32_t *)ml_io_map(0x05065000, 0x2000);
	lv_gpu = (volatile uint32_t *)ml_io_map(0x05000000, 0x40000);
	if (!lv_gcc || !lv_gpucc || !lv_gpu) {
		LOG("LVGPU map failed");
		return;
	}
	LOG("LVGPU before: gcc ahb %#x bimc_gfx %#x %#x gpll0 %#x | cx %#x gx %#x clamp %#x gfx3d cmd %#x cfg %#x cbcr %#x",
	    lv_r(lv_gcc, 0x71004), lv_r(lv_gcc, 0x71010), lv_r(lv_gcc, 0x7106c), lv_r(lv_gcc, 0x5200c),
	    lv_r(lv_gpucc, 0x1004), lv_r(lv_gpucc, 0x1094), lv_r(lv_gpucc, 0x130),
	    lv_r(lv_gpucc, 0x1070), lv_r(lv_gpucc, 0x1074), lv_r(lv_gpucc, 0x1098));

	lv_w(lv_gcc, 0x5200c, lv_r(lv_gcc, 0x5200c) | (1u << 4) | (1u << 3));   /* GPLL0 to the GPU */
	bool ok = lv_branch(lv_gcc, 0x71004, "gpu_cfg_ahb") & lv_branch(lv_gcc, 0x71010, "gpu_bimc_gfx") &
	    lv_branch(lv_gcc, 0x7106c, "bimc_gfx");
	ok &= lv_branch(lv_gpucc, 0x1020, "gpucc_cxo");
	ok &= lv_gdsc_on(0x1004, "CX");

	/* gfx3d: GPLL0 (source 5) / 2 = 300 MHz */
	lv_w(lv_gpucc, 0x1074, (5u << 8) | 3u);
	lv_w(lv_gpucc, 0x1070, lv_r(lv_gpucc, 0x1070) | 1u);
	for (int i = 0; i < 200 && (lv_r(lv_gpucc, 0x1070) & 1u); i++) {
		IODelay(10);
	}
	LOG("LVGPU gfx3d rcg cmd %#x cfg %#x", lv_r(lv_gpucc, 0x1070), lv_r(lv_gpucc, 0x1074));

	/* GX: reset pulse, power, AON reset pulse, unclamp, then its clock */
	lv_w(lv_gpucc, 0x1090, 1);
	IODelay(10);
	lv_w(lv_gpucc, 0x1090, 0);
	ok &= lv_gdsc_on(0x1094, "GX");
	lv_w(lv_gpucc, 0x130, lv_r(lv_gpucc, 0x130) | (1u << 4));
	IODelay(1);
	lv_w(lv_gpucc, 0x130, lv_r(lv_gpucc, 0x130) & ~(1u << 4));
	lv_w(lv_gpucc, 0x130, lv_r(lv_gpucc, 0x130) & ~1u);
	ok &= lv_branch(lv_gpucc, 0x1098, "gfx3d");
	(void)lv_branch(lv_gpucc, 0x10d0, "rbbmtimer");
	LOG("LVGPU power %s: cx %#x gx %#x clamp %#x gfx3d %#x", ok ? "ok" : "INCOMPLETE",
	    lv_r(lv_gpucc, 0x1004), lv_r(lv_gpucc, 0x1094), lv_r(lv_gpucc, 0x130), lv_r(lv_gpucc, 0x1098));
	if (!ok) {
		return;
	}

	lv_w(lv_gpu, 0x464 * 4, 1);                     /* RBBM_PERFCTR_CNTL: counters on */
	uint32_t t0 = lv_r(lv_gpu, 0x4d2 * 4);
	IODelay(1000);
	uint32_t t1 = lv_r(lv_gpu, 0x4d2 * 4);
	lv_w(lv_gpu, 0xb78 * 4, 0x1a5a5a5a);            /* CP_SCRATCH_REG0 */
	LOG("LVGPU regs: RBBM_STATUS %#x STATUS3 %#x alwayson %u -> %u (+%u in 1 ms) scratch %#x HW_FAULT %#x",
	    lv_r(lv_gpu, 0x4f5 * 4), lv_r(lv_gpu, 0x530 * 4), t0, t1, t1 - t0, lv_r(lv_gpu, 0xb78 * 4),
	    lv_r(lv_gpu, 0xb1a * 4));
}
'''

sub('''static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''', PROBE.lstrip('\n') + '''
static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''')
sub('''		lavender_memcpy_speed("after");
	}
}''', '''		lavender_memcpy_speed("after");
	}
	uint32_t gpu = 0;
	PE_parse_boot_argn("lv_gpu", &gpu, sizeof(gpu));
	if (gpu) {
		lavender_gpu_probe();
	}
}''')
open(p, 'w', newline='\n').write(s)
print('ok')
