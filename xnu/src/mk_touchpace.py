"""lavender: with a finger down, touch reads each report when its edge comes, not every 8 ms (patch 1150).

The user saw Settings' rows judder while scrolling slowly with a finger; injected swipes (lv:swipe, they
go around the chip) were smooth. With a finger down the thread read the chip every 8 ms on its own clock
while the NT36672A reports on its own: the two beat against each other, so a report was read late,
twice or not at all, and the finger's steps between frames came out uneven. Since 1145 TLMM latches
each report's rising edge; looking at that bit is a register read, so with a finger down the thread now
looks every sweettouch_down_ms (1) ms and reads only when a new report has come. If none comes for
sweettouch_down_max (30) ms it reads anyway (a lift that came without an edge). The first three touches
say how many reports came and over how long (the chip's rate).

usage: python mk_touchpace.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_touch.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	int edge = 1;
	unsigned quiet = 0, edges = 0;
	PE_parse_boot_argn("sweettouch_edge", &edge, sizeof(edge));''', '''	int edge = 1;
	unsigned quiet = 0, edges = 0;
	PE_parse_boot_argn("sweettouch_edge", &edge, sizeof(edge));
	/* lavender: with a finger down, each report as its edge comes (xnu/src/mk_touchpace.py) */
	uint32_t down_ms = 1, down_max = 30, since = 0, sessions = 0, session_reports = 0;
	uint64_t session_start = 0;
	PE_parse_boot_argn("sweettouch_down_ms", &down_ms, sizeof(down_ms));
	PE_parse_boot_argn("sweettouch_down_max", &down_max, sizeof(down_max));
	if (down_ms == 0 || down_ms > 8) {
		down_ms = 1;
	}''')
sub('''			due = latched || any_down || ++quiet >= 20;''', '''			if (any_down) {
				since += down_ms;
				due = latched || since >= down_max;
			} else {
				due = latched || ++quiet >= 20;
			}''')
sub('''		if (due) {
			quiet = 0;''', '''		if (due) {
			quiet = 0;
			since = 0;''')
sub('''			any_down = false;
			for (unsigned f = 0; f < NVT_FINGERS; f++) {
				any_down |= lt.down[f];
			}
		}
		touch_sleep_ms(any_down ? 8 : 12);''', '''			bool was_down = any_down;
			any_down = false;
			for (unsigned f = 0; f < NVT_FINGERS; f++) {
				any_down |= lt.down[f];
			}
			if (edge && any_down) {
				if (!was_down) {
					session_start = mach_absolute_time();
					session_reports = 0;
				}
				session_reports++;
			} else if (edge && was_down && sessions < 3) {
				uint64_t ns;
				absolutetime_to_nanoseconds(mach_absolute_time() - session_start, &ns);
				printf("SWEET TOUCH: touch %u: %u reports in %llu ms\\n", ++sessions, session_reports, ns / 1000000);
			}
		}
		touch_sleep_ms(any_down ? (edge ? down_ms : 8) : 12);''')
open(path, 'w', newline='\n').write(s)
print('ok')
