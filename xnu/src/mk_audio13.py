"""lavender: audio A4b - SMMU fault state after the tone, buffer read back (patch 1131).

Run t5 (xnu 1130): cache cleaned, still SD0 (GPIO 14) low for all 20000 reads while 50 buffers a
second are taken without an error. The bank set up for SID 1 read back SCTLR 0 after writing
0xE0 (CBAR 0x1f000 took). If the ADSP's reads of the buffer are terminated by the SMMU (with
CFIE/CFRE off nothing is reported to it), it plays zeros.

Now after the tone, logged: GFSR/GFSYNR0-1, bank 0 FSR, FAR (64 bit), FSYNR0, SCTLR, the SMR/S2CR
for SID 1; and the first 8 samples of buffer 0 read back through our mapping.

usage: python mk_audio13.py XNU_TREE   (after mk_audio12.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()
old = '''	a4_playing = false;'''
assert s.count(old) == 1
s = s.replace(old, '''	a4_playing = false;
	{
		uint32_t id1 = lpr(0x24), psize = (id1 & (1u << 31)) ? 0x10000 : 0x1000, npage = 1u << (((id1 >> 28) & 7) + 1);
		uint32_t cbp = npage * psize;           /* bank 0 */
		LOG("A4b SMMU after: GFSR %08x GFSYNR0 %08x GFSYNR1 %08x | CB0 FSR %08x FAR %08x%08x FSYNR0 %08x SCTLR %08x | SMR0 %08x S2CR0 %08x",
		    lpr(0x48), lpr(0x50), lpr(0x54), lpr(cbp + 0x58), lpr(cbp + 0x64), lpr(cbp + 0x60), lpr(cbp + 0x68), lpr(cbp),
		    lpr(0x800), lpr(0xC00));
		const int16_t *s16 = (const int16_t *)a4_va;
		LOG("A4b buffer 0 starts: %d %d %d %d %d %d %d %d", s16[0], s16[1], s16[2], s16[3], s16[4], s16[5], s16[6], s16[7]);
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
