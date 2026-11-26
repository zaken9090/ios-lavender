"""lavender: an AppleOLYHAL service with the Wi-Fi module vendor (patch 1096).

Run e104 (xnu 1095): bluetoothd asks BlueTool for "boot"; BlueTool finds the platform
(fd079b29...) but MobileGestalt's WifiVendor takes 5 s and gives nothing ("Manufacturer is -1",
vendor ALL), so no firmware entry matches (D22 entries are vendor MUR / USI) and it loops
"No WiFi - Iteration N" without ever opening the UART.

libMobileGestalt (static analysis): WifiVendor = IORegistryEntrySearchCFProperty(<first service
of class AppleOLYHAL>, "IOService", "vendor-id", recursive|parents) as a string, waiting 5 s for
the service. On an iPhone the Broadcom Wi-Fi kext sets it from the module's OTP. BlueTool accepts
"Murata" -> MUR (the D22 entry BCM4357B1 ..._Hercules_OS_MUR).

Now a minimal AppleOLYHAL (no hardware, only the property) is registered under the platform
expert when the Bluetooth thread starts, with vendor-id "Murata". It only picks BlueTool's D22
boot script; that script's Broadcom commands are answered by the kernel (mk_bt11.py).

usage: python mk_bt12.py XNU_TREE   (after mk_bt11.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''extern "C" void
lv_bt_start(void)
{''', '''/* the Wi-Fi module's vendor as MobileGestalt reads it (WifiVendor) */
class AppleOLYHAL : public IOService
{
	OSDeclareDefaultStructors(AppleOLYHAL);
};
OSDefineMetaClassAndStructors(AppleOLYHAL, IOService);

static void
bt_olyhal(void)
{
	AppleOLYHAL *h = OSTypeAlloc(AppleOLYHAL);
	IOService *pe = IOService::getPlatform();
	if (h == NULL || pe == NULL || !h->init()) {
		LOG("AppleOLYHAL: not made");
		return;
	}
	h->setProperty("vendor-id", "Murata");
	if (h->attach(pe)) {
		h->registerService();
		LOG("AppleOLYHAL: vendor-id Murata");
	}
	h->release();
}

extern "C" void
lv_bt_start(void)
{''')
sub('''	started = true;
	if (kernel_thread_start(bt_thread''', '''	started = true;
	bt_olyhal();
	if (kernel_thread_start(bt_thread''')
if '#include <IOKit/IOService.h>' not in s:
    sub('#include <IOKit/IOLocks.h>\n', '#include <IOKit/IOLocks.h>\n#include <IOKit/IOService.h>\n#include <IOKit/IOPlatformExpert.h>\n')
open(path, 'w', newline='\n').write(s)
print('ok')
