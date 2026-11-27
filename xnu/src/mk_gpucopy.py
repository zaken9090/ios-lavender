"""lavender: boot-arg sweetfb_gpucopy=1 - a GPU frame is copied into the kernel's own buffer and that is shown (patch 1157).

A test. Settings' rows still came out doubled in exact screenshots (1156) while scrolling by finger. If
CoreAnimation draws a new frame into the GPU-pool surface the MDP is scanning (the in-use hold not
honoured), the panel shows two frames at once. With this switch the panel never scans a surface iOS can
draw into: the frame is copied (CPU, write-combined source) into one of the two flip buffers and shown
from there. Not scaled (QSEED off): the panel-sized middle of the frame, cropped. Default 0.

usage: python mk_gpucopy.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''				if (s->gpuPool) {
					/* GPU pool memory (write-combined): the MDP scans the surface itself, no copy */''', '''				/* lavender: sweetfb_gpucopy=1 - copied and shown from our buffer (xnu/src/mk_gpucopy.py) */
				static int gpucopy = -1;
				if (gpucopy < 0) {
					gpucopy = 0;
					PE_parse_boot_argn("sweetfb_gpucopy", &gpucopy, sizeof(gpucopy));
				}
				if (s->gpuPool && gpucopy && fFlip[0] != NULL) {
					uint32_t cx = s->width > fWidth ? (s->width - fWidth) / 2 : 0, cy = s->height > fHeight ? (s->height - fHeight) / 2 : 0;
					fScaleWant = false;
					flipFrom((const uint8_t *)(va + s->offset + (uint64_t)cy * s->bytesPerRow + (uint64_t)cx * 4), s->bytesPerRow);
				} else if (s->gpuPool) {
					/* GPU pool memory (write-combined): the MDP scans the surface itself, no copy */''')
open(path, 'w', newline='\n').write(s)
print('ok')
