"""lavender keys: power / volume through the SDM660 SPMI arbiter v3 (src/sweet_keys.c replaces the
base series' topaz driver) and USB commands that press them: lv:power, lv:home, lv:volup, lv:voldown.

usage: python mk_keys.py XNU_TREE SWEET_KEYS_C
"""
import sys

tree, keys = sys.argv[1], sys.argv[2]
open(f'{tree}/bsd/dev/sweet_keys.c', 'w', newline='\n').write(open(keys, newline='').read())

p = f'{tree}/bsd/dev/sweet_usb.c'
s = open(p, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:60], s.count(old))
    s = s.replace(old, new)


sub('''/* One command per bulk OUT packet. */''', '''extern void sweet_hid_key(int key, int down);

/* lv:power / lv:volup / lv:voldown / lv:home: a 120 ms press of that key (SweetHID numbering). */
static void
ud_press(int key)
{
	printf("LV USB: key %d pressed by the host\\n", key);
	sweet_hid_key(key, 1);
	ud_sleep_ms(120);
	sweet_hid_key(key, 0);
}

/* One command per bulk OUT packet. */''')
sub('''	} else if (strcmp(cmd, "lv:shot") == 0) {
		ud.shot_pending = true;''', '''	} else if (strcmp(cmd, "lv:shot") == 0) {
		ud.shot_pending = true;
	} else if (strcmp(cmd, "lv:power") == 0) {
		ud_press(0);
	} else if (strcmp(cmd, "lv:volup") == 0) {
		ud_press(1);
	} else if (strcmp(cmd, "lv:voldown") == 0) {
		ud_press(2);
	} else if (strcmp(cmd, "lv:home") == 0) {
		ud_press(3);''')
open(p, 'w', newline='\n').write(s)
print('ok')
