"""lavender: Bluetooth B3/B4 - the UART kernel control iOS talks to (patch 1095).

What the iPhone X user space expects (static analysis of BlueTool, bluetoothd and the kernel
cache's AppleOnboardSerial, docs/BT-PLAN.md):
- kernel control "com.apple.uart.bluetooth": SOCK_STREAM, recvsize 64 KiB; socket(PF_SYSTEM,
  SOCK_STREAM, SYSPROTO_CONTROL) + CTLIOCGINFO + connect(unit 0). One user at a time (EBUSY).
- sockopts at level 2 whose number is the tty ioctl: TIOCGETA 0x40487413 / TIOCSETA 0x80487414
  with the 64-bit termios (0x48 bytes): raw, speed, CRTSCTS. Anything else: ENOPROTOOPT.
- read/write: the plain H4 byte stream (0x01 commands, 0x02 ACL, 0x04 events).
- BlueTool's boot script is Broadcom's (FC18 baud, FC2E + records + FC4E firmware, FC01 address,
  FC27 sleep, calibration); every command needs Command Complete, ncmd 1, status 0.
  bluetoothd itself uses BT_HCI_TRANSPORT=H4BC:POSIX:com.apple.uart.bluetooth,<speed> (launchd
  job environment) and then the same control with plain read/write - no Skywalk.

Here (after bt_setup() has the Qualcomm firmware up):
- the control is registered; data written by user space is cut into H4 packets; commands with a
  vendor opcode (OGF 0x3F, >= 0xFC00 - Broadcom's) are answered at once with Command Complete
  status 0 and never reach the Qualcomm chip (its firmware, baud and address are already set by
  the kernel); everything else goes to the UART as is. The first 64 vendor opcodes are logged.
- a pump thread moves what the chip sends to the connected socket (polled every 1 ms for now).
- termios is stored and given back; the host UART stays at 115200 with RTS/CTS (B2).

usage: python mk_bt11.py XNU_TREE   (after mk_bt10.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('#include <IOKit/IODeviceTreeSupport.h>\n', '''#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLocks.h>
#include <sys/errno.h>
#include <sys/kern_control.h>
#include <sys/kpi_mbuf.h>
''')

sub('''	bt_setup();
	thread_terminate(current_thread());
}
''', '''	bt_setup();
	bt_serve();
	thread_terminate(current_thread());
}
''')

sub('''static void
bt_thread(''', r'''/* ---- B3/B4: kernel control "com.apple.uart.bluetooth" (AppleOnboardSerial's contract) */
static kern_ctl_ref ctl_ref;
static volatile bool ctl_on, bt_ready;
static uint32_t ctl_unit;
static IOLock *tx_lock;
static uint8_t termios_saved[0x48];
static uint8_t tx_pkt[2048];
static uint32_t tx_have, vendor_logged;

static void
ctl_up(const uint8_t *p, size_t n)
{
	if (ctl_on && ctl_enqueuedata(ctl_ref, ctl_unit, (void *)(uintptr_t)p, n, 0) != 0) {
		LOG("socket full: %zu bytes dropped", n);
	}
}

/* one whole H4 packet from user space */
static void
tx_packet(const uint8_t *p, uint32_t n)
{
	if (p[0] == 0x01 && n >= 4) {
		uint16_t op = (uint16_t)(p[1] | (p[2] << 8));
		if (op >= 0xFC00) {
			/* Broadcom vendor command (boot script, calibration): done by the kernel already */
			uint8_t cc[7] = { 0x04, 0x0e, 0x04, 0x01, p[1], p[2], 0x00 };
			if (vendor_logged++ < 64) {
				LOG("vendor %#06x (%u bytes): answered here", op, p[3]);
			}
			ctl_up(cc, sizeof(cc));
			return;
		}
	}
	bt_put(p, n);
}

/* user space -> chip: cut the stream into H4 packets */
static errno_t
btc_send(kern_ctl_ref, u_int32_t, void *, mbuf_t m, int)
{
	IOLockLock(tx_lock);
	for (mbuf_t b = m; b != NULL; b = mbuf_next(b)) {
		const uint8_t *d = (const uint8_t *)mbuf_data(b);
		for (size_t i = 0; i < mbuf_len(b); i++) {
			tx_pkt[tx_have++] = d[i];
			uint32_t need = 0;
			switch (tx_pkt[0]) {
			case 0x01: need = tx_have >= 4 ? 4u + tx_pkt[3] : 0; break;
			case 0x02: need = tx_have >= 5 ? 5u + (tx_pkt[3] | (tx_pkt[4] << 8)) : 0; break;
			case 0x03: need = tx_have >= 4 ? 4u + tx_pkt[3] : 0; break;
			default: need = 1; break;               /* not H4: pass the byte on */
			}
			if (need > sizeof(tx_pkt)) {
				LOG("tx: packet of %u bytes too long, dropped", need);
				tx_have = 0;
			} else if (need != 0 && tx_have >= need) {
				tx_packet(tx_pkt, need);
				tx_have = 0;
			}
		}
	}
	IOLockUnlock(tx_lock);
	mbuf_freem(m);
	return 0;
}

static errno_t
btc_connect(kern_ctl_ref, struct sockaddr_ctl *sac, void **)
{
	if (!bt_ready || ctl_on) {
		return EBUSY;
	}
	ctl_unit = sac->sc_unit;
	tx_have = 0;
	ctl_on = true;
	LOG("com.apple.uart.bluetooth: connected (unit %u)", ctl_unit);
	return 0;
}

static errno_t
btc_disconnect(kern_ctl_ref, u_int32_t, void *)
{
	ctl_on = false;
	LOG("com.apple.uart.bluetooth: disconnected");
	return 0;
}

static errno_t
btc_setopt(kern_ctl_ref, u_int32_t, void *, int opt, void *data, size_t len)
{
	if ((uint32_t)opt == 0x80487414u || (uint32_t)opt == 0x80487415u || (uint32_t)opt == 0x80487416u) {
		if (len != sizeof(termios_saved) || data == NULL) {
			return EINVAL;
		}
		memcpy(termios_saved, data, sizeof(termios_saved));
		uint64_t cflag, ispeed;
		memcpy(&cflag, termios_saved + 0x10, 8);
		memcpy(&ispeed, termios_saved + 0x38, 8);
		LOG("termios: speed %llu cflag %#llx (host UART stays 115200, RTS/CTS)", ispeed, cflag);
		return 0;
	}
	return ENOPROTOOPT;
}

static errno_t
btc_getopt(kern_ctl_ref, u_int32_t, void *, int opt, void *data, size_t *len)
{
	if ((uint32_t)opt == 0x40487413u) {
		if (data != NULL) {
			if (*len != sizeof(termios_saved)) {
				return EINVAL;
			}
			memcpy(data, termios_saved, sizeof(termios_saved));
		}
		*len = sizeof(termios_saved);
		return 0;
	}
	return ENOPROTOOPT;
}

/* after the firmware: register the control and move the chip's bytes up */
static void
bt_serve(void)
{
	struct kern_ctl_reg reg;
	bzero(&reg, sizeof(reg));
	strlcpy(reg.ctl_name, "com.apple.uart.bluetooth", sizeof(reg.ctl_name));
	reg.ctl_flags = CTL_FLAG_REG_SOCK_STREAM;
	reg.ctl_recvsize = 0x10000;
	reg.ctl_connect = btc_connect;
	reg.ctl_disconnect = btc_disconnect;
	reg.ctl_send = btc_send;
	reg.ctl_setopt = btc_setopt;
	reg.ctl_getopt = btc_getopt;
	tx_lock = IOLockAlloc();
	/* termios as a tty would start: 115200 8N1, CREAD|CLOCAL|CRTSCTS */
	uint64_t cflag = 0x38B00, speed = 115200;
	memcpy(termios_saved + 0x10, &cflag, 8);
	memcpy(termios_saved + 0x38, &speed, 8);
	memcpy(termios_saved + 0x40, &speed, 8);
	errno_t e = ctl_register(&reg, &ctl_ref);
	LOG("com.apple.uart.bluetooth: registered (%d)", e);
	if (e != 0) {
		return;
	}
	bt_ready = true;
	uint8_t chunk[256];
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
	}
}

static void
bt_thread(''')
open(path, 'w', newline='\n').write(s)
print('ok')
