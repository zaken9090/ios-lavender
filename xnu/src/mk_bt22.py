"""lavender: Bluetooth control - packets that hang half-received (patch 1106).

Run e116 (xnu 1105): the Bluetooth page spins; bluetoothd restarts ("BD_VSC_FACTORY_CAL_READ_TABLE
timedout waiting for controller", "OI_DHCI_READ_LOCAL_SUP_CMDS_OPCODE", "BlueTool timed out
running boot script"). The trace shows the chip's answers arriving late: the Command Complete of
0x0C13 went up only after the next connection's HCI_Reset, Read_Local_Version's answer only
after the following session's reset - an answer is held back until the chip sends more.

Either the UART keeps the tail of a transfer (no stale event) or the packet cutter waits inside
a packet whose length it misread (one lost byte in front of a long debug ACL is enough). Now:
- every 1 ms poll also looks at SR (overrun bit 4) and logs overruns, and a FORCE_STALE is issued
  when no byte came for 5 ms, so a tail cannot stay in
  the FIFO;
- the packet cutter logs and drops a packet that is still incomplete 50 ms after its last byte
  (type, header, have/need), and then looks for the next packet start.

usage: python mk_bt22.py XNU_TREE   (after mk_bt21.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	static uint8_t pkt[4 + 65536];
	uint32_t have = 0;
	for (;;) {
		bt_rx_poll();
		if (rx_head == rx_tail) {
			IOSleep(1);
			continue;
		}''', '''	static uint8_t pkt[4 + 65536];
	uint32_t have = 0, idle_ms = 0, overruns = 0;
	for (;;) {
		uint32_t sr = rd(uart, U_SR);
		if (sr & (1u << 4)) {
			wr(uart, U_CR, CR_RESET_ERR);
			if (overruns++ < 20) {
				LOG("rx: UART overrun (%u)", overruns);
			}
		}
		bt_rx_poll();
		if (rx_head == rx_tail) {
			IOSleep(1);
			idle_ms++;
			if (idle_ms == 5) {
				wr(uart, U_CR, CR_FORCE_STALE);         /* the tail of this transfer out of the FIFO */
			}
			if (idle_ms == 50 && have != 0) {
				uint32_t need = pkt[0] == 0x04 && have >= 3 ? 3u + pkt[2] :
				    pkt[0] == 0x02 && have >= 5 ? 5u + (pkt[3] | (pkt[4] << 8)) : 0;
				LOG("rx: packet stuck: %02x %02x %02x %02x %02x have %u need %u - dropped", pkt[0], pkt[1], pkt[2],
				    pkt[3], pkt[4], have, need);
				have = 0;
			}
			continue;
		}
		idle_ms = 0;''')
open(path, 'w', newline='\n').write(s)
print('ok')
