"""lavender: Bluetooth UART - re-arm the stale event after every batch of words (patch 1113).

Runs e124-e127: the receive path breaks only after the chip sends its long debug ACL (0x2EDC,
~486 bytes); a boot where the chip sent none (e126, xnu 1103) ran BlueTool and bluetoothd
through. After the long packet no stale event fires any more (SNAP 0, ISR unchanged, RXFS shows
1-3 bytes in the packing buffer), so every partial last word stays in the UART.

Linux msm_handle_rx_dm writes DMRX (0xFFFFFF) and STALE_EVENT_ENABLE again after every batch it
reads - on the FIFO level event too, not only at stale - and keeps the bytes it took
(old_snap_state) to subtract at the stale event. We re-armed only at stale.

Now after a batch of whole words is read outside a stale event, DMRX and STALE_EN are written
again (the count of taken bytes is kept, as in Linux).

usage: python mk_bt29.py XNU_TREE   (after mk_bt28.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()
old = '''	/* words before the stale event are full */
	while (rd(uart, U_SR) & SR_RX_READY) {
		uint32_t w = rd(uart, U_RF);
		for (int i = 0; i < 4; i++) {
			rx_push((uint8_t)(w >> (8 * i)));
		}
		rx_taken += 4;
	}'''
assert s.count(old) == 1
s = s.replace(old, '''	/* words before the stale event are full */
	bool got = false;
	while (rd(uart, U_SR) & SR_RX_READY) {
		uint32_t w = rd(uart, U_RF);
		for (int i = 0; i < 4; i++) {
			rx_push((uint8_t)(w >> (8 * i)));
		}
		rx_taken += 4;
		got = true;
	}
	if (got) {
		/* msm_handle_rx_dm: re-arm after every batch, not only at stale */
		wr(uart, U_DMRX, 0xFFFFFF);
		wr(uart, U_CR, CR_STALE_EN);
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
