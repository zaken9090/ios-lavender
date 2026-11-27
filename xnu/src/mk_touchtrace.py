"""lavender: boot-arg sweettouch_trace=1 - a line for every touch report: time, gap, read time, first finger (patch 1152).

The user sees Settings' rows judder when scrolling slowly with a finger, never with the bench's injected
drags (8 ms steps, perfect positions). To see what the chip gives - its report rate, how even the reports
come, how long our bit-banged I2C read takes, how noisy the positions are - each report while a finger is
down is logged:  TT <ms since boot> gap <us> read <us> f<id> <x>,<y> st <state>
Off by default (it is a lot of lines).

usage: python mk_touchtrace.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_touch.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	PE_parse_boot_argn("sweettouch_down_max", &down_max, sizeof(down_max));''', '''	PE_parse_boot_argn("sweettouch_down_max", &down_max, sizeof(down_max));
	/* lavender: sweettouch_trace=1 (xnu/src/mk_touchtrace.py) */
	uint32_t trace = 0;
	uint64_t trace_last = 0;
	PE_parse_boot_argn("sweettouch_trace", &trace, sizeof(trace));''')
sub('''			if (i2c_read(NVT_ADDR, 0x00, r, NVT_REPORT_LEN) == 0) {
				lt.reports++;''', '''			uint64_t t_read = mach_absolute_time();
			if (i2c_read(NVT_ADDR, 0x00, r, NVT_REPORT_LEN) == 0) {
				lt.reports++;
				if (trace) {
					uint64_t t_end = mach_absolute_time(), ns_now, ns_gap = 0, ns_read;
					absolutetime_to_nanoseconds(t_end, &ns_now);
					absolutetime_to_nanoseconds(t_end - t_read, &ns_read);
					if (trace_last != 0) {
						absolutetime_to_nanoseconds(t_end - trace_last, &ns_gap);
					}
					trace_last = t_end;
					unsigned id = r[0] >> 3, st = r[0] & 7;
					int x = (r[1] << 4) | (r[3] >> 4), y = (r[2] << 4) | (r[3] & 0x0f);
					if (st == 1 || st == 2 || any_down) {
						printf("TT %llu gap %llu read %llu f%u %d,%d st %u\\n", ns_now / 1000000, ns_gap / 1000,
						    ns_read / 1000, id, x, y, st);
					}
				}''')
open(path, 'w', newline='\n').write(s)
print('ok')
