"""lavender: audio A4b - tunables as boot-args, data-line check (patch 1129).

Run t3 (xnu 1128, audio_secs=10): 501 WRITE_DONE in 10 s, no error, amplifier enable acked - and
the user heard nothing (iOS volume plays no part: this path is kernel -> ADSP -> amplifier).

To find out why without a kernel build per try (user's rule: tunables are boot-args):
- audio_amp="0xRRRR=0xVV,..."     amplifier writes after the init table (before the stream)
- audio_amp_on="0xRRRR=0xVV,..."  amplifier writes instead of AMP_EN=1, GLOBAL_EN=1 at start
- audio_amp_read="0xRRRR,..."     amplifier registers logged every second while playing
                                  (default: 0x003A,0x00FF,0x0011,0x0001-0x0006)
- audio_level=N                   tone peak (default 8192, at most 30000)
- audio_freq=N                    tone frequency in Hz, one of 250/500/1000/2000/4000 (default 1000)
Checks added: after enabling, 0x003A and 0x00FF are read back; while playing, GPIO 14 (SD0, the
data line to the amplifier) is sampled 20000 times - the count of level changes tells whether
non-silent data leaves the SoC (silence: SD0 stays low).

usage: python mk_audio11.py XNU_TREE   (after mk_audio10.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


# helpers before a4b_buffers
sub('''static bool
a4b_buffers(void)
{''', r'''/* a number: 0x.. hex or decimal (own parser: no libc here) */
static unsigned long
lv_num(const char *p, char **end)
{
	unsigned long v = 0;
	int base = 10;
	if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
		base = 16;
		p += 2;
	}
	for (;; p++) {
		int d = (*p >= '0' && *p <= '9') ? *p - '0' : (base == 16 && *p >= 'a' && *p <= 'f') ? *p - 'a' + 10 :
		    (base == 16 && *p >= 'A' && *p <= 'F') ? *p - 'A' + 10 : -1;
		if (d < 0) {
			break;
		}
		v = v * (unsigned long)base + (unsigned long)d;
	}
	*end = (char *)(uintptr_t)p;
	return v;
}

/* "0x3a=0x1,0xff=0x1": hex/dec pairs; writes them to the amplifier (mk_audio11.py) */
static void
amp_list_write(const char *arg)
{
	char buf[256];
	if (!PE_parse_boot_argn(arg, buf, sizeof(buf))) {
		return;
	}
	const char *p = buf;
	while (*p != 0) {
		char *e;
		unsigned long r = lv_num(p, &e);
		if (*e != '=') {
			break;
		}
		unsigned long v = lv_num(e + 1, &e);
		LOG("%s: 0x%04lx = 0x%02lx -> %d (read back %#x)", arg, r, v, lv_amp_write((uint16_t)r, (uint8_t)v), lv_amp_read((uint16_t)r));
		p = *e == ',' ? e + 1 : e;
		if (*e != ',') {
			break;
		}
	}
}

static void
amp_list_read(void)
{
	char buf[256] = "0x3a,0xff,0x11,0x1,0x2,0x3,0x4,0x5,0x6";
	(void)PE_parse_boot_argn("audio_amp_read", buf, sizeof(buf));
	char line[256];
	unsigned n = 0;
	const char *p = buf;
	while (*p != 0 && n < sizeof(line) - 16) {
		char *e;
		unsigned long r = lv_num(p, &e);
		if (e == p) {
			break;
		}
		n += (unsigned)snprintf(line + n, sizeof(line) - n, "%lx=%x ", r, lv_amp_read((uint16_t)r));
		p = *e == ',' ? e + 1 : e;
		if (*e != ',') {
			break;
		}
	}
	line[n] = 0;
	LOG("max98927 playing: %s", line);
}

/* GPIO 14 = SD0: level changes over 20000 reads (silence keeps it low) */
static void
sd0_sample(void)
{
	volatile uint32_t *g = (volatile uint32_t *)ml_io_map(0x03900000 + 0x1000 * 14, 0x1000);
	if (g == NULL) {
		return;
	}
	unsigned hi = 0, edges = 0, last = g[1] & 1;
	for (unsigned i = 0; i < 20000; i++) {
		unsigned v = g[1] & 1;
		hi += v;
		edges += v != last;
		last = v;
	}
	LOG("SD0 (GPIO 14): %u of 20000 high, %u level changes", hi, edges);
}

static bool
a4b_buffers(void)
{''')
# tone with level/frequency
sub('''	for (unsigned b = 0; b < A4_BUF_N; b++) {
		int16_t *s16 = (int16_t *)(a4_va + 4096u * b);
		for (unsigned f = 0; f < A4_BUF_BYTES / 4; f++) {
			s16[2 * f] = s16[2 * f + 1] = sine[f % 48];
		}
	}''', '''	uint32_t level = 8192, freq = 1000;
	(void)PE_parse_boot_argn("audio_level", &level, sizeof(level));
	(void)PE_parse_boot_argn("audio_freq", &freq, sizeof(freq));
	level = level > 30000 ? 30000 : level;
	/* 960 frames a buffer: 250/500/1000/2000/4000 Hz give whole cycles (step through the 48-point table) */
	uint32_t step = freq == 250 ? 0 : freq == 500 ? 0 : freq == 2000 ? 2 : freq == 4000 ? 4 : 1;
	uint32_t slow = freq == 250 ? 4 : freq == 500 ? 2 : 1;
	for (unsigned b = 0; b < A4_BUF_N; b++) {
		int16_t *s16 = (int16_t *)(a4_va + 4096u * b);
		for (unsigned f = 0; f < A4_BUF_BYTES / 4; f++) {
			unsigned k = step != 0 ? (f * step) % 48 : (f / slow) % 48;
			int32_t v = (int32_t)sine[k] * (int32_t)level / 8192;
			s16[2 * f] = s16[2 * f + 1] = (int16_t)v;
		}
	}
	LOG("A4b: tone %u Hz, peak %u", freq, level);''')
sub('''			LOG("A4b: amp on: AMP_EN %d GLOBAL_EN %d", lv_amp_write(0x003A, 0x01), lv_amp_write(0x00FF, 0x01));''',
    '''			char on[8];
			if (PE_parse_boot_argn("audio_amp_on", on, sizeof(on))) {
				amp_list_write("audio_amp_on");
			} else {
				LOG("A4b: amp on: AMP_EN %d GLOBAL_EN %d", lv_amp_write(0x003A, 0x01), lv_amp_write(0x00FF, 0x01));
			}
			LOG("A4b: read back AMP_EN %#x GLOBAL_EN %#x", lv_amp_read(0x003A), lv_amp_read(0x00FF));
			sd0_sample();''')
sub('''				if (ms() - last >= 1000) {
					last = ms();
					amp_status("playing");
				}''', '''				if (ms() - last >= 1000) {
					last = ms();
					amp_list_read();
				}''')
# extra amp writes after the init table: in a4b_play before the SMMU
sub('''	if (!lpass_smmu_sid1() || !a4b_buffers()) {
		return;
	}''', '''	amp_list_write("audio_amp");
	if (!lpass_smmu_sid1() || !a4b_buffers()) {
		return;
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
