"""lavender: Bluetooth control - Erroneous Data Reporting for bluetoothd (patch 1101).

Run e109 (xnu 1100): bluetoothd's own init now runs on the chip (reset, version, supported
commands/features, event masks, LE setup, buffer sizes, host flow control - all status 0), then
stops: "OI_HCICMD_WriteDefaultErroneousDataReporting (status=628)", "HCI initialization failed".
It never sent 0x0C5B: the chip's Read_Local_Supported_Commands has octet 18 bits 2/3 (Read /
Write Default Erroneous Data Reporting) clear, and bluetoothd treats that as fatal (the iPhone's
chip has them).

Now those two bits are set in the 0x1002 answer user space gets (the chip's octet is logged), and
0x0C5A / 0x0C5B are answered by the kernel: reporting stays "disabled" (0), which is what a
write of 0 asks and what the chip does anyway.

usage: python mk_bt17.py XNU_TREE   (after mk_bt16.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		if (op >= 0xFC00) {''', '''		if (op == 0x0C5A || op == 0x0C5B) {
			/* Read / Write Default Erroneous Data Reporting: not in the Qualcomm firmware */
			uint8_t cc[8] = { 0x04, 0x0e, (uint8_t)(op == 0x0C5A ? 5 : 4), 0x01, p[1], p[2], 0x00, 0x00 };
			LOG("%#06x (%u bytes): answered here", op, p[3]);
			ctl_up(cc, op == 0x0C5A ? 8 : 7);
			return;
		}
		if (op >= 0xFC00) {''')
sub('''					if (pkt[0] == 0x04 && pkt[1] == 0x0e && need >= 15 && pkt[4] == 0x01 && pkt[5] == 0x10 && pkt[6] == 0) {''',
    '''					if (pkt[0] == 0x04 && pkt[1] == 0x0e && need >= 7 + 64 && pkt[4] == 0x02 && pkt[5] == 0x10 && pkt[6] == 0) {
						LOG("supported commands: octet 18 %#04x -> with Erroneous Data Reporting", pkt[7 + 18]);
						pkt[7 + 18] |= (1u << 2) | (1u << 3);
					}
					if (pkt[0] == 0x04 && pkt[1] == 0x0e && need >= 15 && pkt[4] == 0x01 && pkt[5] == 0x10 && pkt[6] == 0) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
