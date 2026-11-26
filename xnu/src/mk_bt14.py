"""lavender: Bluetooth control - drop the chip's debug ACL, report a Broadcom version (patch 1098).

Run e106 (xnu 1097) trace: BlueTool's HCI_Reset and 0xFC18 complete; then the chip sends ACL
packets on handle 0x2EDC (02 dc 2e ..., ~480 bytes): Qualcomm firmware logging (Linux hci_qca
QCA_DEBUG_HANDLE, passed to hci_recv_diag, never to the stack). BlueTool reads them as data
("ACL/SCO DATA?!") and stalls; its next step asks Read_Local_Version to name the chip.

Now:
- ACL on handle 0x2EDC (and 0x2EDD, memory dump) stays in the kernel (counted, not passed up).
- the Command Complete of Read_Local_Version (0x1001) is given to user space as the iPhone X
  chip reports it: manufacturer 15 (Broadcom), LMP subversion 0x420E (BCM4357B1), HCI/LMP
  versions as the chip says. The real values are logged. (BlueTool and bluetoothd pick their
  Broadcom code paths from it; the vendor commands that follow are answered by the kernel.)

usage: python mk_bt14.py XNU_TREE   (after mk_bt13.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''			if (need != 0 && have >= need) {
				ctl_up(pkt, need);      /* dropped when nobody is connected */
				have = 0;
			}''', '''			if (need != 0 && have >= need) {
				uint16_t h = (uint16_t)((pkt[1] | (pkt[2] << 8)) & 0x0fff);
				if (pkt[0] == 0x02 && (h == 0x2edc || h == 0x2edd)) {
					static uint32_t diag;
					if (diag++ % 100 == 0) {
						LOG("rx: chip debug ACL %#x kept here (%u so far)", h, diag);
					}
				} else {
					if (pkt[0] == 0x04 && pkt[1] == 0x0e && need >= 15 && pkt[4] == 0x01 && pkt[5] == 0x10 && pkt[6] == 0) {
						LOG("Read_Local_Version: chip manufacturer %#x subversion %#x -> Broadcom 0xf / 0x420e",
						    pkt[11] | (pkt[12] << 8), pkt[13] | (pkt[14] << 8));
						pkt[11] = 0x0f;
						pkt[12] = 0x00;
						pkt[13] = 0x0e;
						pkt[14] = 0x42;
					}
					ctl_up(pkt, need);      /* dropped when nobody is connected */
				}
				have = 0;
			}''')
open(path, 'w', newline='\n').write(s)
print('ok')
