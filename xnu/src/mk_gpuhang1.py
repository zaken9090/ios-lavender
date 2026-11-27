"""lavender: GPU hang - full a5xx state at a hang and recovery as Linux a5xx_recover() (patch 1139).

Seen in 9 logs (bench e22..g3, usblog e128/e129/ia1): "TopazGPU: no answer", always the same picture:
the CP inside an IB1 of the first command buffer (IB1 page aligned, 215-311 dwords left), RBBM_STATUS
0x800001c1 (HI, RAS, RB, PC_DCALL busy: a draw that does not finish), CP_HW_FAULT 0, SMMU no fault.
After that the driver never waited again: every later submission failed with -60 (ETIMEDOUT, ring
full) and the UI froze or flickered.

Now:
- the report also gives IB2 base/rem, RBBM_STATUS3, INT0, CP interrupt status, scratch registers,
  the ring around the read pointer and the first dwords of the IB1 and IB2 the CP is in (identity
  SMMU: GPU address = physical), to decode the packet that hangs (gpu_hangdump=0: off);
- then, as Linux a5xx_recover(): RBBM_SW_RESET_CMD (0x43) 1/0, the CP started again (hw init,
  microcode, ME_INIT, SET_SECURE_MODE 0), every fence given so far written as done. At most 20 times
  per boot. gpu_recover=0: the old behaviour (stays stopped).
- a ring-full submission is tried once more after a recovery.

usage: python mk_gpuhang1.py XNU_TREE   (after mk_cleanup1.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


ta = f'{tree}/iokit/Kernel/arm/TopazAdreno.cpp'
patch(ta, '''void redwood_gpu_report(const char *why);
void redwood_gpu_stop(void);''', '''void redwood_gpu_report(const char *why);
bool redwood_gpu_recover(void);
void redwood_gpu_stop(void);''')

patch(ta, '''	IOLog("TopazGPU: %s: fence %u done %u rptr %u wptr %u RBBM_STATUS %08x CP_HW_FAULT %08x IB1 %llx rem %u\\n", why,
	    seqno, mem.va ? *(volatile uint32_t *)mem.va : 0, gpu_rd(0x806), wptr % RB_DWORDS, gpu_rd(0x4f5),
	    gpu_rd(0xb1a), ib1, gpu_rd(0xb21));
	smmu_fault(why);
}
''', '''	IOLog("TopazGPU: %s: fence %u done %u rptr %u wptr %u RBBM_STATUS %08x CP_HW_FAULT %08x IB1 %llx rem %u\\n", why,
	    seqno, mem.va ? *(volatile uint32_t *)mem.va : 0, gpu_rd(0x806), wptr % RB_DWORDS, gpu_rd(0x4f5),
	    gpu_rd(0xb1a), ib1, gpu_rd(0xb21));
	smmu_fault(why);
	hang_dump(why, ib1);                            /* mk_gpuhang1.py */
}

/*
 * lavender (mk_gpuhang1.py): a GPU that stopped answering stayed stopped and the UI froze. As Linux
 * a5xx_recover(): software reset, the CP started again; what was given before is written as done.
 */
bool
redwood_gpu_recover(void)
{
	bool ok;

	if (!ready) {
		return false;
	}
	IOLockLock(hw_lock);
	gpu_wr(0x43, 1);                                /* RBBM_SW_RESET_CMD */
	(void)gpu_rd(0x43);
	IODelay(100);
	gpu_wr(0x43, 0);
	IODelay(100);
	ok = cp_start();
	if (ok && mem.va != NULL) {
		*(volatile uint32_t *)mem.va = seqno;   /* everything given before is over */
		sweet_dcache_clean((vm_offset_t)mem.va, 64);
	}
	IOLockUnlock(hw_lock);
	IOLog("TopazGPU: recovery %s: RBBM_STATUS %08x rptr %u wptr %u fence %u\\n", ok ? "done" : "FAILED", gpu_rd(0x4f5),
	    gpu_rd(0x806), wptr % RB_DWORDS, seqno);
	return ok;
}
''')

# the dump helper, before redwood_gpu_report
patch(ta, '''void
redwood_gpu_report(const char *why)
{''', '''/* n dwords at GPU address va (identity SMMU only), 8 a line */
static void
hang_words(const char *why, const char *what, uint64_t va, uint32_t n)
{
	if (!gpu_identity || va == 0 || (va & 3) || n == 0) {
		return;
	}
	uint64_t page = va & ~0xfffull;
	vm_offset_t m = ml_io_map((vm_offset_t)page, 0x2000);
	if (m == 0) {
		return;
	}
	volatile uint32_t *w = (volatile uint32_t *)(m + (va - page));
	uint32_t most = (uint32_t)((0x2000 - (va - page)) / 4);
	n = n < most ? n : most;
	for (uint32_t i = 0; i < n; i += 8) {
		IOLog("TopazGPU: %s: %s+%03x: %08x %08x %08x %08x %08x %08x %08x %08x\\n", why, what, i, w[i], w[i + 1], w[i + 2],
		    w[i + 3], w[i + 4], w[i + 5], w[i + 6], w[i + 7]);
	}
}

static void
hang_dump(const char *why, uint64_t ib1)
{
	uint32_t on = 1;
	(void)PE_parse_boot_argn("gpu_hangdump", &on, sizeof(on));
	if (on == 0) {
		return;
	}
	uint64_t ib2 = gpu_rd(0xb22) | ((uint64_t)gpu_rd(0xb23) << 32);
	uint32_t rptr = gpu_rd(0x806);
	IOLog("TopazGPU: %s: IB2 %llx rem %u STATUS3 %08x INT0 %08x CP_INT %08x SCRATCH %08x %08x %08x %08x\\n", why, ib2,
	    gpu_rd(0xb24), gpu_rd(0x530), gpu_rd(0x4e1), gpu_rd(0xb18), gpu_rd(0xb78), gpu_rd(0xb79), gpu_rd(0xb7a), gpu_rd(0xb7b));
	if (ring.va != NULL) {
		/* the ring before the CP's read pointer: the IB packet it took last (with its size) */
		volatile uint32_t *r = (volatile uint32_t *)ring.va;
		for (uint32_t row = 0; row < 3; row++) {
			uint32_t at = (rptr + RB_DWORDS - 16 + row * 8) % RB_DWORDS;
			IOLog("TopazGPU: %s: ring@%u: %08x %08x %08x %08x %08x %08x %08x %08x\\n", why, at, r[at], r[(at + 1) % RB_DWORDS],
			    r[(at + 2) % RB_DWORDS], r[(at + 3) % RB_DWORDS], r[(at + 4) % RB_DWORDS], r[(at + 5) % RB_DWORDS],
			    r[(at + 6) % RB_DWORDS], r[(at + 7) % RB_DWORDS]);
		}
	}
	hang_words(why, "IB1", ib1, 352);
	hang_words(why, "IB2", ib2, 64);
}

void
redwood_gpu_report(const char *why)
{''')

rw = f'{tree}/iokit/Kernel/arm/RedwoodGPU.cpp'
patch(rw, '''void redwood_gpu_report(const char * why);
void redwood_gpu_stop(void);''', '''void redwood_gpu_report(const char * why);
bool redwood_gpu_recover(void);
void redwood_gpu_stop(void);''')
patch(rw, '''/* Wait for the 3D core to be done with submission `fence`; with the lock held, which is let go of while waiting. */''',
      '''/*
 * lavender (mk_gpuhang1.py): the GPU stopped answering: report it, then reset it and go on as Linux
 * a5xx_recover() does (boot-arg gpu_recover=0: stay stopped; at most 20 a boot). With the lock held.
 */
static uint32_t gGPURecovered;

static void
gpuHung(const char * why)
{
	uint32_t recover = 1;

	gGPUReported = true;
	redwood_gpu_report(why);
	PE_parse_boot_argn("gpu_recover", &recover, sizeof(recover));
	if (recover != 0 && gGPURecovered < 20 && redwood_gpu_recover()) {
		gGPURecovered++;
		gGPUReported = false;
		IOLog("RedwoodGPU: the GPU was reset (%u so far)\\n", gGPURecovered);
	}
}

/* Wait for the 3D core to be done with submission `fence`; with the lock held, which is let go of while waiting. */''')
patch(rw, '''	if (milliseconds >= 1000 && !gGPUReported) {
		gGPUReported = true;
		redwood_gpu_report("no answer");
	}
	return false;''', '''	if (milliseconds >= 1000 && !gGPUReported) {
		gpuHung("no answer");
	}
	return false;''')
patch(rw, '''	request->fence = redwood_gpu_submit(addresses, words, count);
''', '''	request->fence = redwood_gpu_submit(addresses, words, count);
	if (request->fence == 0 && !gGPUReported) {
		gpuHung("the ring is full");
		if (!gGPUReported) {
			request->fence = redwood_gpu_submit(addresses, words, count);   /* once more, on the reset GPU */
		}
	}
''')
patch(rw, '''	if (request->fence == 0 && !gGPUReported) {
		gGPUReported = true;
		redwood_gpu_report("the ring is full");
	}
''', '')
print('ok')
