"""lavender: Bluetooth B2 diagnostics - what the chip says after the firmware (patch 1089).

Run e97: version read (WCN3990 rom 0x201, soc 0x40020140), rampatch (mode 3) and NVM accepted,
"firmware: loaded" - then HCI_Reset and Read_Local_Version got no Command Complete.

Now: every event bt_cmd_cc() gets is logged (code, length, first bytes), a failed wait says so,
and before the reset the raw bytes of 1 s are dumped (does the chip talk at all, at which speed).
The UART status (SR, ISR, SNAP, RXFS) is logged when nothing comes.
NVM tag 17 bit 7 (software in-band sleep, set by Linux) is now cleared.

usage: python mk_bt5.py XNU_TREE   (after mk_bt4.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	bt_send(opcode, param, plen);
	for (int n = 0; n < 8; n++) {
		if (!bt_event(&code, buf, &l, 1000)) {
			return false;
		}
''', '''	bt_send(opcode, param, plen);
	for (int n = 0; n < 8; n++) {
		if (!bt_event(&code, buf, &l, 1000)) {
			LOG("cmd %#06x: no event (after %d others); sr %#x isr %#x snap %u rxfs %#x", opcode, n, rd(uart, U_SR),
			    rd(uart, U_ISR), rd(uart, U_SNAP), rd(uart, U_RXFS));
			return false;
		}
		LOG("cmd %#06x: event %#04x len %u: %02x %02x %02x %02x %02x %02x", opcode, code, l, buf[0], buf[1], buf[2], buf[3],
		    buf[4], buf[5]);
''')
sub('''	LOG("firmware: %s", ok ? "loaded" : "FAILED");
	IOSleep(100);
''', '''	LOG("firmware: %s", ok ? "loaded" : "FAILED");
	{
		char line[3 * 32 + 1];
		unsigned n = 0, total = 0;
		for (int b; (b = bt_byte(1000)) >= 0 && total < 256; total++) {
			snprintf(line + 3 * n, 4, "%02x ", b);
			if (++n == 32) {
				LOG("after firmware: %s", line);
				n = 0;
			}
		}
		if (n != 0) {
			LOG("after firmware: %s", line);
		}
		LOG("after firmware: %u bytes; sr %#x isr %#x snap %u", total, rd(uart, U_SR), rd(uart, U_ISR), rd(uart, U_SNAP));
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
