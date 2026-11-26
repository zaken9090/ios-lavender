"""lavender: Bluetooth control - trace every session (patch 1100).

Run e108 (xnu 1099): BlueTool boot + init give result 0; bluetoothd starts its stack, connects
(termios 3000000) and its HCI_Reset times out ("reset command failed (STATUS 621)", then
"Bluetooth error - restarting ... OI_DHCI_RESET_OPCODE"). The trace of 1097 had used up its 200
packets on BlueTool's firmware records, so bluetoothd's bytes were not seen.

Now the trace counters start again at every connect, FC4C (HCD records) are not traced, and
bytes that do not start an H4 packet in the down direction are logged too.

usage: python mk_bt16.py XNU_TREE   (after mk_bt15.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	ctl_unit = sac->sc_unit;
	tx_have = 0;''', '''	ctl_unit = sac->sc_unit;
	tx_have = 0;
	trace_up = trace_down = 0;''')
sub('''	if (trace_down++ < 200) {
		bt_trace("down", p, n);
	}''', '''	if (!(n >= 3 && p[0] == 0x01 && p[1] == 0x4c && p[2] == 0xfc) && trace_down++ < 200) {
		bt_trace("down", p, n);
	}''')
sub('''	if (trace_up++ < 200) {
		bt_trace("up", p, n);
	}''', '''	if (!(n == 7 && p[4] == 0x4c && p[5] == 0xfc) && trace_up++ < 200) {
		bt_trace("up", p, n);
	}''')
sub('''			default: need = 1; break;               /* not H4: pass the byte on */''',
    '''			default:
				need = 1;                       /* not H4: pass the byte on */
				LOG("tx: byte %#04x outside a packet", tx_pkt[0]);
				break;''')
open(path, 'w', newline='\n').write(s)
print('ok')
