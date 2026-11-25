"""lavender: touch input from the host for automated tests.

USB commands (panel pixels, 1080x2340, the same space as the real touch screen):
  lv:tap X Y                 finger down and up 80 ms later
  lv:swipe X1 Y1 X2 Y2 MS    finger moves in a straight line over MS milliseconds (16 ms steps)
Finger 9 (the touch screen uses 0..9 from slot 0 up, so 9 does not collide in practice).

usage: python mk_input.py XNU_TREE
"""
import sys

tree = sys.argv[1]
p = f'{tree}/bsd/dev/sweet_usb.c'
s = open(p, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:60], s.count(old))
    s = s.replace(old, new)


sub('''/* One command per bulk OUT packet. */''', '''extern void sweet_hid_touch(int finger, int down, int x, int y);

/* Up to n unsigned decimal numbers from arg; returns how many were read. */
static int
ud_numbers(const char *arg, int *v, int n)
{
	int got = 0;
	while (got < n) {
		while (*arg == ' ') {
			arg++;
		}
		if (*arg < '0' || *arg > '9') {
			break;
		}
		int x = 0;
		for (; *arg >= '0' && *arg <= '9'; arg++) {
			x = x * 10 + (*arg - '0');
		}
		v[got++] = x;
	}
	return got;
}

/* lv:tap X Y / lv:swipe X1 Y1 X2 Y2 MS: a finger from the host (finger 9). */
static void
ud_touch(const char *arg, bool swipe)
{
	int v[5] = {0, 0, 0, 0, 0};
	int need = swipe ? 5 : 2;
	if (ud_numbers(arg, v, need) != need || v[0] >= 1080 || v[1] >= 2340 ||
	    (swipe && (v[2] >= 1080 || v[3] >= 2340 || v[4] > 5000))) {
		printf("LV USB: bad %s\\n", swipe ? "lv:swipe" : "lv:tap");
		return;
	}
	sweet_hid_touch(9, 1, v[0], v[1]);
	if (swipe) {
		int steps = v[4] / 16 > 0 ? v[4] / 16 : 1;
		for (int i = 1; i <= steps; i++) {
			ud_sleep_ms(16);
			sweet_hid_touch(9, 1, v[0] + (v[2] - v[0]) * i / steps, v[1] + (v[3] - v[1]) * i / steps);
		}
		sweet_hid_touch(9, 0, v[2], v[3]);
	} else {
		ud_sleep_ms(80);
		sweet_hid_touch(9, 0, v[0], v[1]);
	}
}

/* One command per bulk OUT packet. */''')
sub('''	char cmd[32];''', '''	char cmd[64];                   /* "lv:swipe 1079 2339 1079 1000 1000" is 33 */''')
sub('''	} else if (strcmp(cmd, "lv:power") == 0) {''', '''	} else if (strncmp(cmd, "lv:tap ", 7) == 0) {
		ud_touch(cmd + 7, false);
	} else if (strncmp(cmd, "lv:swipe ", 9) == 0) {
		ud_touch(cmd + 9, true);
	} else if (strcmp(cmd, "lv:power") == 0) {''')
open(p, 'w', newline='\n').write(s)
print('ok')
