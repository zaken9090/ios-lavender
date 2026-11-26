"""lavender: Bluetooth control - vendor answers echo the parameters (patch 1103).

Run e111 (xnu 1102): with 8 zero bytes after the status, 0xFD48 passed, but
BD_VSC_LE_META_ENA_FEATURES (0xFCE9 {01 27 10 10 00}) failed ("restarting, reason=3602"):
Broadcom's meta commands answer {status, sub-opcode, ...} and bluetoothd checks the sub-opcode.

Now the kernel's Command Complete for a vendor opcode is status 0 followed by the command's own
parameters (up to 16 bytes; none when it had none) - the sub-opcode comes back where Broadcom puts
it, and commands parsed for a byte or more get one.

usage: python mk_bt19.py XNU_TREE   (after mk_bt18.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()
old = '''			uint8_t cc[7 + 8] = { 0x04, 0x0e, 0x04 + 8, 0x01, p[1], p[2], 0x00 };'''
assert s.count(old) == 1
s = s.replace(old, '''			uint8_t echo = p[3] < 16 ? p[3] : 16;
			uint8_t cc[7 + 16] = { 0x04, 0x0e, (uint8_t)(0x04 + echo), 0x01, p[1], p[2], 0x00 };
			memcpy(cc + 7, p + 4, echo);''')
old = '''			ctl_up(cc, sizeof(cc));'''
assert s.count(old) == 1
s = s.replace(old, '''			ctl_up(cc, 7u + echo);''')
open(path, 'w', newline='\n').write(s)
print('ok')
