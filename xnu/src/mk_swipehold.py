"""lavender: lv:swipe X1 Y1 X2 Y2 MS [HOLD] - the finger stays HOLD ms at the end before it lifts (patch 1159).

The app switcher opens on a swipe up from the bottom edge that pauses before the finger lifts; injected
swipes lifted at once and only went home. With HOLD (0..3000 ms, optional) the end position is repeated
every 8 ms for that long, as a finger held still.

usage: python mk_swipehold.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_usb.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	int v[5] = {0, 0, 0, 0, 0};
	int need = swipe ? 5 : 2;
	if (ud_numbers(arg, v, need) != need || v[0] >= 1080 || v[1] >= 2340 ||''', '''	int v[6] = {0, 0, 0, 0, 0, 0};
	int need = swipe ? 5 : 2;
	int got = ud_numbers(arg, v, swipe ? 6 : 2);      /* lavender: an optional HOLD (xnu/src/mk_swipehold.py) */
	if (got < need || v[0] >= 1080 || v[1] >= 2340 ||''')
sub('''		sweet_hid_touch(9, 0, v[2], v[3]);
	} else {''', '''		for (int held = 0; got >= 6 && held < v[5] && held < 3000; held += 8) {
			ud_sleep_ms(8);
			sweet_hid_touch(9, 1, v[2], v[3]);
		}
		sweet_hid_touch(9, 0, v[2], v[3]);
	} else {''')
open(path, 'w', newline='\n').write(s)
print('ok')
