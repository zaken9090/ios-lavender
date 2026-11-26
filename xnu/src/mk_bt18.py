"""lavender: Bluetooth control - vendor answers with return bytes (patch 1102).

Run e110 (xnu 1101): bluetoothd's stack came up on the chip ("Stack initialization complete",
STACK_BUSY -> STACK_READY, local name, class, EIR, SDP), then after Broadcom 0xFD48 (answered
here with a bare status) it asserted: "bcm_vsc.c:642 : ByteStream_NumReadBytesAvail(*pBs) >= 1"
and restarted - some vendor commands' results are parsed past the status byte.

Now the kernel's Command Complete for a vendor opcode carries 8 zero bytes after the status
(a parser takes what it needs; BlueTool only checks ncmd/opcode/status). The vendor log is per
connection (first 64).

usage: python mk_bt18.py XNU_TREE   (after mk_bt17.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''			uint8_t cc[7] = { 0x04, 0x0e, 0x04, 0x01, p[1], p[2], 0x00 };''',
    '''			uint8_t cc[7 + 8] = { 0x04, 0x0e, 0x04 + 8, 0x01, p[1], p[2], 0x00 };''')
sub('''	trace_up = trace_down = 0;''', '''	trace_up = trace_down = 0;
	vendor_logged = 0;''')
sub('''	if (!(n == 7 && p[4] == 0x4c && p[5] == 0xfc) && trace_up++ < 200) {''',
    '''	if (!(n >= 7 && p[1] == 0x0e && p[4] == 0x4c && p[5] == 0xfc) && trace_up++ < 200) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
