"""lavender: a built-in AppleIPAppender service, so that CommCenter has its PDP helper (patch 1036).

CommCenter (back in launchd.plist since 1035) died again and again with a NULL
ApplePDPHelperInterface: ApplePDPHelper.framework looks up IOServiceMatching("AppleIPAppender"),
opens it with type 0 and asks for general-interest notifications; with no such service
getInstance() returns NULL and CommCenter calls callStructMethod() on it (2026-11-26). On an iPhone
the kext puts headers on packets of the baseband's data interfaces. lavender has no such
interfaces yet, so the service accepts every call, answers zeroes and logs each selector once.
It lives in SweetWatchdog.cpp (already built) and IOWatchdog::start() makes it.

usage: python mk_ipappender.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''bool
IOWatchdog::start(IOService *provider)
{''', '''/*
 * lavender: AppleIPAppender (xnu/src/mk_ipappender.py). CommCenter's ApplePDPHelper opens it;
 * no baseband data interfaces here, so every call is accepted and answered with zeroes.
 */
class AppleIPAppender : public IOService {
	OSDeclareDefaultStructors(AppleIPAppender);

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(AppleIPAppender, IOService);

bool
AppleIPAppender::start(IOService *provider)
{
	if (!IOService::start(provider)) {
		return false;
	}
	setProperty(kIOUserClientClassKey, "AppleIPAppenderUserClient");
	registerService();
	IOLog("LV PDP: AppleIPAppender registered (accepts calls, no data interfaces)\\n");
	return true;
}

class AppleIPAppenderUserClient : public IOUserClient {
	OSDeclareDefaultStructors(AppleIPAppenderUserClient);

public:
	IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args,
	    IOExternalMethodDispatch *dispatch, OSObject *target,
	    void *reference) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(AppleIPAppenderUserClient, IOUserClient);

IOReturn
AppleIPAppenderUserClient::clientClose(void)
{
	terminate();
	return kIOReturnSuccess;
}

static uint64_t lv_pdp_logged;          /* selectors already logged (< 64) */

IOReturn
AppleIPAppenderUserClient::externalMethod(uint32_t selector, IOExternalMethodArguments *args,
    __unused IOExternalMethodDispatch *dispatch, __unused OSObject *target,
    __unused void *reference)
{
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
	if (selector >= 64 || !(lv_pdp_logged & (1ULL << selector))) {
		if (selector < 64) {
			lv_pdp_logged |= 1ULL << selector;
		}
		char name[32];
		proc_selfname(name, sizeof(name));
		IOLog("LV PDP: %s sel %u in %u/%u out %u/%u -> ok\\n", name, selector,
		    args->scalarInputCount, args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize);
	}
	return kIOReturnSuccess;
}

bool
IOWatchdog::start(IOService *provider)
{''')
sub('''	IOLog("SWEET WDT: IOWatchdog registered (accepts check-ins, never fires)\\n");
''', '''	IOLog("SWEET WDT: IOWatchdog registered (accepts check-ins, never fires)\\n");
	/* lavender: CommCenter's PDP helper service next to it (mk_ipappender.py) */
	AppleIPAppender *pdp = OSTypeAlloc(AppleIPAppender);
	if (pdp != NULL) {
		if (!pdp->init() || !pdp->attach(provider) || !pdp->start(provider)) {
			IOLog("LV PDP: AppleIPAppender did not start\\n");
		}
		pdp->release();
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
