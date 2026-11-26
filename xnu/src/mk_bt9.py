"""lavender: Bluetooth - the address in the right order, and in the device tree (patch 1093).

Run e101 (xnu 1092): firmware up, HCI_Reset 0, Read_Local_Version HCI 9 / manufacturer 0x1D.
The address went to 0xFC14 as NV 447 stores it, and Read_BD_ADDR then gave it back reversed:
0xFC14 takes the address most significant byte first (as written), NV 447 keeps it the other way.

Now the address is reversed once (= the usual written form, Xiaomi's OUI first), sent so to
0xFC14, and put into IODeviceTree:/arm-io/uart1/bluetooth as local-mac-address (6 bytes, written
form, as iBoot fills it on an iPhone) for bluetoothd (mkadt.py --bt makes the node, zero filled).

usage: python mk_bt9.py XNU_TREE   (after mk_bt8.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	uint8_t addr[6];
	if (lv_bt_addr(addr)) {
		if (bt_cmd_cc(0xFC14, addr, 6, ret, &rlen)) {''', '''	uint8_t nv[6], addr[6];
	if (lv_bt_addr(nv)) {
		for (int i = 0; i < 6; i++) {
			addr[i] = nv[5 - i];            /* written form */
		}
		IORegistryEntry *bt = IORegistryEntry::fromPath("/arm-io/uart1/bluetooth", gIODTPlane);
		if (bt != NULL) {
			OSData *d = OSData::withBytes(addr, 6);
			if (d != NULL) {
				bt->setProperty("local-mac-address", d);
				d->release();
			}
			bt->release();
			LOG("address %02x:%02x:%02x:**:**:** -> device tree", addr[0], addr[1], addr[2]);
		} else {
			LOG("no /arm-io/uart1/bluetooth node (mkadt.py --bt)");
		}
		if (bt_cmd_cc(0xFC14, addr, 6, ret, &rlen)) {''')
sub('''		LOG("BD_ADDR: status %#x, %02x:%02x:%02x:**:**:**", ret[0], ret[6], ret[5], ret[4]);''',
    '''		LOG("BD_ADDR: status %#x, %02x:%02x:%02x:**:**:** (written form)", ret[0], ret[6], ret[5], ret[4]);''')
if '#include <IOKit/IORegistryEntry.h>' not in s:
    sub('#include <IOKit/IOLib.h>\n', '#include <IOKit/IOLib.h>\n#include <IOKit/IODeviceTreeSupport.h>\n')
open(path, 'w', newline='\n').write(s)
print('ok')
