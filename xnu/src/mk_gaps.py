"""lavender: the SWEET FPS line counts frame gaps by vsync periods (patch 1031).

"N frames in a second" mixes animation and idle time. The line gains

  ...; gaps A/B/C/D

frames that came within 1, 2, 3 and more than 3 panel periods (<=20, <=37, <=54 ms, longer) of
the frame before: A is 60 fps pacing, B 30 fps, C 20 fps.

usage: python mk_gaps.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	frames++;
	late += gap > 20000000ull;''', '''	frames++;
	late += gap > 20000000ull;
	static uint32_t lv_gaps[4];             /* lavender: gaps of 1, 2, 3, more panel periods (mk_gaps.py) */
	lv_gaps[gap <= 20000000ull ? 0 : gap <= 37000000ull ? 1 : gap <= 54000000ull ? 2 : 3]++;''')
sub('''came %llu us after the tick; direct %u copied %u, GPU waited %llu us a frame\\n", frames, ns / 1000000,''',
    '''came %llu us after the tick; direct %u copied %u, GPU waited %llu us a frame; gaps %u/%u/%u/%u\\n", frames, ns / 1000000,''')
sub('''		    lv_fps_direct, lv_fps_copied, lv_fps_direct ? gpu_ns / 1000 / lv_fps_direct : 0);''',
    '''		    lv_fps_direct, lv_fps_copied, lv_fps_direct ? gpu_ns / 1000 / lv_fps_direct : 0,
		    lv_gaps[0], lv_gaps[1], lv_gaps[2], lv_gaps[3]);
		lv_gaps[0] = lv_gaps[1] = lv_gaps[2] = lv_gaps[3] = 0;''')
open(path, 'w', newline='\n').write(s)
print('ok')
