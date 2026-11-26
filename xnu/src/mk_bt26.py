"""lavender: Bluetooth UART - log every stale event (patch 1110).

Runs e119-e122 (xnu 1108/1109): the same bytes are lost on every boot - the 0x2EDC debug ACL
after BlueTool's 0xFC18 arrives with 485 of 486 bytes, the Command Complete after it with 4 of 7
- whatever the polling speed, so not a race with the re-arm.

Now the first 60 stale events after the control is registered are logged: SNAP, bytes taken
before the event, bytes left, words read, the bytes of the last word, SR and RXFS before and
after; and words read outside a stale event when SR said RX_READY are counted per event.

usage: python mk_bt26.py XNU_TREE   (after mk_bt25.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		uint32_t snap = rd(uart, U_SNAP);
		int32_t left = (int32_t)(snap - rx_taken);''', '''		uint32_t snap = rd(uart, U_SNAP);
		int32_t left = (int32_t)(snap - rx_taken);
		uint32_t sr0 = rd(uart, U_SR), fs0 = rd(uart, U_RXFS), words = 0, lastw = 0;
		int32_t left0 = left;''')
sub('''			uint32_t w = rd(uart, U_RF);
			for (int i = 0; i < 4 && left > 0; i++, left--) {''', '''			uint32_t w = rd(uart, U_RF);
			words++;
			lastw = w;
			for (int i = 0; i < 4 && left > 0; i++, left--) {''')
sub('''		rx_taken = 0;
		wr(uart, U_CR, CR_RESET_STALE);''', '''		if (stale_log != 0 && stale_n < 60) {
			stale_n++;
			LOG("stale %u: snap %u taken %u left %d words %u last %08x sr %#x->%#x rxfs %#x->%#x", stale_n, snap, rx_taken,
			    left0, words, lastw, sr0, rd(uart, U_SR), fs0, rd(uart, U_RXFS));
		}
		rx_taken = 0;
		wr(uart, U_CR, CR_RESET_STALE);''')
sub('''static uint32_t rx_head, rx_tail, rx_taken;''', '''static uint32_t rx_head, rx_tail, rx_taken;
static uint32_t stale_log, stale_n;             /* mk_bt26.py: set when the control is up */''')
sub('''	bt_ready = true;''', '''	bt_ready = true;
	stale_log = 1;''')
open(path, 'w', newline='\n').write(s)
print('ok')
