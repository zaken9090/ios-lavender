"""lavender: an interface keeps several pending reads (patch 1070), telephony T4.

Run e70: the boot went through - after the Sahara transfer the manager opened qmux1 and qmux2,
the QMUX bridge answered CTL (sync, data format, client ids for uim, dms, nas, wds, ...) and QMI
started to flow to the modem. Then: "pci error: 0. failed on I/O 0xe00002d5". The transport
queues several asynchronous reads on a pipe (four of 0x1800 bytes each); the interface had room
for one and answered the others "busy". Now up to 16 reads wait in order; data completes the
oldest.

usage: python mk_abp8.py XNU_TREE   (after mk_abp7.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	bool fReadPending;
	OSAsyncReference64 fReadRef;
	IOMemoryDescriptor *fReadMD;
	uint32_t fReadMax;
''', '''	struct { OSAsyncReference64 ref; IOMemoryDescriptor *md; uint32_t max; } fRd[LV_ABP_QMAX];
	unsigned fRdHead, fRdCount;
''')
sub('''	if (fReadPending && fReadMD != NULL) {
		uint64_t n = len < fReadMax ? len : fReadMax;
		OSAsyncReference64 ref;
		IOMemoryDescriptor *md = fReadMD;
		bcopy(fReadRef, ref, sizeof(ref));
		fReadPending = false;
		fReadMD = NULL;
		IOLockUnlock(lv_abp_lock);
''', '''	if (fRdCount != 0) {
		uint64_t n = len < fRd[fRdHead].max ? len : fRd[fRdHead].max;
		OSAsyncReference64 ref;
		IOMemoryDescriptor *md = fRd[fRdHead].md;
		bcopy(fRd[fRdHead].ref, ref, sizeof(ref));
		fRd[fRdHead].md = NULL;
		fRdHead = (fRdHead + 1) % LV_ABP_QMAX;
		fRdCount--;
		IOLockUnlock(lv_abp_lock);
''')
sub('''		IOLog("LV ABP %s: read completed, %llu bytes (%#x)\\n", fName, n, r);
		return;
''', '''		if (fRxLogged++ < 24 || r != kIOReturnSuccess) {
			IOLog("LV ABP %s: read completed, %llu bytes (%#x)\\n", fName, n, r);
		}
		return;
''')
sub('''	unsigned fQHead, fQCount;
''', '''	unsigned fQHead, fQCount, fRxLogged;
''')
sub('''	IOLockLock(lv_abp_lock);
	IOMemoryDescriptor *md = fReadPending ? fReadMD : NULL;
	fReadPending = false;
	fReadMD = NULL;
	IOLockUnlock(lv_abp_lock);
	if (md != NULL) {
		md->complete();
		md->release();
	}
''', '''	for (;;) {
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
''')
sub('''					if (ok && !fItf->fReadPending) {
						bzero(fItf->fReadRef, sizeof(fItf->fReadRef));
						for (uint32_t i = 0; i < args->asyncReferenceCount && i < kOSAsyncRef64Count; i++) {
							fItf->fReadRef[i] = args->asyncReference[i];
						}
						fItf->fReadMD = md;
						fItf->fReadMax = (uint32_t)in[1];
						fItf->fReadPending = true;
						IOLockUnlock(lv_abp_lock);
''', '''					if (ok && fItf->fRdCount < LV_ABP_QMAX) {
						unsigned at = (fItf->fRdHead + fItf->fRdCount) % LV_ABP_QMAX;
						bzero(fItf->fRd[at].ref, sizeof(fItf->fRd[at].ref));
						for (uint32_t i = 0; i < args->asyncReferenceCount && i < kOSAsyncRef64Count; i++) {
							fItf->fRd[at].ref[i] = args->asyncReference[i];
						}
						fItf->fRd[at].md = md;
						fItf->fRd[at].max = (uint32_t)in[1];
						fItf->fRdCount++;
						IOLockUnlock(lv_abp_lock);
''')
# the per-call log is long once QMI flows: keep the first calls of each client, then only failures
sub('''	if (fCalls++ < 600) {''', '''	if (fCalls++ < 40 || ret != kIOReturnSuccess) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
