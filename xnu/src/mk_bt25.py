"""lavender: Bluetooth UART - no sleep between a stale event and the next transfer (patch 1109).

Run e119 (xnu 1108): the tails are still lost after reading the partial word by count. The pump
slept 1 ms (often ~10) between polls: when the chip sends again more than one stale timeout
(31 characters, ~2.7 ms) after a packet but before the poll handled that stale event, the new
bytes sit in the FIFO when the transfer is re-armed (DMRX) - they are not in the new SNAP count,
so they are read as words of the new transfer, the counts disagree, and a partial word is lost.

Now the pump polls every 20 us for 20 ms after the last received byte (a stale event is handled
within microseconds, long before the next byte at 115200 baud) and sleeps 1 ms only when the
line has been quiet for 20 ms. The forced stale and stuck-packet timers count real time.

usage: python mk_bt25.py XNU_TREE   (after mk_bt24.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		if (rx_head == rx_tail) {
			IOSleep(1);
			idle_ms++;
			if (idle_ms == 5) {''', '''		if (rx_head == rx_tail) {
			/* idle_ms counts 20 us steps for the first 20 ms after traffic (idle_us), then 1 ms sleeps */
			if (idle_us < 20000) {
				IODelay(20);
				idle_us += 20;
				if (idle_us % 1000 != 0) {
					continue;
				}
			} else {
				IOSleep(1);
			}
			idle_ms++;
			if (idle_ms == 5) {''')
sub('''		idle_ms = 0;''', '''		idle_ms = 0;
		idle_us = 0;''')
sub('''	uint32_t have = 0, idle_ms = 0, overruns = 0;''', '''	uint32_t have = 0, idle_ms = 0, idle_us = 20000, overruns = 0;''')
open(path, 'w', newline='\n').write(s)
print('ok')
