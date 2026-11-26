"""lavender: Bluetooth UART - registers when a packet is stuck (patch 1111).

Run e123 (xnu 1110): not one stale event after the control came up, yet packets that end in a
partial FIFO word lose that word (version answer: 12 of 15 bytes). During bt_setup() stale did
work (the NOP Command Complete after the NVM came whole, SNAP 13).

Now, when a packet is stuck (50 ms without its last bytes), the UART state is logged: SR, ISR,
MISR, IMR (read back is not possible: logged as written), RXFS (bits 9:7 = bytes in the packing
buffer), SNAP, taken; then FORCE_STALE is written and ISR/MISR/RXFS/SNAP logged again 1 ms later.

usage: python mk_bt27.py XNU_TREE   (after mk_bt26.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()
old = '''				LOG("rx: packet stuck: %02x %02x %02x %02x %02x have %u need %u - dropped", pkt[0], pkt[1], pkt[2],
				    pkt[3], pkt[4], have, need);'''
assert s.count(old) == 1
s = s.replace(old, old + '''
				LOG("rx: uart sr %#x isr %#x misr %#x rxfs %#x snap %u taken %u", rd(uart, U_SR), rd(uart, U_ISR), rd(uart, 0x10),
				    rd(uart, U_RXFS), rd(uart, U_SNAP), rx_taken);
				wr(uart, U_CR, CR_FORCE_STALE);
				IOSleep(1);
				LOG("rx: after FORCE_STALE: sr %#x isr %#x misr %#x rxfs %#x snap %u", rd(uart, U_SR), rd(uart, U_ISR),
				    rd(uart, 0x10), rd(uart, U_RXFS), rd(uart, U_SNAP));''')
open(path, 'w', newline='\n').write(s)
print('ok')
