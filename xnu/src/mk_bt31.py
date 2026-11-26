"""lavender: Bluetooth - vendor answers padded to 32 return bytes (patch 1115).

Run e128 (xnu 1113): receive path fixed, bluetoothd reaches STACK_READY, then restarts with
reason 3602 on BD_VSC_FACTORY_CAL_READ_TABLE. Static analysis of bluetoothd: that is 0xFD1B
{table type}; its parser (ByteStream) needs at least 2 return bytes after the status, our echo
gave 1, the callback never ran and the VSC stall watchdog (0xE12 = 3602) restarted the stack.
The Broadcom parsers only check minimum lengths (1, 2, 3, 8, 12, ...) and, for LE meta / AdvBuf
commands, the sub-opcode in the first return byte.

Now: status 0, the command's parameters echoed (up to 16 bytes), zeros up to 32 return bytes -
minimums met, sub-opcodes match, counts read as 0.

usage: python mk_bt31.py XNU_TREE   (after mk_bt30.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''			uint8_t echo = p[3] < 16 ? p[3] : 16;
			uint8_t cc[7 + 16] = { 0x04, 0x0e, (uint8_t)(0x04 + echo), 0x01, p[1], p[2], 0x00 };
			memcpy(cc + 7, p + 4, echo);''', '''			uint8_t echo = p[3] < 16 ? p[3] : 16;
			uint8_t cc[7 + 32] = { 0x04, 0x0e, 0x04 + 32, 0x01, p[1], p[2], 0x00 };   /* rest zero */
			memcpy(cc + 7, p + 4, echo);''')
sub('''			ctl_up(cc, 7u + echo);''', '''			ctl_up(cc, sizeof(cc));''')
open(path, 'w', newline='\n').write(s)
print('ok')
