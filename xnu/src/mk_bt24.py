"""lavender: Bluetooth UART - read the partial word at the stale event (patch 1108).

Run e118 (xnu 1107): still "packet stuck: have 485 need 486", "have 4 need 7", "have 13 need 15" -
the bytes of the last, partial FIFO word are lost, not late: after the stale event the receive
loop read words only while SR.RX_READY, which UARTDM does not raise for a partial word. Linux
(msm_poll_get_char_dm) reads UARTDM_RF at the stale event without looking at RX_READY and takes
RX_TOTAL_SNAP - consumed bytes of it.

Now at the stale event the words are read by count (SNAP - taken), not by RX_READY.

usage: python mk_bt24.py XNU_TREE   (after mk_bt23.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()
old = '''		while (left > 0 && (rd(uart, U_SR) & SR_RX_READY)) {'''
assert s.count(old) == 1
s = s.replace(old, '''		while (left > 0) {                      /* by count: a partial word has no RX_READY */''')
open(path, 'w', newline='\n').write(s)
print('ok')
