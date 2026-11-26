"""lavender: Bluetooth control - the debug-ACL filter on the whole handle field (patch 1099).

Run e107 (xnu 1098): BlueTool's D22 boot script ran to the end with result 0 (HCI_Reset by the
chip, Read_Local_Version reported as BCM4357B1, FC2E + the HCD records + the other vendor commands
answered by the kernel), then "init"; bluetoothd connected (termios 3000000) and left again.
But the first 0x2EDC packet still went up: 1098 masked the handle to 12 bits (0x0EDC). Linux
compares the raw 16-bit field with QCA_DEBUG_HANDLE 0x2EDC; so does this now.

usage: python mk_bt15.py XNU_TREE   (after mk_bt14.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()
old = '''				uint16_t h = (uint16_t)((pkt[1] | (pkt[2] << 8)) & 0x0fff);'''
assert s.count(old) == 1
s = s.replace(old, '''				uint16_t h = (uint16_t)(pkt[1] | (pkt[2] << 8));''')
open(path, 'w', newline='\n').write(s)
print('ok')
