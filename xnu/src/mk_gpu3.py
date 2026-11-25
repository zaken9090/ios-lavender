"""lavender GPU step 4: the GPU SMMU (arm,smmu-kgsl@5040000, SMMUv2), boot-args lv_gpu=9 / 10.

DT: qcom,smmu-v2, 64 KB (global spaces at 0x0 / 0x1000, context banks from 0x8000, 4 KB each),
qcom,skip-init (the secure side has programmed the stream matching), vdd = GPU CX GDSC (on), clocks
gcc_gpu_cfg_ahb / bimc_gfx / gpu_bimc_gfx (on since step 2). Context banks: gfx3d_user = SID 0,
gfx3d_secure = SID 2 (TrustZone's). attach-impl-defs: pairs written by Linux on attach.

lv_gpu=9: read only - sCR0, IDR0-2, GFSR, SMR/S2CR/CBAR/CBA2R 0-7, CB0 SCTLR/FSR.
lv_gpu=10: also write attach-impl-defs, then CB0 as the base's identity mode (TopazAdreno.cpp
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
static void
lavender_gpu_smmu_dump(volatile uint32_t *m, const char *when)
{
	LOG("LVSMMU %s: sCR0 %#x IDR0 %#x IDR1 %#x IDR2 %#x GFSR %#x | CB0 SCTLR %#x FSR %#x TCR %#x",
	    when, m[0x0 / 4], m[0x20 / 4], m[0x24 / 4], m[0x28 / 4], m[0x48 / 4],
	    m[0x8000 / 4], m[0x8058 / 4], m[0x8030 / 4]);
	for (int i = 0; i < 8; i++) {
		LOG("LVSMMU %s: [%d] SMR %#x S2CR %#x CBAR %#x CBA2R %#x", when, i,
		    m[(0x800 + 4 * i) / 4], m[(0xc00 + 4 * i) / 4], m[(0x1000 + 4 * i) / 4], m[(0x1800 + 4 * i) / 4]);
	}
}

static void
lavender_gpu_smmu(uint32_t level)
{
	volatile uint32_t *m = (volatile uint32_t *)ml_io_map(0x05040000, 0x10000);
	if (m == NULL) {
		LOG("LVSMMU map failed");
		return;
	}
	lavender_gpu_smmu_dump(m, "before");
	if (level < 10) {
		return;
	}
	static const uint32_t impl[][2] = {     /* DT attach-impl-defs */
		{ 0x6000, 0x2378 }, { 0x6060, 0x1055 }, { 0x678c, 0x08 }, { 0x6794, 0x28 }, { 0x6800, 0x06 },
		{ 0x6900, 0x3ff }, { 0x6924, 0x204 }, { 0x6928, 0x11000 }, { 0x6930, 0x800 }, { 0x6960, 0xffffffff },
		{ 0x6b64, 0x1a5551 }, { 0x6b68, 0x9a82a382 },
	};
	for (unsigned i = 0; i < sizeof(impl) / sizeof(impl[0]); i++) {
		lv_w((volatile uint32_t *)m, impl[i][0], impl[i][1]);
	}
	lv_w(m, 0x8000, 0);                     /* CB0 SCTLR off while programming */
	lv_w(m, 0x8058, 0xffffffff);            /* CB0 FSR clear */
	lv_w(m, 0x1800, 1);                     /* CBA2R0: AArch64 */
	lv_w(m, 0x1000, 0x0001f000);            /* CBAR0: S1 translate, S2 bypass */
	lv_w(m, 0x8000, 0xe0);                  /* SCTLR: M off = GPU addresses are physical */
	if (!(m[0x800 / 4] & 0x80000000u)) {    /* SMR0 not valid: SID 0 -> CB0 */
		lv_w(m, 0xc00, 0);
		lv_w(m, 0x800, (1u << 31) | (1u << 16));
		LOG("LVSMMU SMR0 was unset: SID 0 -> CB0");
	}
	lv_w(m, 0x48, m[0x48 / 4]);             /* GFSR: write back to clear */
	lv_w(m, 0x8618, 0);                     /* CB0 TLBIALL */
	lv_w(m, 0x87f0, 0);                     /* CB0 TLBSYNC */
	for (int i = 0; i < 1000 && (m[0x87f4 / 4] & 1); i++) {
		IODelay(1);
	}
	IODelay(1000);
	lavender_gpu_smmu_dump(m, "after");
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
