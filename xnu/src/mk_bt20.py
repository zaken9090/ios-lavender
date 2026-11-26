"""lavender: /chosen/mac-address-bluetooth0 and mac-address-wifi0 (patch 1104).

Run e113 (xnu 1103): bluetoothd's stack is up, but Settings has no Bluetooth row. Its root list
(PreferencesUI Settings.plist) shows the row only with the MobileGestalt capability "bluetooth",
and MobileGestalt answers it (static analysis) from a non-zero 6-byte address in
IODeviceTree:/chosen "mac-address-bluetooth0" - filled by iBoot on an iPhone - then, slowly,
IONetworkController parents and syscfg. The Wi-Fi address has the same place
("mac-address-wifi0").

Now when the modem's NV gives the addresses (read only, as before) the kernel puts them there:
NV 447 in written form (reversed, as 0xFC14 and local-mac-address get it) and the NV 4678 Wi-Fi
address as the Wi-Fi driver uses it.

usage: python mk_bt20.py XNU_TREE   (after mk_bt19.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('#include <IOKit/IOMemoryDescriptor.h>\n', '#include <IOKit/IOMemoryDescriptor.h>\n#include <IOKit/IODeviceTreeSupport.h>\n')
sub('''static void wlan_mac_set(const uint8_t *m);
''', '''static void wlan_mac_set(const uint8_t *m);

/* an address where iBoot puts it on an iPhone: IODeviceTree:/chosen (MobileGestalt reads it) */
static void
chosen_mac(const char *key, const uint8_t *m)
{
	IORegistryEntry *ch = IORegistryEntry::fromPath("/chosen", gIODTPlane);
	if (ch == NULL) {
		return;
	}
	OSData *d = OSData::withBytes(m, 6);
	if (d != NULL) {
		ch->setProperty(key, d);
		d->release();
	}
	ch->release();
	LOG("/chosen/%s = %02x:%02x:%02x:**:**:**", key, m[0], m[1], m[2]);
}
''')
sub('''		memcpy(bt_addr_nv, data + 3, 6);
''', '''		memcpy(bt_addr_nv, data + 3, 6);
		{
			uint8_t w[6];
			for (int i = 0; i < 6; i++) {
				w[i] = bt_addr_nv[5 - i];
			}
			chosen_mac("mac-address-bluetooth0", w);
		}
''')
sub('''wlan_mac_set(const uint8_t *m)
{
	memcpy(our_mac, m, 6);
}''', '''wlan_mac_set(const uint8_t *m)
{
	memcpy(our_mac, m, 6);
	chosen_mac("mac-address-wifi0", m);
}''')
open(path, 'w', newline='\n').write(s)
print('ok')
