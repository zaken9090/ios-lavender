"""lavender: a copied frame goes on the panel only once it is complete (patch 1023).

With direct frames (patch 1020) a frame the MDP cannot show by itself (several layers: the app
switcher, dimming) still takes the copy path into the splash buffer. That path pointed VIG0 back
at the splash first and then composed the layers into it: the panel showed what the splash held
meanwhile - the kernel console from boot - and then the copy drawn top-down ("the screen switched
between iOS and the console", 2026-11-25). Now, without flip buffers (lavender's RAM is above
4 GiB), the splash is composed while VIG0 still shows the last direct frame, and VIG0 is pointed
at it after the last layer.

usage: python mk_mdpswitch.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	uint8_t *dst = fFlip[0] != NULL ? backBuffer() : (uint8_t *)fPixels;
	if (fFlip[0] == NULL && fVig0 != NULL && fScanPhys != fBootSrc) {
		scanFrom(fBootSrc, fBootStride);
	}
''', '''	uint8_t *dst = fFlip[0] != NULL ? backBuffer() : (uint8_t *)fPixels;
	/* lavender: VIG0 goes back to the splash only after the frame is composed there (below; mk_mdpswitch.py) */
''')
sub('''		s->release();
	}
	if (fFlip[0] != NULL) {
		flipBack();
	}
}''', '''		s->release();
	}
	if (fFlip[0] != NULL) {
		flipBack();
	} else if (fVig0 != NULL && fScanPhys != fBootSrc) {
		scanFrom(fBootSrc, fBootStride);        /* lavender: the composed frame, complete */
	}
}''')
open(path, 'w', newline='\n').write(s)
print('ok')
