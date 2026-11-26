"""lavender: Bluetooth UART - IPR.RXSTALE_LAST, the stale event at last (patch 1112).

Run e124 (xnu 1111): at a stuck packet RXFS = 0x80 / 0x180 (1 / 3 bytes in the packing buffer,
bits 9:7), SNAP 0, ISR 0x82a3 unchanged, MISR 0, and FORCE_STALE changed nothing: the stale
event never fires, so the bytes of a partial word stay in the UART.

Linux msm_serial (msm_set_termios) programs IPR as STALE_LSB (rxstale & 0x1f) | RXSTALE_LAST
(0x20) | STALE_TIMEOUT_MSB ((rxstale << 2) & 0xffffff80); we wrote 31 only, without
RXSTALE_LAST. Now IPR = 31 | 0x20.

usage: python mk_bt28.py XNU_TREE   (after mk_bt27.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()
old = '''	wr(uart, U_IPR, 31 | (0 << 7));                          /* stale timeout */'''
assert s.count(old) == 1
s = s.replace(old, '''	wr(uart, U_IPR, 31 | 0x20);                              /* stale timeout 31, RXSTALE_LAST (msm_serial) */''')
open(path, 'w', newline='\n').write(s)
print('ok')
