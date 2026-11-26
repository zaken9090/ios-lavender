"""lavender: an SError is recorded instead of a panic while the modem is brought up (patch 1047).

Starts 2 and 3 of the modem (kernels 45733753598, 45758664562) ended the same way: the instant the
Q6 core is released the kernel panics "Unhandled implementation specific error" - an SError, with
no register in the panic text. With lv_serror=1 (set it together with modem=1) the first 32 are
not fatal: ESR, FAR, pc, lr and the CPU are stored in lv_serror_* and the modem code prints them
(nothing is printed from the exception itself), together with the tail of TrustZone's log, which
names the master and the address of an access-control violation.

- osfmk/arm64/sleh.c arm64_platform_error(): the record; panic as before without the boot-arg
- TopazModem.cpp: lv_serror_report(), tz_log_tail(), called after the wait for the boot ROM

usage: python mk_serror.py XNU_TREE   (after mk_modemqdss.py)
"""
import sys

tree = sys.argv[1]


def patch(rel, pairs):
    path = f'{tree}/{rel}'
    s = open(path, newline='').read()
    for old, new in pairs:
        assert s.count(old) == 1, (rel, old[:70], s.count(old))
        s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


patch('osfmk/arm64/sleh.c', [('''#include <pexpert/arm/protos.h>
''', '''#include <pexpert/arm/protos.h>
#include <pexpert/pexpert.h>
'''), ('''	} else {
		arm64_implementation_specific_error(state, esr, far);
	}
}
''', '''	} else {
		/* lavender (xnu/src/mk_serror.py): lv_serror=1 records the first SErrors instead of a panic */
		static int lv_serror_on = -1;
		if (lv_serror_on < 0) {
			uint32_t on = 0;
			(void)PE_parse_boot_argn("lv_serror", &on, sizeof(on));
			lv_serror_on = on != 0;
		}
		if (lv_serror_on && source == PLAT_ERR_SRC_ASYNC && lv_serror_count < 32) {
			if (lv_serror_count == 0) {
				lv_serror_info[0] = esr;
				lv_serror_info[1] = far;
				lv_serror_info[2] = is_saved_state64(state) ? saved_state64(state)->pc : 0;
				lv_serror_info[3] = is_saved_state64(state) ? saved_state64(state)->lr : 0;
				lv_serror_info[4] = (uint64_t)cdp->cpu_number;
			}
			lv_serror_info[5] = esr;
			lv_serror_info[6] = is_saved_state64(state) ? saved_state64(state)->pc : 0;
			lv_serror_count++;
			return;
		}
		arm64_implementation_specific_error(state, esr, far);
	}
}
'''), ('''__dead2 __unused
static void
arm64_implementation_specific_error(''', '''volatile uint32_t lv_serror_count;
volatile uint64_t lv_serror_info[7];    /* first: esr, far, pc, lr, cpu; last: esr, pc */

__dead2 __unused
static void
arm64_implementation_specific_error(''')])

patch('iokit/Kernel/arm/TopazModem.cpp', [('''#include <pexpert/pexpert.h>
''', '''#include <pexpert/pexpert.h>
#include <mach/vm_param.h>
'''), ('''extern "C" bool topaz_rpm_write(uint32_t set, uint32_t type, uint32_t id, uint32_t key, uint32_t value);
''', '''extern "C" bool topaz_rpm_write(uint32_t set, uint32_t type, uint32_t id, uint32_t key, uint32_t value);
extern "C" volatile uint32_t lv_serror_count;
extern "C" volatile uint64_t lv_serror_info[7];

static void
lv_serror_report(const char *when)
{
	uint32_t n = lv_serror_count;
	if (n == 0) {
		LOG("SError: none (%s)", when);
		return;
	}
	LOG("SError x%u (%s): first esr %#llx far %#llx pc %#llx lr %#llx cpu %llu; last esr %#llx pc %#llx (slide %#llx)", n, when,
	    lv_serror_info[0], lv_serror_info[1], lv_serror_info[2], lv_serror_info[3], lv_serror_info[4], lv_serror_info[5],
	    lv_serror_info[6], (uint64_t)vm_kernel_slide);
}

/*
 * The tail of TrustZone's diagnostic log (Linux tz_log.c): IMEM 0x146bf720 holds the address of the
 * area; its header gives the ring's offset and length; the ring starts with {wrap, offset} (16 bits each).
 */
static void
tz_log_tail(void)
{
	IOMemoryMap *p = map_phys(0x146bf000, 0x1000, false);
	if (p == NULL) {
		return;
	}
	uint32_t pa = *(volatile uint32_t *)(p->getVirtualAddress() + 0x720);
	p->release();
	LOG("TZ log: area at %#x", pa);
	if (pa < 0x80000000u || (pa & 3) != 0) {
		return;
	}
	const uint32_t area = 0x3000;
	IOMemoryMap *m = map_phys(pa & ~0x3fffull, area + 0x4000, false);
	if (m == NULL) {
		return;
	}
	volatile uint8_t *b = (volatile uint8_t *)m->getVirtualAddress() + (pa & 0x3fff);
	volatile uint32_t *h = (volatile uint32_t *)b;
	uint32_t ring_off = h[7], ring_len = h[8];
	LOG("TZ log: magic %#x version %#x cpus %u ring %#x+%#x", h[0], h[1], h[2], ring_off, ring_len);
	if (ring_off < 0x24 || ring_len < 0x40 || ring_off + 4 + ring_len > area) {
		m->release();
		return;
	}
	uint32_t pos = *(volatile uint16_t *)(b + ring_off + 2), wrap = *(volatile uint16_t *)(b + ring_off);
	volatile uint8_t *ring = b + ring_off + 4;
	uint32_t want = 3000, have = wrap != 0 ? ring_len : pos;
	if (want > have) {
		want = have;
	}
	char line[200];
	unsigned n = 0;
	for (uint32_t i = 0; i < want; i++) {
		uint8_t c = ring[(pos + ring_len - want + i) % ring_len];
		if (c == 10 || c == 13 || n == sizeof(line) - 1) {
			if (n != 0) {
				line[n] = 0;
				LOG("TZ| %s", line);
				IOSleep(2);
			}
			n = 0;
			if (c == 10 || c == 13) {
				continue;
			}
		}
		line[n++] = (c >= 0x20 && c < 0x7f) ? (char)c : '.';
	}
	if (n != 0) {
		line[n] = 0;
		LOG("TZ| %s", line);
	}
	m->release();
}
'''), ('''	int32_t pbl = mss_wait(0x04, 0, 1000);
''', '''	int32_t pbl = mss_wait(0x04, 0, 1000);
	lv_serror_report("1 s after the core was released");
	if (lv_serror_count != 0 || pbl != 1) {
		tz_log_tail();
	}
''')])
print('ok')
