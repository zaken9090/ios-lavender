"""lavender: touch reads 32 bytes of a report (5 fingers) and the bus speed is a boot-arg (patch 1154).

With 1153 a 65-byte report takes ~4.2 ms of spinning, every ~8 ms while a finger is down: half a core of
the four, beside backboardd's drawing thread. The first 32 bytes hold fingers 1-5 (6 bytes each); the
rest is zeroed before parsing, so slots 6-10 read as empty. sweettouch_len=65: all ten fingers.
sweettouch_half_us (default 2): half an SCL period in microseconds (1: ~2x faster bus).

usage: python mk_touchshort.py XNU_TREE
"""
import re
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_touch.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#define HALF_US         2u              /* half an SCL period */''',
    '''static uint32_t lv_half_us = 2;         /* half an SCL period; boot-arg sweettouch_half_us (xnu/src/mk_touchshort.py) */
#define HALF_US         lv_half_us''')
sub('''			if (i2c_read(NVT_ADDR, 0x00, r, NVT_REPORT_LEN) == 0) {''',
    '''			bzero(r, sizeof(r));            /* lavender: unread finger slots are empty (mk_touchshort.py) */
			if (i2c_read(NVT_ADDR, 0x00, r, lv_report_len) == 0) {''')
sub('''	PE_parse_boot_argn("sweettouch_edge", &edge, sizeof(edge));''', '''	PE_parse_boot_argn("sweettouch_edge", &edge, sizeof(edge));
	/* lavender: 32 bytes (fingers 1-5) and the bus speed (xnu/src/mk_touchshort.py) */
	uint32_t lv_report_len = 32;
	PE_parse_boot_argn("sweettouch_len", &lv_report_len, sizeof(lv_report_len));
	if (lv_report_len < 8 || lv_report_len > NVT_REPORT_LEN) {
		lv_report_len = NVT_REPORT_LEN;
	}
	PE_parse_boot_argn("sweettouch_half_us", &lv_half_us, sizeof(lv_half_us));
	if (lv_half_us == 0 || lv_half_us > 10) {
		lv_half_us = 2;
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
