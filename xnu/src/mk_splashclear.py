"""lavender: the splash buffer is black once direct frames are shown (patch 1025).

With MDP direct frames (patch 1020) the splash buffer keeps the kernel console text from boot.
Whenever VIG0 goes back to it for a moment (display off/on, a frame of several layers before its
copy covers everything) the panel showed kernel text between iOS pictures (user, 2026-11-25).
The second direct frame - the console is muted by then (sweetfb_noconsole=1) - clears the splash
buffer once, so those moments are black, or the composed frame.

usage: python mk_splashclear.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''					fScaleWant = scaled;
					scanFrom(pa, s->bytesPerRow);''', '''					fScaleWant = scaled;
					scanFrom(pa, s->bytesPerRow);
					/* lavender: no console text left in the splash for when VIG0 returns to it (mk_splashclear.py) */
					static uint32_t direct_frames;
					if (++direct_frames == 2 && sweet_console_muted && fPixels != 0) {
						for (uint32_t y = 0; y < fHeight; y++) {
							/* (plain stores: the panel memory is not the kernel's RAM, no bzero/dc zva there) */
							volatile uint32_t *row = (volatile uint32_t *)(fPixels + (uint64_t)y * fRowBytes);
							for (uint32_t x = 0; x < fWidth; x++) {
								row[x] = 0;
							}
						}
					}''')
open(path, 'w', newline='\n').write(s)
print('ok')
