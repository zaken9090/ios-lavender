"""lavender: the Wi-Fi block's SMMU (anoc2, 0x16c0000): dump and an identity stream (patch 1055).

Bisect e53/e54: the WLAN firmware hangs at the first request that makes it use the Wi-Fi hardware
("cap"), with the chip's four supplies and clock verified on from the PMIC side (1054). What is
left between the firmware and the hardware is the SMMU of the bus the Wi-Fi block sits on: stock
DT qcom,icnss has iommus = <anoc2_smmu 0x1a00>, <anoc2_smmu 0x1a01> with qcom,smmu-s1-bypass, and
Android attaches that stream when the driver probes, before the WLFW handshake. The base code's
note for its phone says the same: "a global bypass S2CR is turned into a fault by this SMMU. Done
before the modem boots" - but it runs only with wifi=1 and at topaz's SMMU address.

modem_smmu=1: read-only dump at modem start and in every summary - sCR0, IDR0/1, the global fault
registers (GFSR, GFSYNR0/1: a faulting stream id shows here), the non-secure SMR/S2CR entries.
modem_smmu=2: also gives stream 0x1a00 mask 1 a context bank with translation off (SCTLR.M=0),
the way smmu_identity() does, before the modem boots.

Every access is one plain 32-bit ldr/str (the hypervisor emulates SMMU accesses and can decode
nothing else, see TopazRpm.cpp); only the entries IDR0/IDR1 report are touched.

usage: python mk_wlansmmu.py XNU_TREE   (after mk_wlanrails.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static struct smem_part_hdr *g_part;
''', '''static struct smem_part_hdr *g_part;
static void lv_wlan_smmu(const char *when, bool program);
static uint32_t lv_wlan_smmu_mode;
''')
sub('''	smem_list(g_part);
	lv_serror_report("summary");
''', '''	smem_list(g_part);
	if (lv_wlan_smmu_mode != 0) {
		lv_wlan_smmu("summary", false);
	}
	lv_serror_report("summary");
''')
sub('''static bool
mss_mba_start(void)
{
''', '''/* ---- lavender: anoc2 SMMU, the Wi-Fi block's (xnu/src/mk_wlansmmu.py) ---- */
#define LV_ANOC2_SMMU_PA    0x016C0000ull
#define LV_ANOC2_SMMU_SIZE  0x00040000u
#define LV_WLAN_SID         0x1A00u
#define LV_WLAN_SID_MASK    0x1u

static volatile uint8_t *lv_a2;

static uint32_t
a2r(uint32_t off)
{
	uint32_t v;
	volatile uint8_t *a = lv_a2 + off;
	__asm__ volatile ("dsb sy\\n\\tldr %w0, [%1]" : "=r"(v) : "r"(a) : "memory");
	return v;
}

static void
a2w(uint32_t off, uint32_t v)
{
	volatile uint8_t *a = lv_a2 + off;
	__asm__ volatile ("dsb sy\\n\\tstr %w0, [%1]\\n\\tdsb sy" :: "r"(v), "r"(a) : "memory");
}

static void
lv_wlan_smmu(const char *when, bool program)
{
	if (lv_a2 == NULL) {
		lv_a2 = (volatile uint8_t *)ml_io_map(LV_ANOC2_SMMU_PA, LV_ANOC2_SMMU_SIZE);
		if (lv_a2 == NULL) {
			LOG("anoc2 smmu: map failed");
			return;
		}
	}
	uint32_t cr0 = a2r(0x0), id0 = a2r(0x20), id1 = a2r(0x24);
	uint32_t nsmr = id0 & 0xFF, ncb = id1 & 0xFF;
	uint32_t psize = (id1 & (1u << 31)) ? 0x10000 : 0x1000, npage = 1u << (((id1 >> 28) & 7) + 1);
	LOG("anoc2 smmu %s: sCR0 %08x IDR0 %08x IDR1 %08x: %u SMRs, %u CBs, page %x x%u; GFSR %08x GFSYNR0 %08x GFSYNR1 %08x", when,
	    cr0, id0, id1, nsmr, ncb, psize, npage, a2r(0x48), a2r(0x50), a2r(0x54));
	uint32_t slot = ~0u, cb = ~0u;
	uint64_t used = 0;
	for (uint32_t i = 0; i < nsmr && i < 32; i++) {
		uint32_t smr = a2r(0x800 + 4 * i), s2cr = a2r(0xC00 + 4 * i);
		if ((smr >> 31) != 0 || s2cr != 0) {
			LOG("anoc2 smmu %s: [%u] SMR %08x S2CR %08x", when, i, smr, s2cr);
		}
		uint32_t id = smr & 0xFFFF, m = (smr >> 16) & 0x7FFF;
		bool match = (smr >> 31) != 0 && ((id ^ LV_WLAN_SID) & ~(m | LV_WLAN_SID_MASK) & 0x7FFF) == 0;
		if (match) {
			slot = i;
		} else if ((smr >> 31) == 0 && slot == ~0u) {
			slot = i;
		}
		if ((smr >> 31) != 0 && ((s2cr >> 16) & 3) == 0) {
			used |= 1ull << (s2cr & 0x3F);
		}
	}
	if (!program) {
		return;
	}
	for (uint32_t i = ncb; i-- > 0;) {              /* the highest bank no valid stream uses */
		if (i < 64 && (used & (1ull << i)) == 0) {
			cb = i;
			break;
		}
	}
	if (slot == ~0u || cb == ~0u || (uint64_t)(npage + cb + 1) * psize > LV_ANOC2_SMMU_SIZE) {
		LOG("anoc2 smmu: no free SMR/CB (slot %u cb %u)", slot, cb);
		return;
	}
	uint32_t gr1 = psize, cbp = npage * psize + cb * psize;
	a2w(cbp + 0x58, 0xFFFFFFFF);                    /* FSR: clear */
	a2w(cbp + 0x20, 0);                             /* TTBR0 */
	a2w(cbp + 0x24, 0);
	a2w(cbp + 0x30, 0);                             /* TCR */
	a2w(cbp + 0x10, 0);                             /* TCR2 */
	a2w(cbp + 0x38, 0);                             /* MAIR */
	a2w(cbp + 0x3C, 0);
	a2w(gr1 + 0x800 + 4 * cb, CB_CLONE_CBA2R);
	a2w(gr1 + 0x000 + 4 * cb, CB_CLONE_CBAR);
	a2w(cbp + 0x0, CB_CLONE_SCTLR);                 /* SCTLR last: faults reported, no translation */
	a2w(0xC00 + 4 * slot, cb);                      /* S2CR: translate through this bank */
	a2w(0x800 + 4 * slot, (1u << 31) | (LV_WLAN_SID_MASK << 16) | LV_WLAN_SID);
	a2w(0x70, 0);                                   /* sTLBGSYNC */
	for (uint32_t n = 0; n < 100000 && (a2r(0x74) & 1) != 0; n++) {
		IODelay(1);
	}
	LOG("anoc2 smmu: WLAN stream %x/%x -> CB%u in SMR%u: SMR %08x S2CR %08x CBAR %08x SCTLR %08x", LV_WLAN_SID, LV_WLAN_SID_MASK,
	    cb, slot, a2r(0x800 + 4 * slot), a2r(0xC00 + 4 * slot), a2r(gr1 + 4 * cb), a2r(cbp));
}

static bool
mss_mba_start(void)
{
	(void)PE_parse_boot_argn("modem_smmu", &lv_wlan_smmu_mode, sizeof(lv_wlan_smmu_mode));
	if (lv_wlan_smmu_mode != 0) {
		lv_wlan_smmu("before the modem", lv_wlan_smmu_mode >= 2);
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
