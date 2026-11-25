"""lavender GPU step 4: the GPU SMMU (arm,smmu-kgsl@5040000, SMMUv2), boot-args lv_gpu=9 / 10.

DT: qcom,smmu-v2, 64 KB (global spaces at 0x0 / 0x1000, context banks from 0x8000, 4 KB each),
qcom,skip-init (the secure side has programmed the stream matching), vdd = GPU CX GDSC (on), clocks
gcc_gpu_cfg_ahb / bimc_gfx / gpu_bimc_gfx (on since step 2). Context banks: gfx3d_user = SID 0,
gfx3d_secure = SID 2 (TrustZone's). attach-impl-defs: pairs written by Linux on attach.

lv_gpu=9: read only - sCR0, IDR0-2, GFSR, SMR/S2CR/CBAR/CBA2R of the non-secure entries only (0..NUMSMRG-1;
reading 3-7 hung the phone), CB0 SCTLR/FSR.
lv_gpu=10: (attach-impl-defs only with lv_smmu_impl=1: they hung the phone) then CB0 as the base's identity mode (TopazAdreno.cpp
smmu_setup with gpu_identity: CBA2R AArch64, CBAR S1 translate / S2 bypass, SCTLR 0xE0 = M off,
i.e. GPU addresses are physical), SMR0/S2CR0 only if the secure side left them unset; GFSR/FSR after.

usage: python mk_gpu3.py XNU_TREE
"""
import sys

tree = sys.argv[1]
p = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
s = open(p, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:60], s.count(old))
    s = s.replace(old, new)


SMMU = r'''
/* lavender GPU step 4 (lv_gpu=9 read, 10 program): GPU SMMU. See xnu/src/mk_gpu3.py. */
/*
 * Every SMMU access is one plain 32-bit ldr/str with a single base register: the SMMU's global
 * space is likely trapped and emulated by the hypervisor, which can only decode such accesses
 * (ESR ISV=1); a compiler-made ldp or writeback access cannot be emulated and hangs the phone.
 */
static volatile uint8_t *lv_smmu;
static uint32_t
sr(uint32_t off)
{
	uint32_t v;
	volatile uint8_t *a = lv_smmu + off;
	__asm__ volatile ("dsb sy\n\tldr %w0, [%1]" : "=r"(v) : "r"(a) : "memory");
	return v;
}
static void
sw(uint32_t off, uint32_t v)
{
	volatile uint8_t *a = lv_smmu + off;
	__asm__ volatile ("dsb sy\n\tstr %w0, [%1]\n\tdsb sy" :: "r"(v), "r"(a) : "memory");
}

static void
lavender_gpu_smmu_dump(const char *when)
{
	LOG("LVSMMU %s: sCR0 %#x IDR0 %#x IDR1 %#x IDR2 %#x GFSR %#x | CB0 SCTLR %#x FSR %#x TCR %#x",
	    when, sr(0x0), sr(0x20), sr(0x24), sr(0x28), sr(0x48),
	    sr(0x8000), sr(0x8058), sr(0x8030));
	/* only the non-secure stream-match groups / context banks: IDR0 NUMSMRG (3 here), IDR1 NUMCB (5).
	 * Reading entries 3-7 (secure side's) hung the phone a little later, twice (2026-11-25). */
	uint32_t nsmr = sr(0x20) & 0xff, ncb = sr(0x24) & 0xff;
	for (uint32_t i = 0; i < nsmr && i < 8; i++) {
		LOG("LVSMMU %s: [%u] SMR %#x S2CR %#x CBAR %#x CBA2R %#x", when, i,
		    sr(0x800 + 4 * i), sr(0xc00 + 4 * i), i < ncb ? sr(0x1000 + 4 * i) : 0, i < ncb ? sr(0x1800 + 4 * i) : 0);
	}
}

static void
lavender_gpu_smmu(uint32_t level)
{
	lv_smmu = (volatile uint8_t *)ml_io_map(0x05040000, 0x10000);
	if (lv_smmu == NULL) {
		LOG("LVSMMU map failed");
		return;
	}
	lavender_gpu_smmu_dump("before");
	if (level < 10) {
		return;
	}
	static const uint32_t impl[][2] = {     /* DT attach-impl-defs */
		{ 0x6000, 0x2378 }, { 0x6060, 0x1055 }, { 0x678c, 0x08 }, { 0x6794, 0x28 }, { 0x6800, 0x06 },
		{ 0x6900, 0x3ff }, { 0x6924, 0x204 }, { 0x6928, 0x11000 }, { 0x6930, 0x800 }, { 0x6960, 0xffffffff },
		{ 0x6b64, 0x1a5551 }, { 0x6b68, 0x9a82a382 },
	};
	/*
	 * 2026-11-25: writing attach-impl-defs straight away hung the whole phone (the first is 0x6000,
	 * qcom,micro-mmu-control; Linux halts the SMMU through it first). Off unless lv_smmu_impl=1.
	 * Every step is logged before it runs, so a hang names its register.
	 */
	uint32_t do_impl = 0;
	PE_parse_boot_argn("lv_smmu_impl", &do_impl, sizeof(do_impl));
	for (unsigned i = 0; do_impl && i < sizeof(impl) / sizeof(impl[0]); i++) {
		LOG("LVSMMU impl %#x = %#x", impl[i][0], impl[i][1]);
		sw(impl[i][0], impl[i][1]);
	}
	LOG("LVSMMU CB0 SCTLR off, FSR clear");
	sw(0x8000, 0);                     /* CB0 SCTLR off while programming */
	sw(0x8058, 0xffffffff);            /* CB0 FSR clear */
	LOG("LVSMMU CBA2R0 / CBAR0");
	sw(0x1800, 1);                     /* CBA2R0: AArch64 */
	sw(0x1000, 0x0001f000);            /* CBAR0: S1 translate, S2 bypass */
	LOG("LVSMMU CB0 SCTLR 0xe0 (M off)");
	sw(0x8000, 0xe0);                  /* SCTLR: M off = GPU addresses are physical */
	/*
	 * SID 0 exactly (DT iommus <smmu 0x00>, mask 0). SMR0 with mask 1 (SIDs 0-1, as the base did)
	 * hung the phone at once (2026-11-25): the stream-match table is likely the hypervisor's, which
	 * accepts only the streams the DT gives the HLOS. lv_smmu_smr=0 skips it.
	 */
	uint32_t do_smr = 1;
	PE_parse_boot_argn("lv_smmu_smr", &do_smr, sizeof(do_smr));
	if (do_smr && !(sr(0x800) & 0x80000000u)) {
		LOG("LVSMMU S2CR0 = translate CB0");
		sw(0xc00, 0);
		LOG("LVSMMU SMR0 = valid, SID 0, mask 0");
		sw(0x800, 1u << 31);
		LOG("LVSMMU SMR0 written");
	}
	LOG("LVSMMU GFSR clear, TLB");
	sw(0x48, sr(0x48));             /* GFSR: write back to clear */
	sw(0x8618, 0);                     /* CB0 TLBIALL */
	sw(0x87f0, 0);                     /* CB0 TLBSYNC */
	for (int i = 0; i < 1000 && (sr(0x87f4) & 1); i++) {
		IODelay(1);
	}
	IODelay(1000);
	lavender_gpu_smmu_dump("after");
}
'''

sub('''static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''', SMMU.lstrip('\n') + '''
static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''')
sub('''		if (gpu >= 8) {
			lavender_gpu_zap();
		}''', '''		if (gpu >= 8) {
			lavender_gpu_zap();
		}
		if (gpu >= 9) {
			lavender_gpu_smmu(gpu);
		}''')
open(p, 'w', newline='\n').write(s)
print('ok')
