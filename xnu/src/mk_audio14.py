"""lavender: audio A4b - register ranges, replaceable amplifier init, later SD0 check (patch 1132).

Runs t7-ta3 (xnu 1131): the amplifier's defaults match mainline MAX98927 (0x14=0x75, 0x15=0x8c,
0x16=0x08, 0x17=0x55), but some writes do not hold (0x22, 0x24, 0x3f, 0x42, 0x82-0x87) and
GLOBAL_EN (0x00FF) reads 0 after writing 1; SD0 data was seen in one run, not in others - the
check ran right after RUN, possibly before the first samples.

Boot-arg room is short (608 bytes for the whole command line, ~165 free), so:
- audio_amp_read takes ranges too: "0x0-0x2f,0xff"
- audio_amp_init="reg=val,..." replaces the built-in init table (after reset release + REV read;
  a soft reset is not done unless listed: "0x100=1")
- SD0 is sampled 500 ms after the amplifier is switched on, and again at the end.

usage: python mk_audio14.py XNU_TREE   (after mk_audio13.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


ta = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
# ranges in amp_list_read
patch(ta, '''		n += (unsigned)snprintf(line + n, sizeof(line) - n, "%lx=%x ", r, lv_amp_read((uint16_t)r));
		p = *e == ',' ? e + 1 : e;''', '''		unsigned long to = r;
		if (*e == '-') {
			to = lv_num(e + 1, &e);
		}
		for (unsigned long q = r; q <= to && q < r + 64 && n < sizeof(line) - 16; q++) {
			n += (unsigned)snprintf(line + n, sizeof(line) - n, "%lx=%x ", q, lv_amp_read((uint16_t)q));
		}
		p = *e == ',' ? e + 1 : e;''')
patch(ta, '''	char line[256];
	unsigned n = 0;
	const char *p = buf;''', '''	char line[512];
	unsigned n = 0;
	const char *p = buf;''')
# SD0 later
patch(ta, '''			LOG("A4b: read back AMP_EN %#x GLOBAL_EN %#x", lv_amp_read(0x003A), lv_amp_read(0x00FF));
			sd0_sample();''', '''			LOG("A4b: read back AMP_EN %#x GLOBAL_EN %#x", lv_amp_read(0x003A), lv_amp_read(0x00FF));
			for (unsigned w0 = ms(); ms() - w0 < 500;) {
				if (!glink_poll()) {
					IODelay(200);
				}
			}
			sd0_sample();''')
patch(ta, '''			LOG("A4b: amp off: GLOBAL_EN %d AMP_EN %d", lv_amp_write(0x00FF, 0x00), lv_amp_write(0x003A, 0x00));''',
      '''			sd0_sample();
			LOG("A4b: amp off: GLOBAL_EN %d AMP_EN %d", lv_amp_write(0x00FF, 0x00), lv_amp_write(0x003A, 0x00));''')

la = f'{tree}/iokit/Kernel/arm/LavenderAudio.cpp'
patch(la, '''	int bad = 0;
	for (unsigned i = 0; i < sizeof(init) / sizeof(init[0]); i++) {''', '''	int bad = 0;
	char alt[256];
	if (PE_parse_boot_argn("audio_amp_init", alt, sizeof(alt))) {
		/* "reg=val,..." instead of the built-in table (mk_audio14.py) */
		const char *p = alt;
		while (*p != 0) {
			unsigned long r = 0, v = 0;
			int base = 10;
			if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) { base = 16; p += 2; }
			for (; *p != 0 && *p != '='; p++) { r = r * base + (unsigned long)(*p <= '9' ? *p - '0' : (*p | 0x20) - 'a' + 10); }
			if (*p != '=') { break; }
			p++;
			base = 10;
			if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) { base = 16; p += 2; }
			for (; *p != 0 && *p != ','; p++) { v = v * base + (unsigned long)(*p <= '9' ? *p - '0' : (*p | 0x20) - 'a' + 10); }
			int w = lv_amp_write((uint16_t)r, (uint8_t)v);
			bad += w != 0;
			if (r == 0x100) {
				IOSleep(2);
			}
			LOG("audio_amp_init: 0x%04lx = 0x%02lx -> %d (read back %#x)", r, v, w, lv_amp_read((uint16_t)r));
			if (*p == ',') { p++; }
		}
		LOG("max98927: boot-arg init table, %d NAKs", bad);
		return bad == 0;
	}
	for (unsigned i = 0; i < sizeof(init) / sizeof(init[0]); i++) {''')
print('ok')
