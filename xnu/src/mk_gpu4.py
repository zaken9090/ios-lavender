"""lavender GPU steps 5-6: start the CP (PM4 + PFP microcode, a5xx_hw_init, ring, ME_INIT) and run a
first fence. Boot-arg lv_gpu=11 (after power, zap, SMMU identity).

After Linux drivers/gpu/drm/msm/adreno/a5xx_gpu.c a5xx_hw_init / a5xx_me_init (A512 branches: VBIF
gate-off, MERCIU 0x400, PC_DBG_ECO 0x200/0x200, RB_DBG_ECO bit 9, UCHE_DBG_ECO_CNTL_2, a512_hwcg,
quirk LMLOADKILL_DISABLE, GMEM 256K+16K, highest bank bit 14 -> hbb 1). Register offsets from Linux
drivers/gpu/drm/msm/registers/adreno/a5xx.xml (dword offsets). CP_PROTECT values = ADRENO_PROTECT_RW.

Memory: low RAM outside iOS (like the zap zone, see mk_gpu2.py), default 0x95400000 (lv_gpumem),
mapped as device memory (no cache upkeep): PM4 at +0, PFP at +0x8000 (the .fw files minus their
4-byte header, as adreno_fw_create_bo), ring 32 KB at +0x10000, fence words at +0x18000. The SMMU
context of SID 0 is in bypass (step 4), so GPU addresses are these physical addresses.

Ring: CP_RB_CNTL = BUFSZ log2(32K/8)=12 | BLKSZ log2(32/8)=2 << 8 | NO_UPDATE (bit 27); polled rptr.
Then: ME_INIT (8 dwords), CP_SET_SECURE_MODE 0 (the zap is loaded), PKT4 CP_SCRATCH_REG(1),
CP_EVENT_WRITE CACHE_FLUSH_TS -> fence word. Each is checked: rptr catches up, CP_HW_FAULT,
RBBM_STATUS, RBBM_INT_0_STATUS logged.

usage: python mk_gpu4.py XNU_TREE
"""
import sys

tree = sys.argv[1]
p = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
s = open(p, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:60], s.count(old))
    s = s.replace(old, new)


CP = r'''
/* lavender GPU steps 5-6 (lv_gpu=11): CP start and a first fence. See xnu/src/mk_gpu4.py. */
#define A5_VBIF_ROUND_ROBIN_QOS_ARB  0x3049
#define A5_VBIF_GATE_OFF_WRREQ_EN    0x302a
#define A5_RBBM_PERFCTR_GPU_BUSY_MASKED 0x046f
#define A5_RBBM_AHB_CNTL0            0x0093
#define A5_RBBM_AHB_CNTL1            0x0094
#define A5_RBBM_AHB_CNTL2            0x0095
#define A5_RBBM_INTERFACE_HANG_INT_CNTL 0x002f
#define A5_RBBM_PERFCTR_CNTL         0x0464
#define A5_CP_PERFCTR_CP_SEL_0       0x0bb0
#define A5_RBBM_PERFCTR_RBBM_SEL_0   0x046b
#define A5_SP_PERFCTR_SP_SEL_0       0x0ed0
#define A5_UCHE_CACHE_WAYS           0x0e96
#define A5_UCHE_WRITE_THRU_BASE      0x0e87
#define A5_UCHE_TRAP_BASE            0x0e89
#define A5_UCHE_GMEM_RANGE_MIN       0x0e8b
#define A5_UCHE_GMEM_RANGE_MAX       0x0e8d
#define A5_CP_MEQ_THRESHOLDS         0x0825
#define A5_CP_MERCIU_SIZE            0x0826
#define A5_CP_ROQ_THRESHOLDS_1       0x081f
#define A5_CP_ROQ_THRESHOLDS_2       0x0820
#define A5_PC_DBG_ECO_CNTL           0x0d00
#define A5_RB_DBG_ECO_CNTL           0x0cc4
#define A5_UCHE_MODE_CNTL            0x0e81
#define A5_CP_CHICKEN_DBG            0x0833
#define A5_TPL1_MODE_CNTL            0x0f02
#define A5_RB_MODE_CNTL              0x0cc6
#define A5_UCHE_DBG_ECO_CNTL_2       0x0e8f
#define A5_VPC_DBG_ECO_CNTL          0x0e60
#define A5_HLSQ_DBG_ECO_CNTL         0x0e04
#define A5_CP_PROTECT_CNTL           0x08a0
#define A5_CP_PROTECT(n)             (0x0880 + (n))
#define A5_RBBM_SECVID_TSB_TRUSTED_BASE_LO 0xf800
#define A5_RBBM_SECVID_TSB_TRUSTED_SIZE 0xf802
#define A5_RBBM_SECVID_TSB_CNTL      0xf803
#define A5_RBBM_SECVID_TRUST_CNTL    0xf400
#define A5_CP_ME_INSTR_BASE_LO       0x0838
#define A5_CP_PFP_INSTR_BASE_LO      0x0835
#define A5_CP_RB_BASE                0x0800
#define A5_CP_RB_CNTL                0x0802
#define A5_CP_RB_RPTR                0x0806
#define A5_CP_RB_WPTR                0x0807
#define A5_RBBM_INT_0_MASK           0x0038
#define A5_RBBM_INT_0_STATUS         0x04e1
#define A5_CP_PFP_ME_CNTL            0x0832
#define A5_RBBM_STATUS               0x04f5
#define A5_CP_HW_FAULT               0x0b1a
#define A5_CP_INTERRUPT_STATUS       0x0b18
#define A5_CP_SCRATCH(n)             (0x0b78 + (n))
#define A5_RBBM_CLOCK_CNTL           0x0067
#define A5_RBBM_ISDB_CNT             0x0533

static const uint16_t a5_addr_mode[] = {        /* *_ADDR_MODE_CNTL = 1: 64-bit addresses */
	0x0860, 0x0bc1, 0x0c81, 0x0cc5, 0x0d01, 0x0e05, 0x0e41, 0x0e61, 0x0e80, 0x0ec1, 0x0f01, 0xf810,
};

static const uint32_t a512_hwcg[][2] = {        /* Linux a5xx_gpu.c a512_hwcg */
	{ 0x0068, 0x02222222 }, { 0x0069, 0x02222222 }, { 0x006c, 0x02222220 }, { 0x006d, 0x02222220 },
	{ 0x0070, 0x0000F3CF }, { 0x0071, 0x0000F3CF }, { 0x0074, 0x00000080 }, { 0x0075, 0x00000080 },
	{ 0x004a, 0x22222222 }, { 0x004b, 0x22222222 }, { 0x004e, 0x22222222 }, { 0x004f, 0x22222222 },
	{ 0x0052, 0x00002222 }, { 0x0053, 0x00002222 }, { 0x00b0, 0x77777777 }, { 0x00b1, 0x77777777 },
	{ 0x00b4, 0x77777777 }, { 0x00b5, 0x77777777 }, { 0x00b8, 0x00007777 }, { 0x00b9, 0x00007777 },
	{ 0x00a4, 0x11111111 }, { 0x00a5, 0x11111111 }, { 0x00a8, 0x11111111 }, { 0x00a9, 0x11111111 },
	{ 0x00ac, 0x00001111 }, { 0x00ad, 0x00001111 }, { 0x005a, 0x22222222 }, { 0x005b, 0x22222222 },
	{ 0x005c, 0x22222222 }, { 0x005d, 0x00222222 }, { 0x005e, 0x00444444 }, { 0x005f, 0x00000002 },
	{ 0x0078, 0x22222222 }, { 0x0079, 0x22222222 }, { 0x007c, 0x00222222 }, { 0x007d, 0x00222222 },
	{ 0x0082, 0x00022220 }, { 0x0083, 0x00022220 }, { 0x008a, 0x05522222 }, { 0x008b, 0x00505555 },
	{ 0x0086, 0x04040404 }, { 0x0087, 0x04040404 }, { 0x0080, 0x07444044 }, { 0x008c, 0x00000002 },
	{ 0x008d, 0x00000002 }, { 0x0081, 0x00010011 }, { 0x0063, 0x04222222 }, { 0x0060, 0x02222222 },
	{ 0x0091, 0x00002222 }, { 0x0064, 0x00000000 }, { 0x0062, 0x04104004 }, { 0x0090, 0x00000000 },
	{ 0x0066, 0x00000000 }, { 0x0065, 0x00004000 }, { 0x0061, 0x00000200 }, { 0x0092, 0x00002222 },
};

static inline void g_w(uint32_t reg, uint32_t v) { lv_w(lv_gpu, reg * 4, v); }
static inline uint32_t g_r(uint32_t reg) { return lv_r(lv_gpu, reg * 4); }
static inline void g_w64(uint32_t reg, uint64_t v) { g_w(reg, (uint32_t)v); g_w(reg + 1, (uint32_t)(v >> 32)); }
static inline void g_rmw(uint32_t reg, uint32_t clr, uint32_t set) { g_w(reg, (g_r(reg) & ~clr) | set); }

static uint32_t
a5_par(uint32_t v)
{
	return (0x9669 >> (0xF & (v ^ (v >> 4) ^ (v >> 8) ^ (v >> 12) ^ (v >> 16) ^ (v >> 20) ^ (v >> 24) ^ (v >> 28)))) & 1;
}
static uint32_t a5_pkt7(uint32_t op, uint32_t cnt) { return 0x70000000u | cnt | (a5_par(cnt) << 15) | ((op & 0x7F) << 16) | (a5_par(op) << 23); }
static uint32_t a5_pkt4(uint32_t reg, uint32_t cnt) { return 0x40000000u | cnt | (a5_par(cnt) << 7) | ((reg & 0x3FFFF) << 8) | (a5_par(reg) << 27); }
static uint32_t a5_protect(uint32_t reg, uint32_t len) { return (1u << 30) | (1u << 29) | (((31 - __builtin_clz(len)) & 0x1F) << 24) | ((reg << 2) & 0xFFFFF); }

static volatile uint32_t *a5_ring;
static uint32_t a5_wptr;
#define A5_RB_DWORDS 0x2000                     /* 32 KB */

static void a5_emit(uint32_t v) { a5_ring[a5_wptr % A5_RB_DWORDS] = v; a5_wptr++; }

static bool
a5_kick_wait(const char *what)
{
	__asm__ volatile ("dsb sy" ::: "memory");
	g_w(A5_CP_RB_WPTR, a5_wptr % A5_RB_DWORDS);
	for (int i = 0; i < 100000; i++) {         /* up to 1 s */
		if (g_r(A5_CP_RB_RPTR) == a5_wptr % A5_RB_DWORDS && !(g_r(A5_RBBM_STATUS) & ~1u)) {
			LOG("LVCP %s: done after %d us (rptr %u, RBBM_STATUS %#x, HW_FAULT %#x, INT0 %#x)", what, i * 10,
			    g_r(A5_CP_RB_RPTR), g_r(A5_RBBM_STATUS), g_r(A5_CP_HW_FAULT), g_r(A5_RBBM_INT_0_STATUS));
			return true;
		}
		IODelay(10);
	}
	LOG("LVCP %s: STUCK rptr %u wptr %u RBBM_STATUS %#x HW_FAULT %#x INT0 %#x CP_INT %#x", what,
	    g_r(A5_CP_RB_RPTR), a5_wptr % A5_RB_DWORDS, g_r(A5_RBBM_STATUS), g_r(A5_CP_HW_FAULT),
	    g_r(A5_RBBM_INT_0_STATUS), g_r(A5_CP_INTERRUPT_STATUS));
	return false;
}

/* Linux a5xx_hw_init, the A512 branches (also called by the RedwoodGPU driver, patch 1014) */
static void
a5_hw_init(void)
{
	g_w(A5_VBIF_ROUND_ROBIN_QOS_ARB, 0x3);
	g_w(A5_VBIF_GATE_OFF_WRREQ_EN, 0x9);
	g_w(A5_RBBM_PERFCTR_GPU_BUSY_MASKED, 0xFFFFFFFF);
	g_w(A5_RBBM_AHB_CNTL0, 0x1);
	g_w(A5_RBBM_INTERFACE_HANG_INT_CNTL, (1u << 30) | 0xFFFF);
	g_w(A5_RBBM_PERFCTR_CNTL, 0x1);
	g_w(A5_CP_PERFCTR_CP_SEL_0, 0);                 /* PERF_CP_ALWAYS_COUNT */
	g_w(A5_RBBM_PERFCTR_RBBM_SEL_0, 6);
	g_w(A5_SP_PERFCTR_SP_SEL_0, 1);                 /* PERF_SP_ALU_WORKING_CYCLES */
	g_w(A5_UCHE_CACHE_WAYS, 0x02);
	g_w64(A5_UCHE_TRAP_BASE, 0x0001ffffffff0000ull);
	g_w64(A5_UCHE_WRITE_THRU_BASE, 0x0001ffffffff0000ull);
	g_w64(A5_UCHE_GMEM_RANGE_MIN, 0x00100000);
	g_w64(A5_UCHE_GMEM_RANGE_MAX, 0x00100000 + 0x44000 - 1);
	g_w(A5_CP_MEQ_THRESHOLDS, 0x40);
	g_w(A5_CP_MERCIU_SIZE, 0x400);
	g_w(A5_CP_ROQ_THRESHOLDS_2, 0x80000060);
	g_w(A5_CP_ROQ_THRESHOLDS_1, 0x40201B16);
	g_w(A5_PC_DBG_ECO_CNTL, (0x200u << 11) | (0x200u << 22));
	g_rmw(A5_RB_DBG_ECO_CNTL, 0, 1u << 9);
	g_w(A5_UCHE_MODE_CNTL, 1u << 29);
	g_w(A5_CP_CHICKEN_DBG, 0x02000000);
	g_w(A5_RBBM_AHB_CNTL1, 0xA6FFFFFF);
	for (unsigned i = 0; i < sizeof(a512_hwcg) / sizeof(a512_hwcg[0]); i++) {
		g_w(a512_hwcg[i][0], a512_hwcg[i][1]);
	}
	g_w(A5_RBBM_CLOCK_CNTL, 0xAAA8AA00);
	g_w(A5_RBBM_ISDB_CNT, 0x182);
	g_w(A5_RBBM_AHB_CNTL2, 0x3F);
	g_w(A5_TPL1_MODE_CNTL, 1u << 7);                /* hbb 1 */
	g_w(A5_RB_MODE_CNTL, 1u << 1);
	g_w(A5_UCHE_DBG_ECO_CNTL_2, 1);
	g_rmw(A5_VPC_DBG_ECO_CNTL, 0, 1u << 10);
	g_w(A5_CP_PROTECT_CNTL, 0x7);
	static const uint32_t prot[][2] = {
		{ 0x04, 4 }, { 0x08, 8 }, { 0x10, 16 }, { 0x20, 32 }, { 0x40, 64 }, { 0x80, 64 },
		{ A5_RBBM_SECVID_TSB_TRUSTED_BASE_LO, 16 }, { A5_RBBM_SECVID_TRUST_CNTL, 2 },
		{ 0x800, 64 }, { 0x840, 8 }, { 0x880, 32 }, { 0xAA0, 1 }, { 0xCC0, 1 }, { 0xCF0, 2 },
		{ 0xE68, 8 }, { 0xE70, 16 }, { 0xE80, 16 }, { 0x10000, 0x8000 },
	};
	for (unsigned i = 0; i < sizeof(prot) / sizeof(prot[0]); i++) {
		g_w(A5_CP_PROTECT(i), a5_protect(prot[i][0], prot[i][1]));
	}
	g_w(A5_RBBM_SECVID_TSB_CNTL, 0);
	g_w64(A5_RBBM_SECVID_TSB_TRUSTED_BASE_LO, 0);
	g_w(A5_RBBM_SECVID_TSB_TRUSTED_SIZE, 0);
	for (unsigned i = 0; i < sizeof(a5_addr_mode) / sizeof(a5_addr_mode[0]); i++) {
		g_w(a5_addr_mode[i], 1);
	}
	g_rmw(A5_VPC_DBG_ECO_CNTL, 0, 1u << 23);       /* quirk LMLOADKILL_DISABLE */
	g_rmw(A5_HLSQ_DBG_ECO_CNTL, 1u << 18, 0);
	LOG("LVCP hw_init written: RBBM_STATUS %#x HW_FAULT %#x INT0 %#x", g_r(A5_RBBM_STATUS), g_r(A5_CP_HW_FAULT),
	    g_r(A5_RBBM_INT_0_STATUS));
}

static void
lavender_gpu_cp(void)
{
	uint64_t fwpa = 0, mem = 0x95400000ull;
	PE_parse_boot_argn("lv_fwpa", &fwpa, sizeof(fwpa));
	PE_parse_boot_argn("lv_gpumem", &mem, sizeof(mem));
	const volatile uint8_t *ar = fwpa ? (const volatile uint8_t *)ml_io_map_wcomb(fwpa, 0x40000) : NULL;
	uint32_t pm4_size = 0, pfp_size = 0;
	const uint8_t *pm4 = ar ? lv_fw_find(ar, "a530_pm4.fw", &pm4_size) : NULL;
	const uint8_t *pfp = ar ? lv_fw_find(ar, "a530_pfp.fw", &pfp_size) : NULL;
	if (pm4 == NULL || pfp == NULL || pm4_size < 8 || pfp_size < 8 || pm4_size > 0x8004 || pfp_size > 0x8004) {
		LOG("LVCP microcode missing (pm4 %u, pfp %u)", pm4_size, pfp_size);
		return;
	}
	volatile uint8_t *m = (volatile uint8_t *)ml_io_map(mem, 0x20000);
	if (m == NULL) {
		LOG("LVCP map of %#llx failed", mem);
		return;
	}
	for (uint32_t i = 0; i < 0x20000; i += 4) {
		*(volatile uint32_t *)(m + i) = 0;
	}
	for (uint32_t i = 4; i < pm4_size; i++) {
		m[i - 4] = pm4[i];
	}
	for (uint32_t i = 4; i < pfp_size; i++) {
		m[0x8000 + i - 4] = pfp[i];
	}
	a5_ring = (volatile uint32_t *)(m + 0x10000);
	volatile uint32_t *fence = (volatile uint32_t *)(m + 0x18000);
	uint64_t pm4_pa = mem, pfp_pa = mem + 0x8000, ring_pa = mem + 0x10000, fence_pa = mem + 0x18000;
	LOG("LVCP pm4 %u pfp %u bytes (versions %#x %#x), ring %#llx, fence %#llx", pm4_size - 4, pfp_size - 4,
	    *(const uint32_t *)(pm4 + 4), *(const uint32_t *)(pfp + 4), ring_pa, fence_pa);

	a5_hw_init();

	g_w64(A5_CP_ME_INSTR_BASE_LO, pm4_pa);
	g_w64(A5_CP_PFP_INSTR_BASE_LO, pfp_pa);
	g_w64(A5_CP_RB_BASE, ring_pa);
	g_w(A5_CP_RB_CNTL, 12u | (2u << 8) | (1u << 27));
	g_w(A5_RBBM_INT_0_MASK, 0);                     /* polled, no interrupts */
	a5_wptr = 0;
	g_w(A5_CP_PFP_ME_CNTL, 0);                      /* clear ME_HALT: the micro engine runs */
	IODelay(100);
	LOG("LVCP ME running: PFP_ME_CNTL %#x RBBM_STATUS %#x HW_FAULT %#x", g_r(A5_CP_PFP_ME_CNTL),
	    g_r(A5_RBBM_STATUS), g_r(A5_CP_HW_FAULT));

	a5_emit(a5_pkt7(0x48, 8));                      /* CP_ME_INIT */
	a5_emit(0x0000002F);
	a5_emit(0x00000003);
	a5_emit(0x20000000);
	a5_emit(0);
	a5_emit(0);
	a5_emit(0);                                     /* A512: no microcode workarounds */
	a5_emit(0);
	a5_emit(0);
	if (!a5_kick_wait("ME_INIT")) {
		return;
	}
	a5_emit(a5_pkt7(0x66, 1));                      /* CP_SET_SECURE_MODE 0: leave secure mode (zap) */
	a5_emit(0);
	if (!a5_kick_wait("SET_SECURE_MODE 0")) {
		return;
	}
	a5_emit(a5_pkt4(A5_CP_SCRATCH(1), 1));          /* step 6a: a register write by the CP */
	a5_emit(0xC0FFEE01);
	bool ok = a5_kick_wait("PKT4 scratch");
	LOG("LVCP scratch1 = %#x (%s)", g_r(A5_CP_SCRATCH(1)), g_r(A5_CP_SCRATCH(1)) == 0xC0FFEE01 ? "CP WRITES REGISTERS" : "no");
	a5_emit(a5_pkt7(0x46, 4));                      /* step 6b: CP_EVENT_WRITE CACHE_FLUSH_TS -> memory */
	a5_emit(4);
	a5_emit((uint32_t)fence_pa);
	a5_emit((uint32_t)(fence_pa >> 32));
	a5_emit(0x5EED0001);
	ok &= a5_kick_wait("CACHE_FLUSH_TS");
	for (int i = 0; i < 1000 && fence[0] != 0x5EED0001; i++) {
		IODelay(10);
	}
	LOG("LVCP fence = %#x -> %s", fence[0], fence[0] == 0x5EED0001 ? "GPU WROTE MEMORY (fence ok)" : "no fence");
}
'''

sub('''static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''', CP.lstrip('\n') + '''
static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''')
sub('''		if (gpu >= 9) {
			lavender_gpu_smmu(gpu);
		}''', '''		if (gpu >= 9) {
			lavender_gpu_smmu(gpu);
		}
		if (gpu >= 11) {
			lavender_gpu_cp();
		}''')
open(p, 'w', newline='\n').write(s)
print('ok')
