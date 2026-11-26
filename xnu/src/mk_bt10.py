"""lavender: an IOService for /arm-io/uart1/bluetooth (patch 1094).

Run e102 (xnu 1093, mkadt --bt): bluetoothd now runs and looks, but logs "bluetooth: Unable to
match bluetooth service in device tree" - it matches an IOService by name, and only the direct
children of /arm-io get nubs (SweetPlatformExpert::processTopLevel). Then "Not a valid MAC
address (all 0s)" / "No bluetooth on this device" and an exit (launchd starts it again).

Now the children of /arm-io/uart1 get nubs too (registered services named "bluetooth").

usage: python mk_bt10.py XNU_TREE   (after mk_bt9.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetPlatformExpert.cpp'
s = open(path, newline='').read()
old = '''		createNubs(this, IODTFindMatchingEntries(armio, kIODTExclusive, "('gic')"));
		armio->release();
'''
assert s.count(old) == 1
s = s.replace(old, '''		createNubs(this, IODTFindMatchingEntries(armio, kIODTExclusive, "('gic')"));
		armio->release();
	}
	/* lavender (xnu/src/mk_bt10.py): the Bluetooth node under the UART, matched by name by bluetoothd */
	IORegistryEntry *uart1 = root->childFromPath("arm-io/uart1", gIODTPlane);
	if (uart1 != NULL) {
		createNubs(this, IODTFindMatchingEntries(uart1, kIODTExclusive, NULL));
		uart1->release();
''')
open(path, 'w', newline='\n').write(s)
print('ok')
