"""lavender: audio A4b-1 - LPASS SMMU read, MI2S bit clock seen on the pin (patch 1125).

Run e136 (xnu 1124, A4a): AFE clock set, I2S config, DEVICE_START and the stops all answered
status 0; MAX98927 took its whole init table (read back right). Its 0x0011 stayed 0x1 with and
without clocks, so whether BCLK runs is not known from the amplifier.

Now, read only:
- while PRIMARY_MI2S_RX runs, GPIO 12 (SCK) and 13 (WS) are sampled 20000 times through the TLMM
  IN_OUT input bit: both levels seen = the clock runs (logged as counts of highs);
- the LPASS SMMU (stock DT smmu-lpass_q6 @0x05100000, 0x40000) after voting its clocks the way
  the DT lists them (GCC hlos1_vote_lpass_adsp_smmu_clk 0x0017D014 bit 0; the GDSC vote
  hlos1_vote_lpass_adsp 0x0017D034 bit 0): sCR0, IDR0/1, GFSR, every valid SMR/S2CR among the
  non-secure ones (IDR0 NUMSMRG), and the bank SID 1 (audio buffers, DT msm-audio-ion iommus
  <lpass_q6 1>) goes to, with its SCTLR/TCR. Plain ldr only (the hypervisor emulates single
  32-bit accesses; see the GPU and anoc2 SMMU work). Nothing is written to the SMMU yet.
Runs inside the A4a test (audio_step=1).

usage: python mk_audio7.py XNU_TREE   (after mk_audio6.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''/* A4a: amplifier set up, MI2S clocks through the AFE port, read the amplifier while they run, stop */''', r'''/* ---- A4b-1 (mk_audio7.py): LPASS SMMU, read only, single 32-bit ldr */
extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
static volatile uint8_t *lp_smmu;
static uint32_t
lpr(uint32_t off)
{
	uint32_t v;
	volatile uint8_t *a = lp_smmu + off;
	__asm__ volatile ("dsb sy\n\tldr %w0, [%1]" : "=r"(v) : "r"(a) : "memory");
	return v;
}

static void
lpass_smmu_dump(void)
{
	volatile uint32_t *gcc = (volatile uint32_t *)ml_io_map(0x0017D000, 0x1000);
	if (gcc == NULL) {
		LOG("LPASS SMMU: GCC map failed");
		return;
	}
	LOG("LPASS SMMU: GCC votes before: smmu clk %#x gdsc %#x", gcc[0x14 / 4], gcc[0x34 / 4]);
	gcc[0x34 / 4] |= 1;                             /* hlos1_vote_lpass_adsp GDSC */
	gcc[0x14 / 4] |= 1;                             /* hlos1_vote_lpass_adsp_smmu_clk */
	IOSleep(5);
	LOG("LPASS SMMU: GCC votes after: smmu clk %#x gdsc %#x", gcc[0x14 / 4], gcc[0x34 / 4]);
	lp_smmu = (volatile uint8_t *)ml_io_map(0x05100000, 0x40000);
	if (lp_smmu == NULL) {
		LOG("LPASS SMMU: map failed");
		return;
	}
	uint32_t id0 = lpr(0x20), id1 = lpr(0x24);
	uint32_t nsmr = id0 & 0xFF, ncb = id1 & 0xFF;
	uint32_t psize = (id1 & (1u << 31)) ? 0x10000 : 0x1000, npage = 1u << (((id1 >> 28) & 7) + 1);
	LOG("LPASS SMMU: sCR0 %08x IDR0 %08x IDR1 %08x: %u SMRs, %u CBs, page %x x%u; GFSR %08x", lpr(0x0), id0, id1, nsmr, ncb, psize,
	    npage, lpr(0x48));
	for (uint32_t i = 0; i < nsmr && i < 32; i++) {
		uint32_t smr = lpr(0x800 + 4 * i), s2cr = lpr(0xC00 + 4 * i);
		if ((smr >> 31) == 0 && s2cr == 0) {
			continue;
		}
		uint32_t cb = s2cr & 0xFF, cbp = npage * psize + cb * psize;
		bool to_cb = ((s2cr >> 16) & 3) == 0 && cb < ncb && (uint64_t)cbp + psize <= 0x40000;
		LOG("LPASS SMMU: [%u] SMR %08x (sid %#x mask %#x) S2CR %08x%s", i, smr, smr & 0xFFFF, (smr >> 16) & 0x7FFF, s2cr,
		    to_cb ? "" : " (no bank)");
		if (to_cb) {
			LOG("LPASS SMMU:   CB%u CBAR %08x SCTLR %08x TCR %08x TTBR0 %08x%08x FSR %08x", cb, lpr(psize + 4 * cb), lpr(cbp),
			    lpr(cbp + 0x30), lpr(cbp + 0x24), lpr(cbp + 0x20), lpr(cbp + 0x58));
		}
	}
}

/* GPIO 12 (SCK) and 13 (WS) levels while the port runs: a clock shows both */
static void
mi2s_sample(void)
{
	volatile uint32_t *g = (volatile uint32_t *)ml_io_map(0x03900000 + 0x1000 * 12, 0x2000);
	if (g == NULL) {
		return;
	}
	unsigned sck = 0, ws = 0;
	for (unsigned i = 0; i < 20000; i++) {
		sck += g[1] & 1;
		ws += g[0x1000 / 4 + 1] & 1;
	}
	LOG("pri_mi2s pins: of 20000 reads SCK high %u, WS high %u (a running clock: both well between 0 and 20000)", sck, ws);
}

/* A4a: amplifier set up, MI2S clocks through the AFE port, read the amplifier while they run, stop */''')
sub('''			IOSleep(50);
			amp_status("with clocks");''', '''			IOSleep(50);
			amp_status("with clocks");
			mi2s_sample();''')
sub('''	lv_mi2s_pins(false);
	LOG("A4a done (amp %s)", amp ? "set up" : "NOT set up");''', '''	lv_mi2s_pins(false);
	LOG("A4a done (amp %s)", amp ? "set up" : "NOT set up");
	lpass_smmu_dump();''')
open(path, 'w', newline='\n').write(s)
print('ok')
