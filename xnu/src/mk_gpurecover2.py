"""lavender: the GPU reset of a recovery halts the bus interface first and tries twice (patch 1166).

Recoveries sometimes failed ("recovery FAILED: RBBM_STATUS c00003c1 rptr 0 wptr 9": the CP did not take
ME_INIT after the software reset; the screen stays black or garbled until a reboot; runs rb1, m3, s2).
The hangs they followed had bus activity pending (RBBM_STATUS e61803c1). KGSL does not reset an Adreno
with transactions on its bus: adreno_vbif_clear_pending_transactions() halts the VBIF
(VBIF_XIN_HALT_CTRL0 = 0xF), waits for the acknowledge (CTRL1), resets, lets the halt go.

Now redwood_gpu_recover() does the same, and when the CP still does not start it resets and starts once
more after 2 ms. The log line says whether the halt was acknowledged and which try worked.

usage: python mk_gpurecover2.py XNU_TREE   (after mk_thermalguard.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAdreno.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	IOLockLock(hw_lock);
	gpu_wr(0x43, 1);                                /* RBBM_SW_RESET_CMD */
	(void)gpu_rd(0x43);
	IODelay(100);
	gpu_wr(0x43, 0);
	IODelay(100);
	ok = cp_start();
''', '''	bool halted = false;
	int tries = 0;

	IOLockLock(hw_lock);
	do {
		/* lavender (mk_gpurecover2.py): no reset with transactions on the bus - halt the VBIF first, as KGSL */
		gpu_wr(0x3080, 0xF);                    /* VBIF_XIN_HALT_CTRL0 */
		halted = false;
		for (int i = 0; i < 2000 && !halted; i++) {
			halted = (gpu_rd(0x3081) & 0xF) == 0xF;         /* VBIF_XIN_HALT_CTRL1: acknowledged */
			if (!halted) {
				IODelay(10);
			}
		}
		gpu_wr(0x43, 1);                        /* RBBM_SW_RESET_CMD */
		(void)gpu_rd(0x43);
		IODelay(tries == 0 ? 100 : 2000);
		gpu_wr(0x43, 0);
		IODelay(tries == 0 ? 100 : 2000);
		gpu_wr(0x3080, 0);
		ok = cp_start();
	} while (!ok && ++tries < 2);
''')
sub('''	IOLog("TopazGPU: recovery %s: RBBM_STATUS %08x rptr %u wptr %u fence %u\\n", ok ? "done" : "FAILED", gpu_rd(0x4f5),
	    gpu_rd(0x806), wptr % RB_DWORDS, seqno);''', '''	IOLog("TopazGPU: recovery %s: RBBM_STATUS %08x rptr %u wptr %u fence %u (bus halt %s, try %d)\\n", ok ? "done" : "FAILED",
	    gpu_rd(0x4f5), gpu_rd(0x806), wptr % RB_DWORDS, seqno, halted ? "acknowledged" : "NOT acknowledged", tries + (ok ? 1 : 0));''')
open(path, 'w', newline='\n').write(s)
print('ok')
