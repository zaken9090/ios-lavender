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
Logs every register before and after, nothing else is touched. GX took over 100 ms to report PWR_ON
with the gfx3d root off (CMD bit 31 ROOT_OFF, seen 2026-11-25): the DT asks for force-enable-root-clk,
so CMD bit 1 ROOT_EN is set before GX, and the wait is up to 1 s. A hang here = the GX rail is
off (it is a CPR regulator, not voted yet).

Stages (lv_gpu=N, to find what disturbs the panel's touch, seen 2026-11-25: with the full probe the
NT36672A reports no fingers): 1 map + log, 2 GCC branches + gpucc cxo, 3 + CX GDSC, 4 + gfx3d RCG,
5 + GX reset and GX GDSC, 6 + clamp / AON reset / gfx3d and rbbmtimer branches, 7 + GPU register reads.
Stages 1-4 leave touch working; the full probe stops it (likely the display pipeline, touch is the same chip).

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
	for (int i = 0; i < 100000; i++) {
		if (lv_r(lv_gpucc, off) & 0x80000000u) {
			LOG("LVGPU %s GDSC on after %d us (%#x -> %#x)", name, i * 10, before, lv_r(lv_gpucc, off));
			return true;
		}
		IODelay(10);
	}
	LOG("LVGPU %s GDSC NOT on (%#x -> %#x)", name, before, lv_r(lv_gpucc, off));
	return false;
}

static void
lavender_gpu_probe(uint32_t level)
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

	if (level < 2) {
		return;
	}
	lv_w(lv_gcc, 0x5200c, lv_r(lv_gcc, 0x5200c) | (1u << 4) | (1u << 3));   /* GPLL0 to the GPU */
	bool ok = lv_branch(lv_gcc, 0x71004, "gpu_cfg_ahb") & lv_branch(lv_gcc, 0x71010, "gpu_bimc_gfx") &
	    lv_branch(lv_gcc, 0x7106c, "bimc_gfx");
	ok &= lv_branch(lv_gpucc, 0x1020, "gpucc_cxo");
	if (level < 3) {
		LOG("LVGPU stage 2 (GCC branches) done");
		return;
	}
	ok &= lv_gdsc_on(0x1004, "CX");
	if (level < 4) {
		return;
	}

	/* gfx3d: GPLL0 (source 5) / 2 = 300 MHz */
	lv_w(lv_gpucc, 0x1074, (5u << 8) | 3u);
	lv_w(lv_gpucc, 0x1070, lv_r(lv_gpucc, 0x1070) | 1u);
	for (int i = 0; i < 200 && (lv_r(lv_gpucc, 0x1070) & 1u); i++) {
		IODelay(10);
	}
	/* DT force-enable-root-clk: hold the root on (CMD bit 1 ROOT_EN) until GX is up; bit 31 = ROOT_OFF */
	lv_w(lv_gpucc, 0x1070, lv_r(lv_gpucc, 0x1070) | 2u);
	for (int i = 0; i < 200 && (lv_r(lv_gpucc, 0x1070) & 0x80000000u); i++) {
		IODelay(10);
	}
	LOG("LVGPU gfx3d rcg cmd %#x cfg %#x", lv_r(lv_gpucc, 0x1070), lv_r(lv_gpucc, 0x1074));

	if (level < 5) {
		return;
	}
	/*
	 * The GX rail: DT gfx_corner (cpr4 mmss-ldo) has a stub vdd; the real rail is PM660L S3, voted
	 * by level over RPM (system-supply pm660l_s3_level: resource "smpb" 3, keys "swen" / "vlvl").
	 * Levels per gfx corner 0x40 0x40 0x80 0xc0 0x100 0x140 0x180; 300 MHz = corner 3 = 0x80 (SVS).
	 * Without it the GX GDSC never reports PWR_ON and unclamping it stops the display (and touch).
	 */
	uint32_t lvl = 0x80;
	PE_parse_boot_argn("lv_gfx_lvl", &lvl, sizeof(lvl));
	if (lvl) {
		bool en = topaz_rpm_write(0, 0x62706d73u /* smpb */, 3, 0x6e657773u /* swen */, 1);
		bool lv = topaz_rpm_write(0, 0x62706d73u, 3, 0x6c766c76u /* vlvl */, lvl);
		LOG("LVGPU GX rail smpb3 swen %s vlvl %#x %s", en ? "acked" : "FAILED", lvl, lv ? "acked" : "FAILED");
		IODelay(2000);
	}

	/* GFX LDO block (DT msm_gfx_ldo 0x506e000, BHS mode: all corners have allow-ldo-mode 0): read only */
	{
		volatile uint32_t *ldo = (volatile uint32_t *)ml_io_map(0x0506e000, 0x1000);
		if (ldo) {
			LOG("LVGPU gfx ldo: %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x",
			    ldo[0], ldo[1], ldo[2], ldo[3], ldo[4], ldo[5], ldo[6], ldo[7], ldo[8], ldo[9], ldo[10], ldo[11], ldo[12]);
		}
	}

	/* GX, in msm gdsc.c order: BCR pulse (sw-reset), AON reset pulse (reset-aon-logic, clamp
	 * register bit 4), clear SW_COLLAPSE and wait for PWR_ON; then unclamp (bit 0), then clocks. */
	lv_w(lv_gpucc, 0x1090, 1);
	IODelay(10);
	lv_w(lv_gpucc, 0x1090, 0);
	lv_w(lv_gpucc, 0x130, lv_r(lv_gpucc, 0x130) | (1u << 4));
	IODelay(1);
	lv_w(lv_gpucc, 0x130, lv_r(lv_gpucc, 0x130) & ~(1u << 4));
	ok &= lv_gdsc_on(0x1094, "GX");
	if (level < 6) {
		LOG("LVGPU stage 5 (GX reset + AON reset + GDSC) done: gx %#x clamp %#x", lv_r(lv_gpucc, 0x1094), lv_r(lv_gpucc, 0x130));
		return;
	}
	IODelay(1);
	lv_w(lv_gpucc, 0x130, lv_r(lv_gpucc, 0x130) & ~1u);
	ok &= lv_branch(lv_gpucc, 0x1098, "gfx3d");
	(void)lv_branch(lv_gpucc, 0x10d0, "rbbmtimer");
	LOG("LVGPU power %s: cx %#x gx %#x clamp %#x gfx3d %#x", ok ? "ok" : "INCOMPLETE",
	    lv_r(lv_gpucc, 0x1004), lv_r(lv_gpucc, 0x1094), lv_r(lv_gpucc, 0x130), lv_r(lv_gpucc, 0x1098));
	if (!ok || level < 7) {
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
		lavender_gpu_probe(gpu);
	}
}''')
open(p, 'w', newline='\n').write(s)
print('ok')
