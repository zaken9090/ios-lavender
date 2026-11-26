"""lavender: Bluetooth B2 - why the chip is silent after its firmware (patch 1090).

Run e98: after rampatch + NVM the chip sends the NOP Command Complete (04 0e 04 01 00 00 00, the
firmware is up), then answers nothing: HCI_Reset, Read_Local_Version, 0xFC14 get no event. The
UART ISR then shows DELTA_CTS set and CURRENT_CTS (bit 6) clear: the chip has dropped its RTS, so
with CTS flow control our bytes may never leave.

Now, when HCI_Reset gets no answer, three tries, each logged with the CTS state:
  1. once more as is;
  2. HCI_IBS wake indication 0xFD sent with CTS flow control off, 50 ms for its wake ack 0xFC,
     flow control back on, HCI_Reset;
  3. CTS flow control left off, HCI_Reset.
The NVM tags 17 and 27 are logged as stored (first data bytes) before our edits.

usage: python mk_bt6.py XNU_TREE   (after mk_bt5.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''			if (id == 17 && tl >= 3) {''', '''			if ((id == 17 || id == 27) && tl >= 4) {
				LOG("nvm tag %u len %u: %02x %02x %02x %02x", id, tl, t[12], t[13], t[14], t[15]);
			}
			if (id == 17 && tl >= 3) {''')
sub('''	if (bt_cmd_cc(0x0C03, NULL, 0, ret, &rlen)) {
		LOG("HCI_Reset: status %#x", ret[0]);
	}
''', '''#define CTS_NOW() ((rd(uart, U_ISR) >> 6) & 1)
	LOG("before HCI_Reset: cts %u mr1 %#x", CTS_NOW(), rd(uart, U_MR1));
	bool up = bt_cmd_cc(0x0C03, NULL, 0, ret, &rlen);
	if (!up) {
		LOG("try 1 (again): cts %u", CTS_NOW());
		up = bt_cmd_cc(0x0C03, NULL, 0, ret, &rlen);
	}
	if (!up) {
		uint32_t mr1 = rd(uart, U_MR1);
		wr(uart, U_MR1, mr1 & ~(1u << 6));
		uint8_t wake = 0xFD;
		bt_put(&wake, 1);
		int a = bt_byte(50);
		wr(uart, U_MR1, mr1);
		LOG("try 2 (IBS wake 0xfd): got %#x, cts %u", a, CTS_NOW());
		up = bt_cmd_cc(0x0C03, NULL, 0, ret, &rlen);
	}
	if (!up) {
		wr(uart, U_MR1, rd(uart, U_MR1) & ~(1u << 6));
		LOG("try 3 (no CTS flow control): cts %u", CTS_NOW());
		up = bt_cmd_cc(0x0C03, NULL, 0, ret, &rlen);
	}
	if (up) {
		LOG("HCI_Reset: status %#x, cts %u", ret[0], CTS_NOW());
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
