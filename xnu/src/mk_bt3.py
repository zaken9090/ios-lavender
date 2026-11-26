"""lavender: Bluetooth B1c - hardware flow control after the power-on pulse (patch 1087).

Run e95: the UART is fine (internal loopback returns the bytes) and the chip power rails are on,
yet the chip answers nothing. Linux sends the pulses without flow control and then turns
RTS/CTS on (hci_uart_set_flow_control(hu, false)); a WCN399x only talks while the host holds RTS
(our RFR) asserted. Now after the 0xFC pulse: MR1 = auto-RFR level | RX_RDY_CTL | CTS_CTL, and RFR
is set explicitly; the pulses themselves still go out without flow control.

usage: python mk_bt3.py XNU_TREE   (after mk_bt2.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()
old = '''	pulse = 0xFC;
	bt_put(&pulse, 1);
	IOSleep(100);
'''
new = '''	pulse = 0xFC;
	bt_put(&pulse, 1);
	/* flow control on, as Linux does after the pulses (mk_bt3.py): auto RFR at 48 bytes, CTS gates TX */
	wr(uart, U_MR1, 48u | (1u << 7) | (1u << 6));
	wr(uart, U_CR, 13u << 4);                               /* SET_RFR */
	IOSleep(100);
'''
assert s.count(old) == 1
s = s.replace(old, new)
open(path, 'w', newline='\n').write(s)
print('ok')
