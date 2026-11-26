"""lavender: the baseband PCI services play the modem's boot stages (patch 1063), telephony T3.

Run e64 (firmware folder in place): the manager calls PowerOnModem(1), opens an interface, reads
the boot registers 4, 3, 0 (OEMPkHash 96 bytes, MSMHwId 24, SerialNum 4), gets zeroes
("ChipID = 0"; the firmware's Info.plist says ChipId 0x0003B0E1), fails "output did not return
done" and power-cycles in a loop. It also got the wrong interface: a matching dictionary with
ABPInterfaceProtocol matched any AppleBasebandPCIInterface (it opened "qdss" for "pbl").

Now, with abp=1:
- AppleBasebandPCIInterface::matchPropertyTable() compares ABPInterfaceProtocol.
- A small state machine stands in for the modem's boot (the real modem is already running, booted
  by TopazModem; Apple's updater has no "already booted" path):
    off      nothing published
    rom      after PowerOnModem(1) / PowercycleModem / ResetModem: interface "pbl"; registers:
             MSMHwId[0] = abp_chip (default 0x0003B0E1), SerialNum = abp_serial (default 1)
    sahara   after an image was sent on "pbl": interface "sahara"; the device's Sahara HELLO is
             queued; HELLO_RESP is answered END_IMAGE_TX (success), DONE is answered DONE_RESP
    mission  after DONE: interfaces abp_ifs (default 0xfe3c: diag refs qmux1 qmux2 ...), and the
             "baseband alive" message 0xE3FF8001 on AppleBaseband
  abp_hold=N stops the machine at stage N (1 rom, 2 sahara) to look at what the updater does.
- Interfaces have a receive queue and one pending asynchronous read (the caller's buffer is
  wired at the call, filled and completed when data comes). Writes are logged and completed.
Everything is logged ("LV ABP ...").

usage: python mk_abp2.py XNU_TREE   (after mk_bbverbose.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


def cut(start, end, new):
    """replace from start up to (not including) end"""
    global s
    assert s.count(start) == 1 and s.count(end) == 1, (start[:50], s.count(start), end[:50], s.count(end))
    a, b = s.index(start), s.index(end)
    assert a < b
    s = s[:a] + new + s[b:]


sub('''#include <pexpert/pexpert.h>
''', '''#include <pexpert/pexpert.h>
#include <IOKit/IOLocks.h>
#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

/* lavender (xnu/src/mk_abp2.py): AppleBaseband power calls drive the baseband PCI stand-in below */
static void lv_abp_power(uint32_t selector, uint64_t arg);
''')
sub('''	if (verbose > 0 && calls[bb]++ < 300) {''', '''	if (verbose > 0 && bb && (selector == 0 || selector == 1 || selector == 6)) {
		lv_abp_power(selector, args->scalarInputCount > 0 ? args->scalarInput[0] : 0);
	}
	if (verbose > 0 && calls[bb]++ < 300) {''')

cut('''/*
 * lavender: Apple's baseband PCI services, step T2 (xnu/src/mk_abp.py, docs/ABP-ABI.md).
 */''', '''bool
IOWatchdog::start(IOService *provider)
{
''', r'''/*
 * lavender: Apple's baseband PCI services (xnu/src/mk_abp.py, mk_abp2.py; docs/ABP-ABI.md).
 */
#define LV_ABP_NIF      21
#define LV_ABP_QMAX     16
static const char *const lv_abp_names[LV_ABP_NIF] = {
	"pbl", "sahara", "diag", "refs", "qmux1", "qmux2", "rom", "boot", "ari", "trace", "at", "dpl", "mediactl", "vcom",
	"gnss", "qdss", NULL, "virtual_timesync", NULL, NULL, "boot_logger",
};
enum { LV_ABP_OFF = 0, LV_ABP_ROM = 1, LV_ABP_SAHARA = 2, LV_ABP_MISSION = 3 };

class AppleBasebandPCIControl : public IOService {
	OSDeclareDefaultStructors(AppleBasebandPCIControl);

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(AppleBasebandPCIControl, IOService);

bool
AppleBasebandPCIControl::start(IOService *provider)
{
	if (!IOService::start(provider)) {
		return false;
	}
	setProperty("bootstage", 0ULL, 32);
	setProperty("logSnapshotBufferSize", 0x1000ULL, 32);
	setProperty(kIOUserClientClassKey, "SweetABPUserClient");
	registerService();
	IOLog("LV ABP: AppleBasebandPCIControl registered\n");
	return true;
}

class AppleBasebandPCIInterface : public IOService {
	OSDeclareDefaultStructors(AppleBasebandPCIInterface);

public:
	const char *fName;
	unsigned fIndex;
	/* receive side: data for the client, and its one pending asynchronous read */
	struct { uint8_t *data; uint32_t len; } fQ[LV_ABP_QMAX];
	unsigned fQHead, fQCount;
	bool fReadPending;
	OSAsyncReference64 fReadRef;
	IOMemoryDescriptor *fReadMD;
	uint32_t fReadMax;

	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	bool matchPropertyTable(OSDictionary *table, SInt32 *score) APPLE_KEXT_OVERRIDE;
	void rx(const void *data, uint32_t len);
	void dropRead(void);
};

OSDefineMetaClassAndStructors(AppleBasebandPCIInterface, IOService);

static IOLock *lv_abp_lock;
static IOService *lv_abp_provider, *lv_abp_bb;
static AppleBasebandPCIControl *lv_abp_ctl;
static AppleBasebandPCIInterface *lv_abp_if[LV_ABP_NIF];
static uint32_t lv_abp_stage, lv_abp_hold, lv_abp_ifs = 0xfe3c, lv_abp_chip = 0x0003B0E1, lv_abp_serial = 1;

bool
AppleBasebandPCIInterface::start(IOService *provider)
{
	if (!IOService::start(provider)) {
		return false;
	}
	setProperty("ABPInterfaceProtocol", fName);
	setProperty(kIOUserClientClassKey, "SweetABPUserClient");
	registerService();
	return true;
}

/* libIOABP matches IOServiceMatching("AppleBasebandPCIInterface") + ABPInterfaceProtocol = name */
bool
AppleBasebandPCIInterface::matchPropertyTable(OSDictionary *table, SInt32 *score)
{
	if (!IOService::matchPropertyTable(table, score)) {
		return false;
	}
	OSString *want = OSDynamicCast(OSString, table->getObject("ABPInterfaceProtocol"));
	return want == NULL || want->isEqualTo(fName);
}

/* data from the "modem" to the client: completes the pending read or waits in the queue */
void
AppleBasebandPCIInterface::rx(const void *data, uint32_t len)
{
	IOLockLock(lv_abp_lock);
	if (fReadPending && fReadMD != NULL) {
		uint64_t n = len < fReadMax ? len : fReadMax;
		OSAsyncReference64 ref;
		IOMemoryDescriptor *md = fReadMD;
		bcopy(fReadRef, ref, sizeof(ref));
		fReadPending = false;
		fReadMD = NULL;
		IOLockUnlock(lv_abp_lock);
		md->writeBytes(0, data, (IOByteCount)n);
		md->complete();
		md->release();
		IOReturn r = IOUserClient::sendAsyncResult64(ref, kIOReturnSuccess, &n, 1);
		IOLog("LV ABP %s: read completed, %llu bytes (%#x)\n", fName, n, r);
		return;
	}
	if (fQCount < LV_ABP_QMAX) {
		uint8_t *copy = (uint8_t *)IOMallocData(len != 0 ? len : 1);
		if (copy != NULL) {
			bcopy(data, copy, len);
			unsigned at = (fQHead + fQCount) % LV_ABP_QMAX;
			fQ[at].data = copy;
			fQ[at].len = len;
			fQCount++;
		}
	} else {
		IOLog("LV ABP %s: receive queue full, %u bytes dropped\n", fName, len);
	}
	IOLockUnlock(lv_abp_lock);
}

void
AppleBasebandPCIInterface::dropRead(void)
{
	IOLockLock(lv_abp_lock);
	IOMemoryDescriptor *md = fReadPending ? fReadMD : NULL;
	fReadPending = false;
	fReadMD = NULL;
	IOLockUnlock(lv_abp_lock);
	if (md != NULL) {
		md->complete();
		md->release();
	}
}

static void
lv_abp_publish(unsigned i)
{
	if (i >= LV_ABP_NIF || lv_abp_names[i] == NULL || lv_abp_if[i] != NULL || lv_abp_provider == NULL) {
		return;
	}
	AppleBasebandPCIInterface *itf = OSTypeAlloc(AppleBasebandPCIInterface);
	if (itf == NULL) {
		return;
	}
	if (!itf->init()) {
		itf->release();
		return;
	}
	itf->fName = lv_abp_names[i];
	itf->fIndex = i;
	if (!itf->attach(lv_abp_provider) || !itf->start(lv_abp_provider)) {
		IOLog("LV ABP: interface %s did not start\n", lv_abp_names[i]);
		itf->release();
		return;
	}
	lv_abp_if[i] = itf;
}

static void
lv_abp_unpublish(unsigned i)
{
	AppleBasebandPCIInterface *itf = i < LV_ABP_NIF ? lv_abp_if[i] : NULL;
	if (itf == NULL) {
		return;
	}
	lv_abp_if[i] = NULL;
	itf->dropRead();
	itf->terminate(kIOServiceRequired);
	itf->release();
}

static void
lv_abp_set_stage(uint32_t stage)
{
	static const char *const names[] = { "off", "rom (pbl)", "sahara", "mission" };
	uint32_t want = stage == LV_ABP_ROM ? 1u << 0 : stage == LV_ABP_SAHARA ? 1u << 1 : stage == LV_ABP_MISSION ? lv_abp_ifs : 0;

	IOLog("LV ABP: stage %s -> %s\n", names[lv_abp_stage & 3], names[stage & 3]);
	lv_abp_stage = stage;
	for (unsigned i = 0; i < LV_ABP_NIF; i++) {
		if (!(want & (1u << i))) {
			lv_abp_unpublish(i);
		}
	}
	if (lv_abp_ctl != NULL) {
		lv_abp_ctl->setProperty("bootstage", stage == LV_ABP_MISSION ? 2ULL : stage == LV_ABP_OFF ? 0ULL : 1ULL, 32);
	}
	for (unsigned i = 0; i < LV_ABP_NIF; i++) {
		if (want & (1u << i)) {
			lv_abp_publish(i);
		}
	}
	if (stage == LV_ABP_SAHARA && lv_abp_if[1] != NULL) {
		/* the device speaks first: Sahara HELLO, version 2, image transfer pending */
		uint32_t hello[12] = { 1, 0x30, 2, 1, 0x400, 0, 0, 0, 0, 0, 0, 0 };
		lv_abp_if[1]->rx(hello, sizeof(hello));
	}
	if (stage == LV_ABP_MISSION && lv_abp_bb != NULL) {
		IOReturn r = lv_abp_bb->messageClients(0xE3FF8001, NULL, 0);
		IOLog("LV ABP: 'baseband alive' sent (%#x)\n", r);
	}
}

/* AppleBaseband: ResetModem (0), PowerOnModem (1, arg 1 = on), PowercycleModem (6) */
static void
lv_abp_power(uint32_t selector, uint64_t arg)
{
	if (lv_abp_provider == NULL) {
		return;
	}
	if (selector == 1 && arg == 0) {
		lv_abp_set_stage(LV_ABP_OFF);
	} else if (selector == 1 && lv_abp_stage != LV_ABP_OFF) {
		IOLog("LV ABP: PowerOnModem while already on (stage %u): nothing to do\n", lv_abp_stage);
	} else {
		if (lv_abp_stage != LV_ABP_OFF) {
			lv_abp_set_stage(LV_ABP_OFF);
		}
		lv_abp_set_stage(LV_ABP_ROM);
	}
}

class SweetABPUserClient : public IOUserClient {
	OSDeclareDefaultStructors(SweetABPUserClient);

	AppleBasebandPCIInterface *fItf;
	const char *fWho;
	unsigned fCalls;

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target,
	    void *reference) APPLE_KEXT_OVERRIDE;
	void modemSide(const uint8_t *data, uint32_t len);
};

OSDefineMetaClassAndStructors(SweetABPUserClient, IOUserClient);

bool
SweetABPUserClient::start(IOService *provider)
{
	fItf = OSDynamicCast(AppleBasebandPCIInterface, provider);
	fWho = fItf != NULL ? fItf->fName : "control";
	fCalls = 0;
	char name[32];
	proc_selfname(name, sizeof(name));
	IOLog("LV ABP %s: opened by %s\n", fWho, name);
	return IOUserClient::start(provider);
}

IOReturn
SweetABPUserClient::clientClose(void)
{
	IOLog("LV ABP %s: closed\n", fWho);
	if (fItf != NULL) {
		fItf->dropRead();
	}
	terminate();
	return kIOReturnSuccess;
}

/* the first bytes of a buffer, as hex; copy is filled with up to copymax bytes of it */
static uint32_t
lv_abp_fetch(char *out, size_t outsz, uint64_t va, uint64_t len, const void *kbuf, uint8_t *copy, uint32_t copymax)
{
	uint32_t n = len < copymax ? (uint32_t)len : copymax, got = 0;
	out[0] = 0;
	if (kbuf != NULL) {
		bcopy(kbuf, copy, n);
		got = n;
	} else if (va != 0 && n != 0) {
		IOMemoryDescriptor *md = IOMemoryDescriptor::withAddressRange(va, n, kIODirectionOut, current_task());
		if (md != NULL) {
			if (md->prepare() == kIOReturnSuccess) {
				got = (uint32_t)md->readBytes(0, copy, n);
				md->complete();
			}
			md->release();
		}
	}
	for (uint32_t i = 0; i < got && i < 40 && 3 * i + 4 < outsz; i++) {
		snprintf(out + 3 * i, 4, "%02x ", copy[i]);
	}
	return got;
}

/* what the "modem" does with data the client wrote */
void
SweetABPUserClient::modemSide(const uint8_t *data, uint32_t len)
{
	if (fItf == NULL || fItf->fIndex != 1 || len < 8) {
		return;                                 /* only the Sahara endpoint answers so far */
	}
	uint32_t cmd, w[4] = { 0, 0, 0, 0 };
	memcpy(&cmd, data, 4);
	switch (cmd) {
	case 2: {                                       /* HELLO_RESP: nothing to fetch, end of image transfer */
		uint32_t mode = 0;
		if (len >= 24) {
			memcpy(&mode, data + 20, 4);
		}
		IOLog("LV ABP sahara: HELLO_RESP (mode %u) -> END_IMAGE_TX\n", mode);
		w[0] = 4; w[1] = 16; w[2] = 0; w[3] = 0;
		fItf->rx(w, 16);
		break;
	}
	case 5:                                         /* DONE -> DONE_RESP, image transfer complete */
		IOLog("LV ABP sahara: DONE -> DONE_RESP\n");
		w[0] = 6; w[1] = 12; w[2] = 1;
		fItf->rx(w, 12);
		if (lv_abp_hold == 0 || lv_abp_hold > LV_ABP_SAHARA) {
			lv_abp_set_stage(LV_ABP_MISSION);
		}
		break;
	default:
		IOLog("LV ABP sahara: command %u (%u bytes) not answered\n", cmd, len);
		break;
	}
}

IOReturn
SweetABPUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    __unused IOExternalMethodDispatch *dispatch, __unused OSObject *target,
    __unused void *reference)
{
	bool async = args->asyncWakePort != MACH_PORT_NULL;
	uint64_t in[4] = { 0, 0, 0, 0 };
	char name[32], hex[128];
	uint8_t buf[512];
	uint32_t got = 0;
	const char *what = "?";
	uint64_t done[2] = { 0, 0 };
	int complete = -1;                              /* number of completion arguments, -1: stays pending */
	IOReturn ret = kIOReturnSuccess;
	bool next_sahara = false;

	for (uint32_t i = 0; i < args->scalarInputCount && i < 4; i++) {
		in[i] = args->scalarInput[i];
	}
	for (uint32_t i = 0; i < args->scalarOutputCount; i++) {
		args->scalarOutput[i] = 0;
	}
	hex[0] = 0;
	proc_selfname(name, sizeof(name));
	if (fItf == NULL) {
		static const char *const cn[] = { "open", "close", "readLogs", "loggerTune" };
		what = selector < 4 ? cn[selector] : "?";
	} else {
		switch (selector) {
		case 0: what = "open"; break;
		case 1: what = "close"; fItf->dropRead(); break;
		case 2:
			what = "write";
			if (async) {
				got = lv_abp_fetch(hex, sizeof(hex), in[0], in[1], NULL, buf, sizeof(buf));
				done[0] = in[1];
				complete = 1;
			} else if (args->structureInput != NULL) {
				got = lv_abp_fetch(hex, sizeof(hex), 0, args->structureInputSize, args->structureInput, buf, sizeof(buf));
			} else if (args->structureInputDescriptor != NULL) {
				got = (uint32_t)args->structureInputDescriptor->readBytes(0, buf, MIN(sizeof(buf),
				    (size_t)args->structureInputDescriptor->getLength()));
				snprintf(hex, sizeof(hex), "(%llu bytes by descriptor)", (uint64_t)args->structureInputDescriptor->getLength());
			}
			break;
		case 3:
			what = "read";
			if (async) {
				IOLockLock(lv_abp_lock);
				if (fItf->fQCount != 0) {
					uint8_t *d = fItf->fQ[fItf->fQHead].data;
					uint32_t n = fItf->fQ[fItf->fQHead].len;
					fItf->fQHead = (fItf->fQHead + 1) % LV_ABP_QMAX;
					fItf->fQCount--;
					IOLockUnlock(lv_abp_lock);
					uint64_t take = n < in[1] ? n : in[1];
					IOMemoryDescriptor *md = IOMemoryDescriptor::withAddressRange(in[0], take, kIODirectionIn, current_task());
					if (md != NULL && md->prepare() == kIOReturnSuccess) {
						md->writeBytes(0, d, (IOByteCount)take);
						md->complete();
					}
					OSSafeReleaseNULL(md);
					IOFreeData(d, n != 0 ? n : 1);
					done[0] = take;
					complete = 1;
				} else {
					IOMemoryDescriptor *md = IOMemoryDescriptor::withAddressRange(in[0], in[1], kIODirectionIn, current_task());
					bool ok = md != NULL && md->prepare() == kIOReturnSuccess;
					if (ok && !fItf->fReadPending) {
						bzero(fItf->fReadRef, sizeof(fItf->fReadRef));
						for (uint32_t i = 0; i < args->asyncReferenceCount && i < kOSAsyncRef64Count; i++) {
							fItf->fReadRef[i] = args->asyncReference[i];
						}
						fItf->fReadMD = md;
						fItf->fReadMax = (uint32_t)in[1];
						fItf->fReadPending = true;
						IOLockUnlock(lv_abp_lock);
					} else {
						IOLockUnlock(lv_abp_lock);
						if (ok) {
							md->complete();
						}
						OSSafeReleaseNULL(md);
						ret = kIOReturnBusy;
					}
				}
			} else {
				args->structureOutputSize = 0;
			}
			break;
		case 4:
			what = "sendImage";
			complete = 2;
			if (!async && args->scalarOutputCount >= 2) {
				args->scalarOutput[0] = 0;
				args->scalarOutput[1] = 0;
			}
			next_sahara = fItf->fIndex == 0;
			break;
		case 5: {
			/* BHI registers: 0 SerialNum (4 bytes), 3 MSMHwId (24), 4 OEMPkHash (96) */
			uint32_t reg[24];
			bzero(reg, sizeof(reg));
			what = "readRegister";
			if (in[0] == 0) {
				reg[0] = lv_abp_serial;
			} else if (in[0] == 3) {
				reg[0] = lv_abp_chip;
			}
			uint32_t n = MIN((uint32_t)sizeof(reg), args->structureOutputSize);
			if (args->structureOutputDescriptor != NULL) {
				args->structureOutputDescriptor->writeBytes(0, reg, MIN((IOByteCount)sizeof(reg),
				    args->structureOutputDescriptor->getLength()));
			} else if (args->structureOutput != NULL) {
				bcopy(reg, args->structureOutput, n);
			}
			break;
		}
		case 6: what = "abortChannel"; complete = 0; break;
		case 7: what = "startChannel"; complete = 0; break;
		case 8: what = "timeSync"; complete = 1; break;
		case 9: what = "mapMemory"; complete = 0; break;
		case 10: what = "unmapMemory"; complete = 0; break;
		case 11: what = "registerTimeEvent"; break;
		case 12: what = "deregisterTimeEvent"; complete = 0; break;
		default: break;
		}
	}
	if (fCalls++ < 600) {
		IOLog("LV ABP %s: %s %s(%u)%s in %u [%llx %llx %llx %llx] struct in %u out %u/%u%s%s -> %#x\n", fWho, name, what, selector,
		    async ? " async" : "", args->scalarInputCount, in[0], in[1], in[2], in[3], args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize, hex[0] ? " data " : "", hex, ret);
	}
	if (async && complete >= 0 && ret == kIOReturnSuccess) {
		OSAsyncReference64 ref;
		bzero(ref, sizeof(ref));
		for (uint32_t i = 0; i < args->asyncReferenceCount && i < kOSAsyncRef64Count; i++) {
			ref[i] = args->asyncReference[i];
		}
		(void)sendAsyncResult64(ref, kIOReturnSuccess, done, (uint32_t)complete);
	}
	if (selector == 2 && got != 0) {
		modemSide(buf, got);
	}
	if (next_sahara && (lv_abp_hold == 0 || lv_abp_hold > LV_ABP_ROM)) {
		lv_abp_set_stage(LV_ABP_SAHARA);
	}
	return ret;
}

''')

cut('''	uint32_t abp = 0, ifs = 0xfe3c;
''', '''	return true;
}

class IOWatchdogUserClient''', r'''	uint32_t abp = 0;
	(void)PE_parse_boot_argn("abp", &abp, sizeof(abp));
	if (abp != 0) {
		(void)PE_parse_boot_argn("abp_ifs", &lv_abp_ifs, sizeof(lv_abp_ifs));
		(void)PE_parse_boot_argn("abp_chip", &lv_abp_chip, sizeof(lv_abp_chip));
		(void)PE_parse_boot_argn("abp_serial", &lv_abp_serial, sizeof(lv_abp_serial));
		(void)PE_parse_boot_argn("abp_hold", &lv_abp_hold, sizeof(lv_abp_hold));
		lv_abp_lock = IOLockAlloc();
		lv_abp_provider = provider;
		lv_abp_bb = bb;
		lv_abp_ctl = OSTypeAlloc(AppleBasebandPCIControl);
		if (lv_abp_ctl != NULL && (!lv_abp_ctl->init() || !lv_abp_ctl->attach(provider) || !lv_abp_ctl->start(provider))) {
			IOLog("LV ABP: AppleBasebandPCIControl did not start\n");
		}
		IOLog("LV ABP: stand-in for the modem's boot stages ready (chip %#x, mission interfaces %#x, hold %u)\n", lv_abp_chip,
		    lv_abp_ifs, lv_abp_hold);
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
