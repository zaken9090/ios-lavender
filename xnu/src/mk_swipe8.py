"""lavender: lv:swipe moves in 8 ms steps, as the touch chip reports a finger (patch 1151).

Injected swipes stepped every 16 ms; the first lavender project's (and the NT36672A with a finger down)
every 8 ms. The bench now drags slowly like a finger (tools/bench.py), so the steps should come at a
finger's rate too. boot-arg lv_swipe_ms (default 8, 4..33).

usage: python mk_swipe8.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_usb.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		int steps = v[4] / 16 > 0 ? v[4] / 16 : 1;
		for (int i = 1; i <= steps; i++) {
			ud_sleep_ms(16);''', '''		/* lavender: a finger's report rate (xnu/src/mk_swipe8.py) */
		static int step_ms;
		if (step_ms == 0) {
			step_ms = 8;
			PE_parse_boot_argn("lv_swipe_ms", &step_ms, sizeof(step_ms));
			if (step_ms < 4 || step_ms > 33) {
				step_ms = 8;
			}
		}
		int steps = v[4] / step_ms > 0 ? v[4] / step_ms : 1;
		for (int i = 1; i <= steps; i++) {
			ud_sleep_ms((unsigned)step_ms);''')
open(path, 'w', newline='\n').write(s)
print('ok')
