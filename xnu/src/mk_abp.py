"""lavender: AppleBasebandPCIControl / AppleBasebandPCIInterface services, step T2: observe (patch 1057).

The Qualcomm iPhone X reaches its modem through Apple's kext AppleBasebandPCI; user space
(libPCITransport -> libIOABP) finds the services by class name and talks to their user clients.
docs/ABP-ABI.md has the interface as read from libIOABP.dylib. This patch publishes the services,
with boot-arg abp=1 only, and a user client that accepts every call and logs it in full - the
first step to putting the phone's own modem behind them (docs/MODEM-PLAN.md, Telephony).

- AppleBasebandPCIControl: properties "bootstage" (abp_stage=N, default 2; libTelephonyBaseband
  calls a value below 2 "down"), "logSnapshotBufferSize".
- AppleBasebandPCIInterface, one per name in abp_ifs=MASK (bit = PCITransportInterface number;
  default 0xfe3c: diag refs qmux1 qmux2 trace at dpl mediactl vcom gnss qdss - no boot-ROM ones),
  string property "ABPInterfaceProtocol".
- User client: open/close ok; writes are logged (first bytes) and completed; reads and time
  events stay pending; channel start/abort, map/unmap complete at once; registers read as zero.
  Log lines "LV ABP <service>: <process> ...".

usage: python mk_abp.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#include <sys/proc.h>
''', '''#include <sys/proc.h>
#include <pexpert/pexpert.h>
''')
sub('''bool
IOWatchdog::start(IOService *provider)
{
''', '''/*
 * lavender: Apple's baseband PCI services, step T2 (xnu/src/mk_abp.py, docs/ABP-ABI.md).
 */
static const char *const lv_abp_names[21] = {
	"pbl", "sahara", "diag", "refs", "qmux1", "qmux2", "rom", "boot", "ari", "trace", "at", "dpl", "mediactl", "vcom",
	"gnss", "qdss", NULL, "virtual_timesync", NULL, NULL, "boot_logger",
};

class AppleBasebandPCIControl : public IOService {
	OSDeclareDefaultStructors(AppleBasebandPCIControl);

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(AppleBasebandPCIControl, IOService);

bool
AppleBasebandPCIControl::start(IOService *provider)
{
	uint32_t stage = 2;
	if (!IOService::start(provider)) {
		return false;
	}
	(void)PE_parse_boot_argn("abp_stage", &stage, sizeof(stage));
	setProperty("bootstage", stage, 32);
	setProperty("logSnapshotBufferSize", 0x1000ULL, 32);
	setProperty(kIOUserClientClassKey, "SweetABPUserClient");
	registerService();
	IOLog("LV ABP: AppleBasebandPCIControl registered, bootstage %u\\n", stage);
	return true;
}

class AppleBasebandPCIInterface : public IOService {
	OSDeclareDefaultStructors(AppleBasebandPCIInterface);

public:
	const char *fName;
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(AppleBasebandPCIInterface, IOService);

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

class SweetABPUserClient : public IOUserClient {
	OSDeclareDefaultStructors(SweetABPUserClient);

	const char *fWho;
	bool fControl;
	unsigned fCalls;

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target,
	    void *reference) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(SweetABPUserClient, IOUserClient);

bool
SweetABPUserClient::start(IOService *provider)
{
	AppleBasebandPCIInterface *i = OSDynamicCast(AppleBasebandPCIInterface, provider);
	fControl = i == NULL;
	fWho = i != NULL ? i->fName : "control";
	fCalls = 0;
	char name[32];
	proc_selfname(name, sizeof(name));
	IOLog("LV ABP %s: opened by %s\\n", fWho, name);
	return IOUserClient::start(provider);
}

IOReturn
SweetABPUserClient::clientClose(void)
{
	IOLog("LV ABP %s: closed\\n", fWho);
	terminate();
	return kIOReturnSuccess;
}

/* the first bytes of a buffer of the calling task, as hex */
static void
lv_abp_hex(char *out, size_t outsz, uint64_t va, uint64_t len, const void *kbuf)
{
	uint8_t b[40];
	size_t n = len < sizeof(b) ? (size_t)len : sizeof(b), got = 0;
	out[0] = 0;
	if (kbuf != NULL) {
		bcopy(kbuf, b, n);
		got = n;
	} else if (va != 0 && n != 0) {
		IOMemoryDescriptor *md = IOMemoryDescriptor::withAddressRange(va, n, kIODirectionOut, current_task());
		if (md != NULL) {
			if (md->prepare() == kIOReturnSuccess) {
				got = md->readBytes(0, b, n);
				md->complete();
			}
			md->release();
		}
	}
	for (size_t i = 0; i < got && 3 * i + 4 < outsz; i++) {
		snprintf(out + 3 * i, 4, "%02x ", b[i]);
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
	const char *what = "";
	uint64_t done[2] = { 0, 0 };
	int complete = -1;                              /* number of completion arguments, -1: stays pending */

	for (uint32_t i = 0; i < args->scalarInputCount && i < 4; i++) {
		in[i] = args->scalarInput[i];
	}
	for (uint32_t i = 0; i < args->scalarOutputCount; i++) {
		args->scalarOutput[i] = 0;
	}
	if (args->structureOutputDescriptor != NULL) {
		IOByteCount len = args->structureOutputDescriptor->getLength();
		for (IOByteCount off = 0; off < len; off += 8) {
			static const uint64_t zero = 0;
			args->structureOutputDescriptor->writeBytes(off, &zero, len - off < 8 ? len - off : 8);
		}
	} else if (args->structureOutput != NULL) {
		bzero(args->structureOutput, args->structureOutputSize);
	}
	hex[0] = 0;
	proc_selfname(name, sizeof(name));
	if (fControl) {
		switch (selector) {
		case 0: what = "open"; break;
		case 1: what = "close"; break;
		case 2: what = "readLogs"; break;
		case 3: what = "loggerTune"; break;
		default: what = "?"; break;
		}
	} else {
		switch (selector) {
		case 0: what = "open"; break;
		case 1: what = "close"; break;
		case 2:
			what = "write";
			if (async) {
				lv_abp_hex(hex, sizeof(hex), in[0], in[1], NULL);
				done[0] = in[1];
				complete = 1;
			} else if (args->structureInput != NULL) {
				lv_abp_hex(hex, sizeof(hex), 0, args->structureInputSize, args->structureInput);
			}
			break;
		case 3:
			what = "read";
			if (!async) {
				args->structureOutputSize = 0;
			}
			break;
		case 4: what = "sendImage"; complete = 2; break;
		case 5: what = "readRegister"; break;
		case 6: what = "abortChannel"; complete = 0; break;
		case 7: what = "startChannel"; complete = 0; break;
		case 8: what = "timeSync"; complete = 1; break;
		case 9: what = "mapMemory"; complete = 0; break;
		case 10: what = "unmapMemory"; complete = 0; break;
		case 11: what = "registerTimeEvent"; break;
		case 12: what = "deregisterTimeEvent"; complete = 0; break;
		default: what = "?"; break;
		}
	}
	if (fCalls++ < 400) {
		IOLog("LV ABP %s: %s %s(%u)%s in %u [%llx %llx %llx %llx] struct in %u out %u/%u%s%s\\n", fWho, name, what, selector,
		    async ? " async" : "", args->scalarInputCount, in[0], in[1], in[2], in[3], args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize, hex[0] ? " data " : "", hex);
	}
	if (async && complete >= 0) {
		OSAsyncReference64 ref;
		bzero(ref, sizeof(ref));
		for (uint32_t i = 0; i < args->asyncReferenceCount && i < kOSAsyncRef64Count; i++) {
			ref[i] = args->asyncReference[i];
		}
		(void)sendAsyncResult64(ref, kIOReturnSuccess, done, (uint32_t)complete);
	}
	return kIOReturnSuccess;
}

bool
IOWatchdog::start(IOService *provider)
{
''')
sub('''		bb->release();
	}
	return true;
}
''', '''		bb->release();
	}
	uint32_t abp = 0, ifs = 0xfe3c;
	(void)PE_parse_boot_argn("abp", &abp, sizeof(abp));
	(void)PE_parse_boot_argn("abp_ifs", &ifs, sizeof(ifs));
	if (abp != 0) {
		AppleBasebandPCIControl *ctl = OSTypeAlloc(AppleBasebandPCIControl);
		if (ctl != NULL) {
			if (!ctl->init() || !ctl->attach(provider) || !ctl->start(provider)) {
				IOLog("LV ABP: AppleBasebandPCIControl did not start\\n");
			}
			ctl->release();
		}
		for (unsigned i = 0; i < 21; i++) {
			if (lv_abp_names[i] == NULL || !(ifs & (1u << i))) {
				continue;
			}
			AppleBasebandPCIInterface *itf = OSTypeAlloc(AppleBasebandPCIInterface);
			if (itf != NULL) {
				itf->fName = lv_abp_names[i];
				if (!itf->init() || !itf->attach(provider) || !itf->start(provider)) {
					IOLog("LV ABP: interface %s did not start\\n", lv_abp_names[i]);
				}
				itf->release();
			}
		}
		IOLog("LV ABP: interfaces %#x registered\\n", ifs);
	}
	return true;
}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
