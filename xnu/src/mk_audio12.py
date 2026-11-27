"""lavender: audio A4b - clean the tone buffers out of the CPU cache (patch 1130).

Run t4 (xnu 1129): the ADSP takes 50 buffers a second without errors, but SD0 (GPIO 14, the data
line to the amplifier) stayed low for all 20000 reads: the samples that reach the I2S port are
zeros. The tone was written through the kernel mapping of TopazModem's pool, which is cacheable,
and only a dsb followed - the lines can sit in the CPU cache while the ADSP reads DRAM (zeros).
(Also: MAX98927 GLOBAL_EN read back 0 after writing 1 - to look at with audio_amp_on once data
flows.)

Now after filling, every 64-byte line of the 16 KB is cleaned and invalidated to the point of
coherency (dc civac), then dsb sy.

usage: python mk_audio12.py XNU_TREE   (after mk_audio11.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()
old = '''	LOG("A4b: tone %u Hz, peak %u", freq, level);'''
assert s.count(old) == 1
s = s.replace(old, '''	LOG("A4b: tone %u Hz, peak %u", freq, level);
	for (uintptr_t a = (uintptr_t)a4_va; a < (uintptr_t)a4_va + A4_BUF_N * 4096u; a += 64) {
		__asm__ volatile ("dc civac, %0" :: "r"(a) : "memory");     /* to DRAM: the ADSP reads there */
	}
	__asm__ volatile ("dsb sy" ::: "memory");''')
open(path, 'w', newline='\n').write(s)
print('ok')
