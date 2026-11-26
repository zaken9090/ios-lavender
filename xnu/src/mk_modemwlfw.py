"""lavender: modem_wlfw=0 leaves the WLAN firmware service alone; TZ log address accepted (patch 1051).

Run e49: with every GLINK open acknowledged and the mcfg files found, the modem still dies 13.4 s
after its start of "Task starvation: diag". The last thing we start in it before that is the
WLAN firmware (WLFW handshake at 1.03 s; its MSA_READY indication never comes), and the Wi-Fi
chip has no power yet (step 7). modem_wlfw=0 skips the WLFW handshake, to tell whether the WLAN
firmware is what starves diag. The result of handing the MSA regions over is logged. TrustZone's
log area on this phone is at 0x14693000, below the address the first check allowed.

usage: python mk_modemwlfw.py XNU_TREE   (after mk_modemdiag.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		(void)scm_assign(addr, size, vm, sec ? 2 : 3);
''', '''		LOG(" handed to the modem: %d", (int)scm_assign(addr, size, vm, sec ? 2 : 3));
''')
sub('''	if ((w_node != 0 || w_port != 0) && w_node == node && w_port == port) {
		return;
	}
	if (w_arrivals++ != 0) {''', '''	if ((w_node != 0 || w_port != 0) && w_node == node && w_port == port) {
		return;
	}
	uint32_t wl = 1;
	(void)PE_parse_boot_argn("modem_wlfw", &wl, sizeof(wl));
	if (wl == 0) {
		LOG("WLFW left alone (modem_wlfw=0)");
		return;
	}
	if (w_arrivals++ != 0) {''')
sub('''	if (pa < 0x80000000u || (pa & 3) != 0) {
		return;
	}
''', '''	if (pa < 0x10000000u || (pa & 3) != 0) {
		return;
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
