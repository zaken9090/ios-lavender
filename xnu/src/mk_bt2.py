"""lavender: Bluetooth B1b - chip-power rail and a UART loopback check (patch 1086).

Run e94: rails L9/L6/L19 and RF_CLK1 acked, the UART clock runs, but after the power pulses only
four zero bytes came back and no command was answered - the line looks idle-low, as from an
unpowered chip. The stock DT gives the WCN3990 one more supply, "chip-pwd" = PM660L BOB pin1
(3.6 V, pin-controlled): now voted (RPM "bobb" 1: enable, 3.6 V, pin-control voltage 1 3.6 V).
And before the pulses the UART checks itself in internal loopback (MR2 bit 7): four bytes sent
must come back, which tells a broken UART from a silent chip.

usage: python mk_bt2.py XNU_TREE   (after mk_bt1.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	LOG("RF_CLK1: %s", topaz_rpm_write(0, 0x616b6c63u, 4, 0x6e657773u, 1) ? "ok" : "FAILED");
''', '''	LOG("RF_CLK1: %s", topaz_rpm_write(0, 0x616b6c63u, 4, 0x6e657773u, 1) ? "ok" : "FAILED");
	/* chip power: PM660L BOB pin1, 3.6 V (mk_bt2.py) */
	bool b1 = topaz_rpm_write(0, 0x62626f62u, 1, 0x6e657773u, 1);
	bool b2 = topaz_rpm_write(0, 0x62626f62u, 1, 0x00007675u, 3600000);
	bool b3 = topaz_rpm_write(0, 0x62626f62u, 1, 0x31766370u, 3600000);
	LOG("BOB (chip power): enable %s, 3.6 V %s, pin voltage 1 %s", b1 ? "ok" : "FAILED", b2 ? "ok" : "FAILED", b3 ? "ok" : "FAILED");
''')
sub('''	bt_pins();
	IOSleep(10);
''', '''	bt_pins();
	IOSleep(10);
	/* UART self-test in internal loopback (MR2 bit 7) */
	bt_uart_baud(0xcc);
	wr(uart, U_MR2, rd(uart, U_MR2) | (1u << 7));
	const uint8_t probe[4] = { 0x5a, 0xa5, 0x3c, 0xc3 };
	bt_put(probe, 4);
	IOSleep(5);
	bt_drain("loopback (expect 5a a5 3c c3)", 50);
	wr(uart, U_MR2, rd(uart, U_MR2) & ~(1u << 7));
''')
open(path, 'w', newline='\n').write(s)
print('ok')
