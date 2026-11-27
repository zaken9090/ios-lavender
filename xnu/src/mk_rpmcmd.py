"""lavender: lv:rpm and lv:poke - an RPM request and a register write from the host (patch 1162).

For finding out how a rail or a clock is really raised without a kernel build for every try:

  lv:rpm TYPE ID KEY VALUE     one request to the RPM (active set), e.g. "lv:rpm rwcx 0 vlvl 320":
                               CX to level 0x140. TYPE and KEY are the 1-4 letter names of the stock
                               DT (rwcx, rwmx, smpb, ldoa ... / vlvl, swen, uv ...), VALUE decimal or 0x..
                               Answer: "LV RPM rwcx 0 vlvl 320: acked" (or FAILED).
  lv:poke HEXADDR HEXVALUE     one 32-bit write to device memory at a physical address.
                               Answer: "LV POKE 0x...: old -> written, reads back ...".

Both change hardware state: for experiments, one step at a time, read back with lv:peek / lv:pmic.

usage: python mk_rpmcmd.py XNU_TREE   (after mk_goldclock.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


usb = f'{tree}/bsd/dev/sweet_usb.c'
patch(usb, '''static void
ud_rx_done(void)
{''', '''/* lavender: lv:rpm TYPE ID KEY VALUE, lv:poke HEXADDR HEXVALUE (xnu/src/mk_rpmcmd.py) */
extern bool topaz_rpm_write(uint32_t set, uint32_t type, uint32_t id, uint32_t key, uint32_t value);   /* TopazRpm.cpp */

/* a name of 1-4 letters as the RPM spells it (first letter in the low byte); NULL when there is none */
static const char *
ud_fourcc(const char *s, uint32_t *v)
{
	uint32_t x = 0;
	int n = 0;

	while (*s == ' ') {
		s++;
	}
	for (; *s != 0 && *s != ' ' && n < 4; s++, n++) {
		x |= (uint32_t)(uint8_t)*s << (8 * n);
	}
	*v = x;
	return n != 0 && (*s == ' ' || *s == 0) ? s : NULL;
}

/* a number, decimal or 0x hex */
static const char *
ud_value(const char *s, uint64_t *v)
{
	int d = 0;

	while (*s == ' ') {
		s++;
	}
	if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
		return ud_hex(s, v);
	}
	if (ud_numbers(s, &d, 1) != 1) {
		return NULL;
	}
	*v = (uint64_t)d;
	while (*s >= '0' && *s <= '9') {
		s++;
	}
	return s;
}

static void
ud_rpm(const char *arg)
{
	uint32_t type = 0, key = 0;
	uint64_t id = 0, value = 0;
	const char *s = ud_fourcc(arg, &type);

	if (s == NULL || (s = ud_value(s, &id)) == NULL || (s = ud_fourcc(s, &key)) == NULL || ud_value(s, &value) == NULL) {
		printf("LV USB: bad lv:rpm (TYPE ID KEY VALUE)\\n");
		return;
	}
	bool ok = topaz_rpm_write(0, type, (uint32_t)id, key, (uint32_t)value);
	printf("LV RPM %c%c%c%c %u %c%c%c%c %u: %s\\n", (char)type, (char)(type >> 8) ? (char)(type >> 8) : ' ',
	    (char)(type >> 16) ? (char)(type >> 16) : ' ', (char)(type >> 24) ? (char)(type >> 24) : ' ', (uint32_t)id,
	    (char)key, (char)(key >> 8) ? (char)(key >> 8) : ' ', (char)(key >> 16) ? (char)(key >> 16) : ' ',
	    (char)(key >> 24) ? (char)(key >> 24) : ' ', (uint32_t)value, ok ? "acked" : "FAILED");
}

static void
ud_poke(const char *arg)
{
	static uint64_t page_pa;
	static vm_offset_t page_va;
	uint64_t addr = 0, value = 0;
	const char *rest = ud_hex(arg, &addr);

	if (rest == NULL || ud_hex(rest, &value) == NULL) {
		printf("LV USB: bad lv:poke (HEXADDR HEXVALUE)\\n");
		return;
	}
	addr &= ~3ull;
	if (page_va == 0 || page_pa != (addr & ~0xfffull)) {
		page_pa = addr & ~0xfffull;
		page_va = ml_io_map((vm_offset_t)page_pa, 0x1000);
	}
	if (page_va == 0) {
		printf("LV POKE %#llx: map failed\\n", addr);
		return;
	}
	volatile uint32_t *reg = (volatile uint32_t *)(page_va + (addr & 0xfff));
	uint32_t old = *reg;
	*reg = (uint32_t)value;
	__asm__ volatile ("dsb sy" ::: "memory");
	printf("LV POKE %#llx: %08x -> %08x, reads back %08x\\n", addr, old, (uint32_t)value, *reg);
}

static void
ud_rx_done(void)
{''')
patch(usb, '''	} else if (strncmp(cmd, "lv:gold ", 8) == 0) {''', '''	} else if (strncmp(cmd, "lv:rpm ", 7) == 0) {
		ud_rpm(cmd + 7);
	} else if (strncmp(cmd, "lv:poke ", 8) == 0) {
		ud_poke(cmd + 8);
	} else if (strncmp(cmd, "lv:gold ", 8) == 0) {''')
print('ok')
