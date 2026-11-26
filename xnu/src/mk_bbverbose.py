"""lavender: the AppleBaseband / AppleIPAppender stubs log every call when abp=1 (patch 1059).

They logged each selector once; to follow the baseband manager's start (SetManagerState 0 then 1,
PowerOnModem, ...: docs/ABP-ABI.md) every call is needed, with its scalar inputs. With abp=1 the
first 300 calls of each service are logged in full; the method names of AppleBaseband are added.

usage: python mk_bbverbose.py XNU_TREE   (after mk_abp.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	bool bb = OSDynamicCast(AppleBaseband, getProvider()) != NULL;
	uint64_t *logged = bb ? &lv_bb_logged : &lv_pdp_logged;
	if (selector >= 64 || !(*logged & (1ULL << selector))) {''', '''	bool bb = OSDynamicCast(AppleBaseband, getProvider()) != NULL;
	uint64_t *logged = bb ? &lv_bb_logged : &lv_pdp_logged;
	static int verbose = -1;
	static unsigned calls[2];
	if (verbose < 0) {
		uint32_t abp = 0;
		verbose = PE_parse_boot_argn("abp", &abp, sizeof(abp)) && abp != 0;
	}
	if (verbose > 0 && calls[bb]++ < 300) {
		static const char *const bbn[] = {
			"ResetModem", "PowerOnModem", "EnableModemMux", "GetReset", "4", "5", "PowercycleModem", "7", "EnableModemVBUS", "9",
			"VoteDeviceWake", "GetPMUExtOn", "12", "13", "14", "Identify", "GetDiagReady", "GetFSEraseDone", "GetResetReq",
			"SetModemCoredumpGPIO", "APTimeSync", "21", "SetManagerState", "GetManagerState", "24", "SetChargerDesense",
			"GetBasebandState", "SetBasebandState", "GetBasebandProperty", "SetBasebandProperty", "ReportThermalData",
			"DebugCommand", "ClearFreqList", "AddFreqList", "RemoveFreqList", "ResetSPMI",
		};
		char who[32], text[40];
		proc_selfname(who, sizeof(who));
		text[0] = 0;
		if (bb && selector == 15 && args->structureInput != NULL && args->structureInputSize > 0) {
			const char *src = (const char *)args->structureInput;
			size_t n = 0;
			while (n < sizeof(text) - 1 && n < args->structureInputSize && src[n] != 0) {
				text[n] = src[n];
				n++;
			}
			text[n] = 0;
		}
		IOLog("LV %s: %s %s(%u) in %u [%llx %llx] struct %u out %u/%u %s\\n", bb ? "BB" : "PDP", who,
		    bb && selector < sizeof(bbn) / sizeof(bbn[0]) ? bbn[selector] : "sel", selector, args->scalarInputCount,
		    args->scalarInputCount > 0 ? args->scalarInput[0] : 0, args->scalarInputCount > 1 ? args->scalarInput[1] : 0,
		    args->structureInputSize, args->scalarOutputCount, args->structureOutputSize, text);
	} else if (selector >= 64 || !(*logged & (1ULL << selector))) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
