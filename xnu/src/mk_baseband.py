'''lavender: a built-in AppleBaseband service, so that CommCenter gets its baseband controller (patch 1038).

With AppleIPAppender there (1036) CommCenter still died of an uncaught exception: the stack scan
(1037) showed the unwind going through the function that calls TelephonyBasebandCreateController()
(libTelephonyBasebandDynamic). That waits for an IOService "AppleBaseband" (matching notification,
then a timeout: "Timeout for waiting for the driver", "Unable to communicate with AppleBaseband
driver") and throws. On an iPhone AppleBaseband is the modem's power/reset/state driver. lavender's
modem is not driven yet, so this service only exists: every call is accepted and answered with
zeroes, each selector logged once ("LV BB: ..."). The modem never comes up; what CommCenter does
then is the next thing to look at.

usage: python mk_baseband.py XNU_TREE   (after mk_ipappender.py)
'''
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''class AppleIPAppenderUserClient : public IOUserClient {''', '''/* lavender: AppleBaseband (xnu/src/mk_baseband.py) - CommCenter's baseband controller opens it; no modem behind it yet */
class AppleBaseband : public IOService {
	OSDeclareDefaultStructors(AppleBaseband);

public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(AppleBaseband, IOService);

bool
AppleBaseband::start(IOService *provider)
{
	if (!IOService::start(provider)) {
		return false;
	}
	setProperty(kIOUserClientClassKey, "AppleIPAppenderUserClient");
	registerService();
	IOLog("LV BB: AppleBaseband registered (accepts calls, no modem behind it)\\n");
	return true;
}

class AppleIPAppenderUserClient : public IOUserClient {''')
sub('''static uint64_t lv_pdp_logged;          /* selectors already logged (< 64) */
''', '''static uint64_t lv_pdp_logged;          /* selectors already logged (< 64) */
static uint64_t lv_bb_logged;           /* ... of AppleBaseband */
''')
sub('''	if (selector >= 64 || !(lv_pdp_logged & (1ULL << selector))) {
		if (selector < 64) {
			lv_pdp_logged |= 1ULL << selector;
		}
		char name[32];
		proc_selfname(name, sizeof(name));
		IOLog("LV PDP: %s sel''', '''	bool bb = OSDynamicCast(AppleBaseband, getProvider()) != NULL;
	uint64_t *logged = bb ? &lv_bb_logged : &lv_pdp_logged;
	if (selector >= 64 || !(*logged & (1ULL << selector))) {
		if (selector < 64) {
			*logged |= 1ULL << selector;
		}
		char name[32];
		proc_selfname(name, sizeof(name));
		IOLog("LV %s: %s sel''')
sub('''-> ok\\n", name, selector,
		    args->scalarInputCount, args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize);
	}
	return kIOReturnSuccess;
}

bool
IOWatchdog::start''', '''-> ok\\n", bb ? "BB" : "PDP", name, selector,
		    args->scalarInputCount, args->structureInputSize,
		    args->scalarOutputCount, args->structureOutputSize);
	}
	return kIOReturnSuccess;
}

bool
IOWatchdog::start''')
sub('''		pdp->release();
	}
''', '''		pdp->release();
	}
	AppleBaseband *bb = OSTypeAlloc(AppleBaseband);
	if (bb != NULL) {
		if (!bb->init() || !bb->attach(provider) || !bb->start(provider)) {
			IOLog("LV BB: AppleBaseband did not start\\n");
		}
		bb->release();
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
