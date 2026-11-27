"""lavender: Bluetooth UART - outside a stale event read only the FIFO's full words (patch 1137).

Run bp1 (xnu 1136): the user's headset connects, pairs (SSP, link key stored, encryption on),
SDP, HFP and A2DP connect, the headset plays its "connected" tone - then the link drops. 1339
"rx: stray byte 0000" lines in the same log: zero bytes appear in the chip's stream, packets
are cut wrongly and the higher layers fail.

The stray zeros come from the receive loop: outside a stale event it read words while
SR.RX_READY; when the stale event fires during that loop the packing buffer (1-3 bytes) is
pushed into the FIFO as a word and read as 4 bytes, and rx_taken overcounts. Now it first reads
RXFS (bits 6:0 = full words in the FIFO, bits 9:7 = bytes still in the packing buffer) and takes
only that many words; the rest waits for the stale branch, which reads by SNAP - taken.

usage: python mk_bt32.py XNU_TREE   (after mk_audio18.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()
old = '''	bool got = false;
	while (rd(uart, U_SR) & SR_RX_READY) {'''
assert s.count(old) == 1
s = s.replace(old, '''	bool got = false;
	uint32_t words = rd(uart, U_RXFS) & 0x7F;      /* full words now; a partial one stays for the stale branch */
	while (words-- > 0 && (rd(uart, U_SR) & SR_RX_READY)) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
