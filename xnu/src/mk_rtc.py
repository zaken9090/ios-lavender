"""lavender clock: the PM660 RTC (0x6000, seconds counter) is the platform's time of day.

- sweet_usb.c: sweet_rtc_get() / sweet_rtc_set() over the SPMI code that is already there (one cached
  channel mapping per peripheral instead of a new mapping per access); USB command "lv:time SECS"
  sets the calendar (and with it the RTC) from the host.
- SweetPlatformExpert: getGMTTimeOfDay / setGMTTimeOfDay use them, so the calendar starts from the
  RTC at boot and iOS's own time changes (Settings) are kept in the RTC.
Android never writes this RTC (DT qcom,qpnp-rtc-write = 0, it keeps an offset instead), so a set
may be refused by the arbiter; it is logged.

usage: python mk_rtc.py XNU_TREE
"""
import sys

tree = sys.argv[1]


def edit(rel, pairs):
    p = f'{tree}/{rel}'
    s = open(p, newline='').read()
    for old, new in pairs:
        assert s.count(old) == 1, (rel, old[:70], s.count(old))
        s = s.replace(old, new)
    open(p, 'w', newline='\n').write(s)


RTC = r'''
/*
 * lavender: PM660 RTC (DT qcom,pm660_rtc_rw@6000): a running count of seconds.
 * 0x6040..43 write data, 0x6046 bit 7 enable, 0x6048..4b read data (little endian).
 */
#define RTC_WDATA       0x6040
#define RTC_CTRL        0x6046
#define RTC_RDATA       0x6048

static int
rtc_read32(uint32_t *out)
{
	uint8_t b[4], again = 0;
	for (int tries = 0; tries < 3; tries++) {
		for (int i = 0; i < 4; i++) {
			if (spmi_byte(false, RTC_RDATA + i, &b[i]) != 0) {
				return -1;
			}
		}
		if (spmi_byte(false, RTC_RDATA, &again) != 0) {
			return -1;
		}
		if (again == b[0]) {    /* no carry out of byte 0 while reading */
			*out = (uint32_t)b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16 | (uint32_t)b[3] << 24;
			return 0;
		}
	}
	return -1;
}

int
sweet_rtc_get(uint32_t *secs)
{
	uint8_t ctrl = 0;
	int r = spmi_byte(false, RTC_CTRL, &ctrl);
	if (r == 0) {
		r = rtc_read32(secs);
	}
	printf("SWEET RTC: read %u (ctrl %#x) -> %d\n", r == 0 ? *secs : 0, ctrl, r);
	return r != 0 || !(ctrl & 0x80) ? -1 : 0;
}

int
sweet_rtc_set(uint32_t secs)
{
	uint8_t v[4] = { (uint8_t)secs, (uint8_t)(secs >> 8), (uint8_t)(secs >> 16), (uint8_t)(secs >> 24) };
	uint8_t zero = 0;
	uint32_t back = 0;
	/* qpnp-rtc order: stop, byte 0 = 0, bytes 1..3, byte 0, start */
	int r = spmi_update(RTC_CTRL, 0x80, 0);
	if (r == 0) {
		r = spmi_byte(true, RTC_WDATA, &zero);
	}
	for (int i = 1; r == 0 && i < 4; i++) {
		r = spmi_byte(true, RTC_WDATA + i, &v[i]);
	}
	if (r == 0) {
		r = spmi_byte(true, RTC_WDATA, &v[0]);
	}
	int e = spmi_update(RTC_CTRL, 0x80, 0x80);      /* always restart the counter */
	if (r == 0) {
		r = e;
	}
	if (r == 0) {
		r = rtc_read32(&back);
	}
	printf("SWEET RTC: set %u -> %d, reads back %u\n", secs, r, back);
	return r;
}

/* "lv:time SECS": seconds since 1970 (UTC) from the host. */
static void
ud_set_time(const char *arg)
{
	uint64_t secs = 0;
	while (*arg == ' ') {
		arg++;
	}
	for (; *arg >= '0' && *arg <= '9'; arg++) {
		secs = secs * 10 + (uint64_t)(*arg - '0');
	}
	if (secs < 1600000000ULL || secs > 0xffffffffULL) {
		printf("LV USB: lv:time: bad value\n");
		return;
	}
	printf("LV USB: calendar set to %llu by the host\n", secs);
	clock_set_calendar_microtime((clock_sec_t)secs, 0);
}
'''

edit('bsd/dev/sweet_usb.c', [
    # one mapping per channel, not one per access
    ('''	vm_offset_t ch = ml_io_map((write ? SPMI_CHNLS_PA : SPMI_OBSRVR_PA) + 0x8000u * (uint32_t)channel, 0x1000);
	if (ch == 0) {
		return -1;
	}''', '''	static vm_offset_t maps[2][512];
	vm_offset_t ch = maps[write][channel];
	if (ch == 0) {
		ch = ml_io_map((write ? SPMI_CHNLS_PA : SPMI_OBSRVR_PA) + 0x8000u * (uint32_t)channel, 0x1000);
		maps[write][channel] = ch;
	}
	if (ch == 0) {
		return -1;
	}'''),
    ('''/* One command per bulk OUT packet. */''', RTC.lstrip('\n') + '''
/* One command per bulk OUT packet. */'''),
    ('''	} else if (strcmp(cmd, "lv:power") == 0) {''', '''	} else if (strncmp(cmd, "lv:time ", 8) == 0) {
		ud_set_time(cmd + 8);
	} else if (strcmp(cmd, "lv:power") == 0) {'''),
])

edit('iokit/Kernel/arm/SweetPlatformExpert.cpp', [
    ('''extern "C" void sweet_usb_probe(void);''', '''extern "C" void sweet_usb_probe(void);
extern "C" int sweet_rtc_get(uint32_t *secs);
extern "C" int sweet_rtc_set(uint32_t secs);'''),
    ('''	const char *excludeList(void) APPLE_KEXT_OVERRIDE;
};''', '''	const char *excludeList(void) APPLE_KEXT_OVERRIDE;
	long getGMTTimeOfDay(void) APPLE_KEXT_OVERRIDE;
	void setGMTTimeOfDay(long secs) APPLE_KEXT_OVERRIDE;
};'''),
    ('''const char *
SweetPlatformExpert::deleteList(void)''', '''/* lavender: the calendar lives in the PM660 RTC (bsd/dev/sweet_usb.c). */
long
SweetPlatformExpert::getGMTTimeOfDay(void)
{
	uint32_t secs = 0;
	return sweet_rtc_get(&secs) == 0 ? (long)secs : 0;
}

void
SweetPlatformExpert::setGMTTimeOfDay(long secs)
{
	if (secs > 0 && secs <= 0xffffffffL) {
		(void)sweet_rtc_set((uint32_t)secs);
	}
}

const char *
SweetPlatformExpert::deleteList(void)'''),
])
print('ok')
