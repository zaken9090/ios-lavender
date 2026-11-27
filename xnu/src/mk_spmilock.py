"""lavender: one lock for the PMIC bus; the LVM line takes the GPU clock from its divider (patch 1163).

The user saw the volume slider twitch while a bench ran. The log had "SWEET KEYS: read error ..." and
key events nobody pressed (volume up 0xe9, volume down) - only since patch 1160: its metrics thread
reads the fuel gauge over SPMI every second while the keys thread reads the PON and GPIO status every
20 ms through another channel of the same arbiter, with nothing between them. Two transactions at once
make one of them fail or return a wrong byte, and a wrong status byte is a key press.

Now every SPMI transaction of the kernel (keys, lv_pmic_byte: metrics, backlight, lv:pmic, lv:fastboot)
runs under one mutex (lv_spmi_lock / lv_spmi_unlock, bsd/dev/sweet_usb.c).

Also: the GPU busy share was computed with the clock the driver believes (300 MHz) and read double once
the core ran at 600 MHz. The line now takes the clock from the gfx3d RCG (0x5066074: source 5 = GPLL0
600 MHz, divider (d + 1) / 2).

usage: python mk_spmilock.py XNU_TREE   (after mk_rpmcmd.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


usb = f'{tree}/bsd/dev/sweet_usb.c'
patch(usb, '''#include <pexpert/device_tree.h>
''', '''#include <pexpert/device_tree.h>
#include <kern/locks.h>
''')
patch(usb, '''/* One byte of PMIC 0 at addr. Returns 0 on success. */
static int
spmi_byte(bool write, unsigned addr, uint8_t *val)
{''', '''/*
 * lavender: one SPMI transaction at a time, whoever asks (xnu/src/mk_spmilock.py). Two at once through
 * different channels made one fail or return a wrong byte (phantom volume keys while the metrics read
 * the fuel gauge).
 */
static LCK_GRP_DECLARE(lv_spmi_grp, "lv_spmi");
static LCK_MTX_DECLARE(lv_spmi_mtx, &lv_spmi_grp);
void lv_spmi_lock(void);
void lv_spmi_unlock(void);

void
lv_spmi_lock(void)
{
	lck_mtx_lock(&lv_spmi_mtx);
}

void
lv_spmi_unlock(void)
{
	lck_mtx_unlock(&lv_spmi_mtx);
}

/* One byte of PMIC 0 at addr. Returns 0 on success. With the SPMI lock held. */
static int
spmi_byte_bus(bool write, unsigned addr, uint8_t *val)
{''')
patch(usb, '''/*
 * lavender: one PMIC byte for other drivers (xnu/src/mk_wled.c): addr = slave << 16 | register.''', '''static int
spmi_byte(bool write, unsigned addr, uint8_t *val)
{
	lv_spmi_lock();
	int r = spmi_byte_bus(write, addr, val);
	lv_spmi_unlock();
	return r;
}

/*
 * lavender: one PMIC byte for other drivers (xnu/src/mk_wled.c): addr = slave << 16 | register.''')

keys = f'{tree}/bsd/dev/sweet_keys.c'
patch(keys, '''static bool
keys_read(struct keys_reg *k, uint8_t *out)
{''', '''extern void lv_spmi_lock(void);          /* bsd/dev/sweet_usb.c (xnu/src/mk_spmilock.py) */
extern void lv_spmi_unlock(void);

static bool
keys_read_bus(struct keys_reg *k, uint8_t *out)
{''')
patch(keys, '''static void
keys_wait(void)
{''', '''/* lavender: under the SPMI lock (xnu/src/mk_spmilock.py) */
static bool
keys_read(struct keys_reg *k, uint8_t *out)
{
	lv_spmi_lock();
	bool ok = keys_read_bus(k, out);
	lv_spmi_unlock();
	return ok;
}

static void
keys_wait(void)
{''')

m = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'
patch(m, '''static volatile uint32_t *tm, *pll_gold, *pll_silver, *gold_rcg, *apcs_common;''',
      '''static volatile uint32_t *tm, *pll_gold, *pll_silver, *gold_rcg, *apcs_common;
static volatile uint32_t *gfx_cc;               /* GPU clock controller page with the gfx3d RCG (xnu/src/mk_spmilock.py) */''')
patch(m, '''		if (redwood_gpu_stats(&busy, &mhz, &sub, &rec, &fail) && mhz != 0) {
			uint64_t share = 0;''', '''		if (redwood_gpu_stats(&busy, &mhz, &sub, &rec, &fail) && mhz != 0) {
			uint64_t share = 0;
			uint32_t cfg = gfx_cc != NULL ? gfx_cc[0x74 / 4] : 0;
			if (((cfg >> 8) & 7) == 5) {
				mhz = 1200 / ((cfg & 0x1f) + 1);        /* GPLL0 600 MHz, divider (d + 1) / 2 */
			}''')
patch(m, '''	apcs_common = (volatile uint32_t *)ml_io_map(APCS_COMMON_PA, 0x1000);
''', '''	apcs_common = (volatile uint32_t *)ml_io_map(APCS_COMMON_PA, 0x1000);
	gfx_cc = (volatile uint32_t *)ml_io_map(0x05066000ull, 0x1000);
''')
print('ok')
