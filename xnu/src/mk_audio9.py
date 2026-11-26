"""lavender: audio A4b-3 - SID 1 through a context bank without translation (patch 1127).

Run t1 (xnu 1126): all set-up commands answered 0 (AFE clock/I2S/start, ASM map -> handle, ASM
open, ADM open -> copp 0, matrix map, media format), then after the 4 ASM writes and RUN the
whole phone stopped. The S2CR write for bypass (type 1, 0x10000) read back 0x20000 (fault): the
hypervisor does not allow bypass, so the ADSP's first buffer access with stream 1 faulted (the
bank config stalls on faults) and took the system down.

Now as for the Wi-Fi stream on the anoc2 SMMU (mk_wlansmmu.py, works): the lowest context bank,
FSR cleared, TTBR/TCR/MAIR 0, CBA2R 64-bit, CBAR S1 translate / S2 fault, SCTLR 0xE0 (M=0: no
translation, the ADSP's addresses are physical), then S2CR -> that bank and SMR (SID 1 exact).
Every write logged first; read back after. If S2CR does not read back as "translate, bank N",
the tone is not started (a4b_play needs lpass_smmu_sid1() true).

usage: python mk_audio9.py XNU_TREE   (after mk_audio8.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()
a = s.index('''	LOG("LPASS SMMU: S2CR%u = bypass", slot);''')
b = s.index('''	return true;
}''', a)
s = s[:a] + '''	uint32_t id1 = lpr(0x24), ncb = id1 & 0xFF;
	uint32_t psize = (id1 & (1u << 31)) ? 0x10000 : 0x1000, npage = 1u << (((id1 >> 28) & 7) + 1);
	uint32_t cb = 0, cbp = npage * psize + cb * psize;     /* no valid SMR uses any bank: the lowest */
	if (ncb == 0 || (uint64_t)cbp + psize > 0x40000) {
		LOG("LPASS SMMU: no bank (%u banks, page %x x%u)", ncb, psize, npage);
		return false;
	}
	LOG("LPASS SMMU: CB%u at +%x: SCTLR %08x FSR %08x CBAR %08x", cb, cbp, lpr(cbp), lpr(cbp + 0x58), lpr(psize + 4 * cb));
	LOG("LPASS SMMU: CB%u FSR clear, TTBR/TCR/MAIR 0", cb);
	lpw(cbp + 0x58, 0xFFFFFFFF);
	lpw(cbp + 0x20, 0);
	lpw(cbp + 0x24, 0);
	lpw(cbp + 0x30, 0);
	lpw(cbp + 0x10, 0);
	lpw(cbp + 0x38, 0);
	lpw(cbp + 0x3C, 0);
	LOG("LPASS SMMU: CBA2R/CBAR");
	lpw(psize + 0x800 + 4 * cb, 0x00000001u);         /* CBA2R: VA64 */
	lpw(psize + 0x000 + 4 * cb, 0x0001f000u);         /* CBAR: S1 translate, S2 fault, WB */
	LOG("LPASS SMMU: SCTLR 0xe0 (M=0)");
	lpw(cbp, 0x000000e0u);
	LOG("LPASS SMMU: S2CR%u = bank %u", slot, cb);
	lpw(0xC00 + 4 * slot, cb);
	LOG("LPASS SMMU: SMR%u = valid, SID 1, mask 0", slot);
	lpw(0x800 + 4 * slot, (1u << 31) | 1);
	lpw(0x70, 0);                                   /* sTLBGSYNC */
	for (uint32_t i = 0; i < 100000 && (lpr(0x74) & 1) != 0; i++) {
		IODelay(1);
	}
	uint32_t s2 = lpr(0xC00 + 4 * slot);
	LOG("LPASS SMMU: SMR%u %08x S2CR %08x CBAR %08x SCTLR %08x GFSR %08x", slot, lpr(0x800 + 4 * slot), s2, lpr(psize + 4 * cb),
	    lpr(cbp), lpr(0x48));
	if (((s2 >> 16) & 3) != 0 || (s2 & 0xFF) != cb) {
		LOG("LPASS SMMU: S2CR not taken - no tone");
		return false;
	}
''' + s[b:]
open(path, 'w', newline='\n').write(s)
print('ok')
