"""lavender: pending reads are completed "aborted" at close and at a baseband reset (patch 1079), T4.

"Failed to engage router" after every baseband reset (runs e74-e78): libPCITransport keeps one
live transport object per interface; a new one for qmux1/qmux2 waits up to 5 s for the old one to
go away, then gives up before any kernel call. The old one never goes: each asynchronous read it
started holds a reference that is released only when the kernel completes that read. The stand-in
dropped pending reads at close without completing them.

Now every pending read is completed with kIOReturnAborted (0xE00002EB, what libPCITransport itself
marks them with) when the client closes the pipe, and on every interface when the baseband goes
"off" at a reset.

usage: python mk_abp10.py XNU_TREE   (after mk_abp9.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	for (;;) {
		IOLockLock(lv_abp_lock);
		IOMemoryDescriptor *md = NULL;
		if (fRdCount != 0) {
			md = fRd[fRdHead].md;
			fRd[fRdHead].md = NULL;
			fRdHead = (fRdHead + 1) % LV_ABP_QMAX;
			fRdCount--;
		}
		IOLockUnlock(lv_abp_lock);
		if (md == NULL) {
			break;
		}
		md->complete();
		md->release();
	}
''', '''	unsigned aborted = 0;
	for (;;) {
		IOLockLock(lv_abp_lock);
		IOMemoryDescriptor *md = NULL;
		OSAsyncReference64 ref;
		bool have = fRdCount != 0;
		if (have) {
			md = fRd[fRdHead].md;
			bcopy(fRd[fRdHead].ref, ref, sizeof(ref));
			fRd[fRdHead].md = NULL;
			fRdHead = (fRdHead + 1) % LV_ABP_QMAX;
			fRdCount--;
		}
		IOLockUnlock(lv_abp_lock);
		if (!have) {
			break;
		}
		if (md != NULL) {
			md->complete();
			md->release();
		}
		/* the client's transport lives until each of its reads is completed (mk_abp10.py) */
		uint64_t zero = 0;
		(void)lv_abp_async_done(ref, (IOReturn)0xE00002EB, &zero, 1);
		aborted++;
	}
	if (aborted != 0) {
		IOLog("LV ABP %s: %u pending read(s) completed as aborted\\n", fName, aborted);
	}
''')
sub('''	if (stage == LV_ABP_OFF) {
		lv_qmux_reset();
	}
''', '''	if (stage == LV_ABP_OFF) {
		lv_qmux_reset();
		for (unsigned i = 0; i < LV_ABP_NIF; i++) {     /* the old transports must be able to go (mk_abp10.py) */
			if (lv_abp_if[i] != NULL) {
				lv_abp_if[i]->dropRead();
			}
		}
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
