"""lavender: INTF_1's frame/line counters for the vsync lock (boot-arg sweetfb_lock=1) (patch 1030).

CoreAnimation's vsync ticks came from a free-running 16.7 ms timer, not from the panel. With two
display surfaces a new frame can only start once the last one is latched by the MDP (at the
panel's vsync) and the other surface is free; a tick that falls just before that costs a whole
tick (Settings ~24 fps with ~12 ms of drawing and ~11 ms of showing a frame, 2026-11-25).
SDM660's INTF_1 (DSI0) is at 0xc96b800 with the layout of topaz's DPU (block +0x800, FRAME_COUNT
0xac, LINE_COUNT 0xb0), so the base's sweetfb_lock=1 (vsyncNext(): ticks a little after the
panel's frame starts) works once the block is mapped. Only with the MDP in use (patch 1020).
The idea comes from the user's first lavender project (its patch 1001).

usage: python mk_vlock.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()
old = '''	fIntf1 = NULL;  /* lavender: no SM6225 INTF_1 */'''
assert s.count(old) == 1
s = s.replace(old, '''	/* lavender: SDM660 INTF_1 (DSI0) at 0xc96b800, counters as on topaz's DPU (xnu/src/mk_vlock.py) */
	fIntf1 = fVig0 != NULL ? (volatile uint32_t *)ml_io_map(0x0c96b000, 0x1000) : NULL;''')
open(path, 'w', newline='\n').write(s)
print('ok')
