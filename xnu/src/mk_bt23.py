"""lavender: Bluetooth UART - the stale event needs its IMR bit (patch 1107).

Run e117 (xnu 1106): the stuck-packet log shows the tails missing: 485 of 486, 4 of 7, 13 of 15
bytes - the last, partial FIFO word. UARTDM hands a partial word out only after the stale event,
and (as in Linux msm_poll_get_char_dm, which looks at UART_MISR) the event is latched only with
RXSTALE enabled in IMR; IMR was 0 and FORCE_STALE alone did not help.

Now IMR = RXSTALE (bit 3) whenever the UART is set up; the UART's interrupt is not routed in the
GIC (nothing registered), so this only lets the status latch. bt_rx_poll() looks at MISR and ISR.

usage: python mk_bt23.py XNU_TREE   (after mk_bt22.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	wr(uart, U_IMR, 0);
''', '''	wr(uart, U_IMR, 1u << 3);                                /* RXSTALE latched (no IRQ routed) */
''')
sub('''	if (rd(uart, U_ISR) & MISR_RXSTALE) {''', '''	if ((rd(uart, U_ISR) | rd(uart, 0x10 /* MISR */)) & MISR_RXSTALE) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
