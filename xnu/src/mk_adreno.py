"""lavender GPU step 7: the base's RedwoodGPU driver (TopazAdreno.cpp) on the Adreno 512.

Boot-arg gpu=1 (without lv_gpu): TopazAdreno's thread waits for the root filesystem, then brings
the GPU up with the lavender sequences proven by lv_gpu=1..11 (TopazRpm.cpp: power with the GX rail
vote and the gfx BHS, the zap from the payload's firmware archive, the SMMU identity with plain
ldr/str) and starts the CP the a5xx way (PM4 + PFP microcode from the archive, a5_hw_init, ME_INIT,
SET_SECURE_MODE 0), publishes RedwoodGPU and runs one empty submission (a fence) as a self-test.

What changes in TopazAdreno.cpp (the A610 code stays, unused):
  addresses GCC 0x100000 / GPUCC 0x5065000 / GPU 0x5000000 / SMMU 0x5040000, GMEM 0x44000;
  the GPU pool (contiguous, below 4 GiB, GPU address = physical with the SMMU in bypass) moves from
  0x90000000, which overlaps modem/adsp/cdsp/splash on lavender, to 0xA1000000 (1 GB): free low RAM
  after pstore (DT reserved-memory ends at 0xa0400000), outside XNU's RAM (0x100000000+);
  hw_start -> lavender_gpu_bringup(); cp_start -> PM4/PFP, CP_ME/PFP_INSTR_BASE 0x838/0x835,
  CP_PFP_ME_CNTL 0x832 = 0; status registers RBBM_STATUS 0x4f5, CP_HW_FAULT 0xb1a, IB1 0xb1f-0xb21,
  always-on counter 0x4d2/0x4d3; parameters GPU_ID 512, CHIP_ID 0x05010200, highest bank bit 14;
  the SMMU's GFSR is read with ldr (hypervisor-emulated, see mk_gpu3.py).

usage: python mk_adreno.py XNU_TREE
"""
import sys

tree = sys.argv[1]
s = ''


def load(rel):
    global s, path
    path = f'{tree}/{rel}'
    s = open(path, newline='').read()


def save():
    open(path, 'w', newline='\n').write(s)


def sub(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:70], s.count(old))
    s = s.replace(old, new)


# ---------------------------------------------------------------- TopazRpm.cpp: exports
load('iokit/Kernel/arm/TopazRpm.cpp')
sub('''static void
lavender_gpu_zap(void)
{''', '''static bool lv_zap_ok;

static void
lavender_gpu_zap(void)
{''')
sub('''	LOG("LVZAP auth_and_reset: %#llx/%#llx -> %s"''', '''	lv_zap_ok = st == 0 && res == 0;
	LOG("LVZAP auth_and_reset: %#llx/%#llx -> %s"''')
sub('''static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''', '''/* ---- for the RedwoodGPU driver (TopazAdreno.cpp, patch 1014) ---- */
extern "C" bool
lavender_gpu_bringup(void)
{
	lavender_gpu_probe(7);
	if (!(lv_r(lv_gpucc, 0x1094) & 0x80000000u) || !(lv_r(lv_gpucc, 0x1004) & 0x80000000u)) {
		LOG("LVGPU bringup: power failed");
		return false;
	}
	lavender_gpu_zap();
	if (!lv_zap_ok) {
		LOG("LVGPU bringup: zap failed");
		return false;
	}
	lavender_gpu_smmu(10);
	if (!(sr(0x800) & 0x80000000u) || sr(0x48) != 0) {
		LOG("LVGPU bringup: SMMU not as expected");
		return false;
	}
	return true;
}

extern "C" void
lavender_a5xx_hw_init(void)
{
	a5_hw_init();
}

extern "C" uint32_t
lavender_smmu_gr_read(uint32_t off)
{
	return lv_smmu ? sr(off) : 0;
}

/* a file of the payload's firmware archive (mkpayload.py --fw), or NULL */
extern "C" const uint8_t *
lavender_fw(const char *name, uint32_t *size)
{
	static const volatile uint8_t *ar;
	uint64_t fwpa = 0;
	if (ar == NULL) {
		if (!PE_parse_boot_argn("lv_fwpa", &fwpa, sizeof(fwpa)) || fwpa == 0) {
			return NULL;
		}
		ar = (const volatile uint8_t *)ml_io_map_wcomb(fwpa, 0x40000);
		if (ar == NULL || memcmp((const void *)ar, "LVFW0001", 8) != 0) {
			ar = NULL;
			return NULL;
		}
	}
	return lv_fw_find(ar, name, size);
}

static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''')
save()

# ---------------------------------------------------------------- TopazAdreno.cpp
load('iokit/Kernel/arm/TopazAdreno.cpp')
sub('''#define GCC_BASE        0x01400000ull
#define GCC_SIZE        0x80000
#define GPUCC_BASE      0x05990000ull
#define GPUCC_SIZE      0x9000
#define GPU_BASE        0x05900000ull
#define GPU_SIZE        0x40000
#define SMMU_BASE       0x059A0000ull
#define SMMU_SIZE       0x10000''', '''/* lavender (SDM660, Adreno 512): see xnu/src/mk_adreno.py */
#define GCC_BASE        0x00100000ull
#define GCC_SIZE        0x80000
#define GPUCC_BASE      0x05065000ull
#define GPUCC_SIZE      0x2000
#define GPU_BASE        0x05000000ull
#define GPU_SIZE        0x40000
#define SMMU_BASE       0x05040000ull
#define SMMU_SIZE       0x10000
extern "C" bool lavender_gpu_bringup(void);
extern "C" void lavender_a5xx_hw_init(void);
extern "C" uint32_t lavender_smmu_gr_read(uint32_t off);
extern "C" const uint8_t *lavender_fw(const char *name, uint32_t *size);''')
sub('#define GMEM_SIZE           0x21000             /* 128K + 4K (bengal), TopazGpuW */',
    '#define GMEM_SIZE           0x44000             /* A512: 256K + 16K (Linux a5xx_catalog.c) */')
sub('#define GPU_POOL_BASE       0x90000000ull',
    '#define GPU_POOL_BASE       0xA1000000ull       /* lavender: free low RAM after pstore (0xa0400000) */')
sub('static struct kbuf ring, sqe, mem;', 'static struct kbuf ring, sqe, pfp, mem;')
# unused A610 paths
for fn in ('static bool\npower_up(void)', 'static bool\nzap_load(void)', 'static bool\nsmmu_setup(void)',
           'static void\nhw_init_regs(void)'):
    sub(fn, '__unused ' + fn)
sub('''	IOLog("TopazGPU: [%s] SMMU gfsr %08x CB0 FSR %08x FAR %08x%08x FSYNR0 %08x\\n", tag, rd(smmu, 0x48),''',
    '''	IOLog("TopazGPU: [%s] SMMU gfsr %08x CB0 FSR %08x FAR %08x%08x FSYNR0 %08x\\n", tag, lavender_smmu_gr_read(0x48),''')
sub('''	IOLog("TopazGPU: ring stuck: rptr %u wptr %u RBBM_STATUS %08x CP_HW_FAULT %08x\\n", gpu_rd(0x806),
	    wptr % RB_DWORDS, gpu_rd(0x210), gpu_rd(0x821));''', '''	IOLog("TopazGPU: ring stuck: rptr %u wptr %u RBBM_STATUS %08x CP_HW_FAULT %08x\\n", gpu_rd(0x806),
	    wptr % RB_DWORDS, gpu_rd(0x4f5), gpu_rd(0xb1a));''')

# cp_start: PM4 + PFP, a5xx init, ME start
sub('''	fw = (void *)topaz_fw_sqe_fw;
	fw_size = topaz_fw_sqe_fw_size;
	IOLog("TopazGPU: cp: SQE %zu bytes, allocating ring\\n", fw_size);
	if ((sqe.md == NULL && (!kbuf_alloc(&sqe, fw_size - 4) || !kbuf_map(&sqe))) ||
	    (ring.md == NULL && (!kbuf_alloc(&ring, RB_BYTES) || !kbuf_map(&ring))) ||
	    (mem.md == NULL && (!kbuf_alloc(&mem, PAGE_SIZE) || !kbuf_map(&mem)))) {
		IOLog("TopazGPU: CP buffers failed\\n");
		return false;
	}
	memcpy(sqe.va, (const uint8_t *)fw + 4, fw_size - 4);
	sweet_dcache_clean((vm_offset_t)sqe.va, (unsigned)(fw_size - 4));
	IOLog("TopazGPU: cp: SQE at GPU %#llx, ring %#llx\\n", sqe.iova, ring.iova);
	tlb_flush();
	hw_init_regs();
	gpu_wr64(0x830, sqe.iova);                      /* CP_SQE_INSTR_BASE */
	gpu_wr64(0x800, ring.iova);                     /* CP_RB_BASE */
	gpu_wr(0x802, 12 | (2 << 8) | (1u << 27));      /* CP_RB_CNTL */
	wptr = 0;
	gpu_wr(0x807, 0);
	__asm__ volatile ("dsb sy" ::: "memory");
	gpu_wr(0x808, 1);                               /* CP_SQE_CNTL */
''', '''	uint32_t pm4_size = 0, pfp_size = 0;
	const uint8_t *pm4 = lavender_fw("a530_pm4.fw", &pm4_size), *pfpfw = lavender_fw("a530_pfp.fw", &pfp_size);
	(void)fw;
	(void)fw_size;
	if (pm4 == NULL || pfpfw == NULL || pm4_size < 8 || pfp_size < 8) {
		IOLog("TopazGPU: cp: no PM4/PFP microcode (mkpayload.py --fw)\\n");
		return false;
	}
	IOLog("TopazGPU: cp: PM4 %u + PFP %u bytes, allocating ring\\n", pm4_size, pfp_size);
	if ((sqe.va == NULL && (!kbuf_alloc(&sqe, pm4_size - 4) || !kbuf_map(&sqe))) ||
	    (pfp.va == NULL && (!kbuf_alloc(&pfp, pfp_size - 4) || !kbuf_map(&pfp))) ||
	    (ring.va == NULL && (!kbuf_alloc(&ring, RB_BYTES) || !kbuf_map(&ring))) ||
	    (mem.va == NULL && (!kbuf_alloc(&mem, PAGE_SIZE) || !kbuf_map(&mem)))) {
		IOLog("TopazGPU: CP buffers failed\\n");
		return false;
	}
	for (uint32_t i = 4; i < pm4_size; i++) {
		sqe.va[i - 4] = pm4[i];
	}
	for (uint32_t i = 4; i < pfp_size; i++) {
		pfp.va[i - 4] = pfpfw[i];
	}
	__asm__ volatile ("dsb sy" ::: "memory");
	IOLog("TopazGPU: cp: PM4 at GPU %#llx, PFP %#llx, ring %#llx, fences %#llx\\n", sqe.iova, pfp.iova, ring.iova, mem.iova);
	lavender_a5xx_hw_init();
	gpu_wr64(0x838, sqe.iova);                      /* CP_ME_INSTR_BASE */
	gpu_wr64(0x835, pfp.iova);                      /* CP_PFP_INSTR_BASE */
	gpu_wr64(0x800, ring.iova);                     /* CP_RB_BASE */
	gpu_wr(0x802, 12 | (2 << 8) | (1u << 27));      /* CP_RB_CNTL */
	gpu_wr(0x038, 0);                               /* RBBM_INT_0_MASK: polled */
	wptr = 0;
	gpu_wr(0x807, 0);
	__asm__ volatile ("dsb sy" ::: "memory");
	gpu_wr(0x832, 0);                               /* CP_PFP_ME_CNTL: ME runs */
''')
sub('''	IOLog("TopazGPU: powered: RBBM_STATUS %08x\\n", gpu_rd(0x210));
	return zap_load() && smmu_setup() && cp_start();''', '''	IOLog("TopazGPU: powered: RBBM_STATUS %08x\\n", gpu_rd(0x4f5));
	return cp_start();''')
sub('''	if (!power_up()) {
		return false;
	}''', '''	if (!lavender_gpu_bringup()) {         /* power, zap, SMMU: TopazRpm.cpp (lv_gpu probe code) */
		return false;
	}''')
sub('''	case 0x01: *value = 610; return true;                   /* GPU_ID */''',
    '''	case 0x01: *value = 512; return true;                   /* GPU_ID */''')
sub('''	case 0x03: *value = 0x06010001; return true;            /* CHIP_ID */''',
    '''	case 0x03: *value = 0x05010200; return true;            /* CHIP_ID (DT qcom,chipid) */''')
sub('''		*value = ready ? ((uint64_t)gpu_rd(0x981) << 32 | gpu_rd(0x980)) : 0;''',
    '''		*value = ready ? ((uint64_t)gpu_rd(0x4d3) << 32 | gpu_rd(0x4d2)) : 0;     /* RBBM_ALWAYSON_COUNTER */''')
sub('''	case 0x10: *value = 13; return true;                    /* HIGHEST_BANK_BIT (a6xx_calc_ubwc_config a610) */''',
    '''	case 0x10: *value = 14; return true;                    /* HIGHEST_BANK_BIT (a5xx_hw_init hbb 1) */''')
sub('''	uint64_t ib1 = gpu_rd(0x928) | ((uint64_t)gpu_rd(0x929) << 32);''',
    '''	uint64_t ib1 = gpu_rd(0xb1f) | ((uint64_t)gpu_rd(0xb20) << 32);''')
sub('''	    seqno, mem.va ? *(volatile uint32_t *)mem.va : 0, gpu_rd(0x806), wptr % RB_DWORDS, gpu_rd(0x210),
	    gpu_rd(0x821), ib1, gpu_rd(0x92A));''', '''	    seqno, mem.va ? *(volatile uint32_t *)mem.va : 0, gpu_rd(0x806), wptr % RB_DWORDS, gpu_rd(0x4f5),
	    gpu_rd(0xb1a), ib1, gpu_rd(0xb21));''')
sub('''	if (ready) {
		gpu_wr(0x808, 0);
	}
	ready = false;''', '''	ready = false;                                  /* (the CP keeps running idle) */''')
sub('''	ready = true;
	RedwoodGPUStart();
	IOLog("TopazGPU: Adreno 610 ready, RedwoodGPU published\\n");''', '''	ready = true;
	RedwoodGPUStart();
	IOLog("TopazGPU: Adreno 512 ready, RedwoodGPU published\\n");
	uint32_t f = redwood_gpu_submit(NULL, NULL, 0);     /* self-test: an empty submission's fence */
	for (int i = 0; i < 1000 && f != 0 && !redwood_gpu_done(f); i++) {
		IODelay(100);
	}
	IOLog("TopazGPU: self-test fence %u -> %s\\n", f, f != 0 && redwood_gpu_done(f) ? "done" : "NOT DONE");''')
save()
print('ok')
