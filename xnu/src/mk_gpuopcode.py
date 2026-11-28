"""lavender: a GPU hang on a CP opcode error says which opcode (patch 1169).

The hangs after opening Messages (usblog-y1-after, 15 of them) are not pipeline waits: RBBM_STATUS
0x800001c1 has no block busy, CP_INTERRUPT_STATUS = 1 = CP_OPCODE_ERROR - the CP met a packet it
does not know and stopped. As Linux a5xx_cp_err_irq: CP_PFP_STAT_ADDR (0x808) = 0, the second read
of CP_PFP_STAT_DATA (0x809) is the opcode (four reads are logged).

usage: python mk_gpuopcode.py XNU_TREE
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


a = f'{tree}/iokit/Kernel/arm/TopazAdreno.cpp'
patch(a, '''	    gpu_rd(0xb24), gpu_rd(0x530), gpu_rd(0x4e1), gpu_rd(0xb18), gpu_rd(0xb78), gpu_rd(0xb79), gpu_rd(0xb7a), gpu_rd(0xb7b));
''', '''	    gpu_rd(0xb24), gpu_rd(0x530), gpu_rd(0x4e1), gpu_rd(0xb18), gpu_rd(0xb78), gpu_rd(0xb79), gpu_rd(0xb7a), gpu_rd(0xb7b));
	if (gpu_rd(0xb18) & 1) {
		/* lavender (mk_gpuopcode.py): CP_OPCODE_ERROR - which opcode (Linux a5xx_cp_err_irq) */
		uint32_t stat[4];

		gpu_wr(0x808, 0);
		for (unsigned i = 0; i < 4; i++) {
			stat[i] = gpu_rd(0x809);
		}
		IOLog("TopazGPU: %s: CP opcode error, possible opcode %08x (PFP stat %08x %08x %08x %08x)\\n", why, stat[1], stat[0], stat[1], stat[2], stat[3]);
	}
''')
print('ok')
