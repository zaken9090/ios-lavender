"""lavender: Bluetooth control - whole packets up, and a byte trace (patch 1097).

Run e105 (xnu 1096): MobileGestalt gives "Murata", BlueTool picks the D22 boot script (fwPos 30),
connects to com.apple.uart.bluetooth, sets termios, its HCI_Reset goes to the chip and completes;
then 0xFC18 (baud) is answered by the kernel - and BlueTool reads "ACL/SCO DATA?!" twice and
waits forever.

The pump thread gave the socket whatever bytes it had, the kernel's own answers went in from the
send path: they can land inside a packet of the chip's. Now the pump cuts the chip's stream into
whole H4 packets (event 0x04: 2 + len, ACL 0x02: 4 + len, SCO 0x03: 3 + len; other bytes one
by one, logged) and both writers enqueue under one lock. Up and down traffic is logged (first
16 bytes of the first 200 packets each way) to see what BlueTool takes for ACL.

usage: python mk_bt13.py XNU_TREE   (after mk_bt12.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static void
ctl_up(const uint8_t *p, size_t n)
{
	if (ctl_on && ctl_enqueuedata(ctl_ref, ctl_unit, (void *)(uintptr_t)p, n, 0) != 0) {
		LOG("socket full: %zu bytes dropped", n);
	}
}
''', '''static IOLock *up_lock;
static uint32_t trace_up, trace_down;

static void
bt_trace(const char *dir, const uint8_t *p, size_t n)
{
	char line[3 * 16 + 1];
	size_t k = n < 16 ? n : 16;
	for (size_t i = 0; i < k; i++) {
		snprintf(line + 3 * i, 4, "%02x ", p[i]);
	}
	line[3 * k] = 0;
	LOG("%s %zu: %s", dir, n, line);
}

/* one whole packet to the connected socket */
static void
ctl_up(const uint8_t *p, size_t n)
{
	if (!ctl_on) {
		return;
	}
	if (trace_up++ < 200) {
		bt_trace("up", p, n);
	}
	IOLockLock(up_lock);
	errno_t e = ctl_enqueuedata(ctl_ref, ctl_unit, (void *)(uintptr_t)p, n, 0);
	IOLockUnlock(up_lock);
	if (e != 0) {
		LOG("socket full (%d): %zu bytes dropped", e, n);
	}
}
''')
sub('''static void
tx_packet(const uint8_t *p, uint32_t n)
{''', '''static void
tx_packet(const uint8_t *p, uint32_t n)
{
	if (trace_down++ < 200) {
		bt_trace("down", p, n);
	}''')
sub('''	tx_lock = IOLockAlloc();''', '''	tx_lock = IOLockAlloc();
	up_lock = IOLockAlloc();''')
sub('''	uint8_t chunk[256];
	for (;;) {
		uint32_t n = 0;
		bt_rx_poll();
		while (rx_head != rx_tail && n < sizeof(chunk)) {
			chunk[n++] = rx_ring[rx_head++ % sizeof(rx_ring)];
		}
		if (n != 0) {
			ctl_up(chunk, n);       /* dropped when nobody is connected */
		} else {
			IOSleep(1);
		}
	}''', '''	static uint8_t pkt[4 + 65536];
	uint32_t have = 0;
	for (;;) {
		bt_rx_poll();
		if (rx_head == rx_tail) {
			IOSleep(1);
			continue;
		}
		while (rx_head != rx_tail) {
			pkt[have++] = rx_ring[rx_head++ % sizeof(rx_ring)];
			uint32_t need = 0;
			switch (pkt[0]) {
			case 0x04: need = have >= 3 ? 3u + pkt[2] : 0; break;
			case 0x02: need = have >= 5 ? 5u + (pkt[3] | (pkt[4] << 8)) : 0; break;
			case 0x03: need = have >= 4 ? 4u + pkt[3] : 0; break;
			default:
				LOG("rx: stray byte %#04x", pkt[0]);
				have = 0;
				continue;
			}
			if (need != 0 && have >= need) {
				ctl_up(pkt, need);      /* dropped when nobody is connected */
				have = 0;
			}
		}
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
