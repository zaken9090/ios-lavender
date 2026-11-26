"""lavender: audio A1 - census of the audio hardware (patch 1116).

docs/AUDIO-PLAN.md step A1, nothing is played and nothing is written to a codec or an amplifier:
- RPM: PM660L L6 (RPM "ldob" 6) on at 1.8 V - the amplifier's vdd and the pull-up of its I2C
  bus (stock DT: tas2557/tfa98xx vdd-supply = pm660l_l6, i2c-pull-up);
- SPMI (observer, read only): the PM660L analog codec at SID 3 0xF000 and 0xF100 - revision,
  type and subtype bytes (0x00..0x05) - through a new sweet_spmi_peek() without the battery-only
  filter of sweet_spmi_read();
- I2C6 (BLSP2 QUP2, i2c@c1b6000) in software on TLMM GPIO 22/23 (centre tile, function gpio,
  pull-up, open drain), ~100 kHz. The DT enables three speaker amplifiers behind one reset line,
  GPIO 77 (north tile): TFA98xx at 0x34 (reset active high), MAX98927 at 0x3A and TAS2557 at 0x4C
  (reset active low), plus the NFC controller at 0x28. With GPIO 77 low and then high, each
  address is probed (ACK) and read: TFA98xx register 0x03 (revision, 16 bit), MAX98927 register
  0x01FF (revision, 16-bit address), TAS2557 registers 0x00/0x01 (page, reset value). GPIO 73
  (amp interrupt) is read too. GPIO 77 is left low (TFA runs, the others held in reset) at the end.

Started with the Bluetooth thread when the modem is up, boot-arg audio=1. Log prefix "audio: ".

usage: python mk_audio1.py XNU_TREE   (after mk_bt31.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


# sweet_spmi_peek: an observer read of any SID/peripheral
patch(f'{tree}/bsd/dev/sweet_spmi.c', '''int
sweet_spmi_read(unsigned sid, unsigned addr, uint8_t *out)
{''', '''/* lavender (xnu/src/mk_audio1.py): observer read of any peripheral (read only, no filter) */
int sweet_spmi_peek(unsigned sid, unsigned addr, uint8_t *out);

int
sweet_spmi_peek(unsigned sid, unsigned addr, uint8_t *out)
{
	if (sweet_spmi_init() != 0 || !out || sid > 15 || addr > 0xffffu) {
		return -1;
	}
	IOLockLock(sp_lock);
	uint16_t apid = sp_find_apid((uint16_t)((sid << 8) | (addr >> 8)));
	if (apid == SP_NO_APID || sp_poisoned[apid]) {
		IOLockUnlock(sp_lock);
		return -2;
	}
	unsigned off = 0x80u * apid;
	uint32_t cmd = (1u << 27) | ((addr & 0xffu) << 4);
	__asm__ volatile("dmb oshst" ::: "memory");
	*(volatile uint32_t *)(sp_obs + off) = cmd;
	__asm__ volatile("dsb osh" ::: "memory");
	for (unsigned i = 0; i < 1000; ++i) {
		uint32_t status = sp_rd(sp_obs, off + 0x08u);
		if (status & 1u) {
			int r = (status & 0x0eu) ? -3 : 0;
			if (r == 0) {
				*out = (uint8_t)sp_rd(sp_obs, off + 0x18u);
			}
			IOLockUnlock(sp_lock);
			return r;
		}
		delay(1);
	}
	IOLockUnlock(sp_lock);
	return -4;
}

int
sweet_spmi_read(unsigned sid, unsigned addr, uint8_t *out)
{''')

open(f'{tree}/iokit/Kernel/arm/LavenderAudio.cpp', 'w', newline='\n').write(r'''/*
 * lavender audio (xnu/src/mk_audio*.py, docs/AUDIO-PLAN.md).
 * A1: census - PM660L analog codec ids over SPMI, the speaker amplifier on I2C6 (GPIO 22/23).
 */
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>

#define LOG(fmt, ...)       IOLog("audio: " fmt "\n", ##__VA_ARGS__)

extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern "C" bool topaz_rpm_write(uint32_t set, uint32_t type, uint32_t id, uint32_t key, uint32_t value);
extern "C" int sweet_spmi_peek(unsigned sid, unsigned addr, uint8_t *out);
extern "C" void lv_audio_start(void);

#define TLMM_CENTER_PA      0x03500000ull
#define TLMM_NORTH_PA       0x03900000ull
#define GPIO_SDA            22
#define GPIO_SCL            23
#define GPIO_IRQ            73
#define GPIO_RST            77
#define CFG_PULL_UP         3u
#define CFG_OE              (1u << 9)

static volatile uint32_t *pin_sda, *pin_scl, *pin_irq, *pin_rst;   /* each: CFG at [0], IN_OUT at [1] */

static void
pin_cfg(volatile uint32_t *p, uint32_t cfg)
{
	p[0] = cfg;
	__asm__ volatile("dsb sy" ::: "memory");
}

/* open drain: low = drive 0, release = input with pull-up */
static void
od_low(volatile uint32_t *p)
{
	p[1] = 0;
	pin_cfg(p, CFG_PULL_UP | CFG_OE);
}

static void
od_release(volatile uint32_t *p)
{
	pin_cfg(p, CFG_PULL_UP);
}

static bool
od_high(volatile uint32_t *p)
{
	return (p[1] & 1) != 0;
}

#define HALF_US 5

static bool
scl_up(void)
{
	od_release(pin_scl);
	for (int i = 0; i < 1000; i++) {                /* clock stretching up to 1 ms */
		if (od_high(pin_scl)) {
			IODelay(HALF_US);
			return true;
		}
		IODelay(1);
	}
	return false;
}

static bool
i2c_start(void)
{
	od_release(pin_sda);
	if (!scl_up() || !od_high(pin_sda)) {
		return false;
	}
	od_low(pin_sda);
	IODelay(HALF_US);
	od_low(pin_scl);
	IODelay(HALF_US);
	return true;
}

static void
i2c_stop(void)
{
	od_low(pin_sda);
	IODelay(HALF_US);
	(void)scl_up();
	od_release(pin_sda);
	IODelay(HALF_US);
}

static bool
i2c_wb(uint8_t b)
{
	for (int i = 7; i >= 0; i--) {
		if (b & (1u << i)) {
			od_release(pin_sda);
		} else {
			od_low(pin_sda);
		}
		IODelay(HALF_US);
		if (!scl_up()) {
			return false;
		}
		od_low(pin_scl);
	}
	od_release(pin_sda);
	IODelay(HALF_US);
	if (!scl_up()) {
		return false;
	}
	bool ack = !od_high(pin_sda);
	od_low(pin_scl);
	return ack;
}

static uint8_t
i2c_rb(bool ack)
{
	uint8_t b = 0;
	od_release(pin_sda);
	for (int i = 7; i >= 0; i--) {
		IODelay(HALF_US);
		(void)scl_up();
		if (od_high(pin_sda)) {
			b |= (uint8_t)(1u << i);
		}
		od_low(pin_scl);
	}
	if (ack) {
		od_low(pin_sda);
	}
	IODelay(HALF_US);
	(void)scl_up();
	od_low(pin_scl);
	od_release(pin_sda);
	return b;
}

/* register read: write the register address (1 or 2 bytes), repeated start, read n bytes */
static int
i2c_read(uint8_t addr, uint16_t reg, int reglen, uint8_t *out, int n)
{
	if (!i2c_start()) {
		return -2;                                      /* bus stuck low */
	}
	if (!i2c_wb((uint8_t)(addr << 1))) {
		i2c_stop();
		return -1;                                      /* no ACK */
	}
	bool ok = (reglen == 2 ? i2c_wb((uint8_t)(reg >> 8)) : true) && i2c_wb((uint8_t)reg);
	if (!ok || !i2c_start() || !i2c_wb((uint8_t)((addr << 1) | 1))) {
		i2c_stop();
		return -3;
	}
	for (int i = 0; i < n; i++) {
		out[i] = i2c_rb(i + 1 < n);
	}
	i2c_stop();
	return 0;
}

static void
census_i2c(int rst)
{
	pin_rst[1] = rst ? 2u : 0u;                             /* IN_OUT bit 1 = output value */
	pin_cfg(pin_rst, CFG_OE);
	IOSleep(20);
	uint8_t b[2] = { 0, 0 };
	int r;
	r = i2c_read(0x34, 0x03, 1, b, 2);
	LOG("reset gpio77=%d: tfa98xx 0x34 reg 0x03: %d %02x%02x", rst, r, b[0], b[1]);
	b[0] = b[1] = 0;
	r = i2c_read(0x3a, 0x01ff, 2, b, 1);
	LOG("reset gpio77=%d: max98927 0x3a reg 0x01ff: %d %02x", rst, r, b[0]);
	b[0] = b[1] = 0;
	r = i2c_read(0x4c, 0x00, 1, b, 2);
	LOG("reset gpio77=%d: tas2557 0x4c reg 0x00-01: %d %02x %02x", rst, r, b[0], b[1]);
	r = i2c_read(0x28, 0x00, 1, b, 1);
	LOG("reset gpio77=%d: nfc 0x28: %d", rst, r);
	LOG("reset gpio77=%d: amp irq gpio73 = %u, sda %u scl %u", rst, pin_irq[1] & 1, pin_sda[1] & 1, pin_scl[1] & 1);
}

static void
audio_thread(__unused void *arg, __unused wait_result_t w)
{
	/* the amplifier's supply and I2C pull-up: PM660L L6 1.8 V */
	bool a = topaz_rpm_write(0, 0x626f646cu, 6, 0x00007675u, 1800000);
	bool e = topaz_rpm_write(0, 0x626f646cu, 6, 0x6e657773u, 1);
	LOG("PM660L L6 1.8 V: %s/%s", a ? "ok" : "FAILED", e ? "ok" : "FAILED");
	IOSleep(10);

	/* PM660L analog codec (SID 3): revision 1-4, type, subtype of both peripherals */
	for (unsigned base = 0xF000; base <= 0xF100; base += 0x100) {
		uint8_t v[6];
		int rr = 0;
		for (unsigned i = 0; i < 6; i++) {
			v[i] = 0;
			int x = sweet_spmi_peek(3, base + i, &v[i]);
			rr = rr != 0 ? rr : x;
		}
		LOG("pm660l %#x: rev %02x %02x %02x %02x type %02x subtype %02x (%d)", base, v[0], v[1], v[2], v[3], v[4], v[5], rr);
	}

	vm_offset_t c = ml_io_map(TLMM_CENTER_PA + 0x1000 * GPIO_SDA, 0x2000);
	vm_offset_t n1 = ml_io_map(TLMM_NORTH_PA + 0x1000 * GPIO_IRQ, 0x1000);
	vm_offset_t n2 = ml_io_map(TLMM_NORTH_PA + 0x1000 * GPIO_RST, 0x1000);
	if (c == 0 || n1 == 0 || n2 == 0) {
		LOG("TLMM map failed");
		thread_terminate(current_thread());
		return;
	}
	pin_sda = (volatile uint32_t *)c;
	pin_scl = (volatile uint32_t *)(c + 0x1000);
	pin_irq = (volatile uint32_t *)n1;
	pin_rst = (volatile uint32_t *)n2;
	LOG("pins before: sda cfg %#x io %#x, scl cfg %#x io %#x, rst cfg %#x io %#x, irq cfg %#x io %#x", pin_sda[0], pin_sda[1],
	    pin_scl[0], pin_scl[1], pin_rst[0], pin_rst[1], pin_irq[0], pin_irq[1]);
	pin_cfg(pin_irq, CFG_PULL_UP);
	od_release(pin_sda);
	od_release(pin_scl);
	IOSleep(1);
	census_i2c(0);
	census_i2c(1);
	census_i2c(0);
	LOG("A1 done");
	thread_terminate(current_thread());
}

extern "C" void
lv_audio_start(void)
{
	static bool started;
	uint32_t on = 0;
	thread_t t;
	if (started || !PE_parse_boot_argn("audio", &on, sizeof(on)) || on == 0) {
		return;
	}
	started = true;
	if (kernel_thread_start(audio_thread, NULL, &t) == KERN_SUCCESS) {
		thread_deallocate(t);
	}
}
''')

patch(f'{tree}/iokit/conf/files.arm64', '''iokit/Kernel/arm/LavenderBT.cpp                                  optional iokitcpp
''', '''iokit/Kernel/arm/LavenderBT.cpp                                  optional iokitcpp
iokit/Kernel/arm/LavenderAudio.cpp                               optional iokitcpp
''')
patch(f'{tree}/iokit/Kernel/arm/TopazModem.cpp', '''			lv_bt_start();                          /* LavenderBT.cpp (bt=1) */
''', '''			lv_bt_start();                          /* LavenderBT.cpp (bt=1) */
			lv_audio_start();                       /* LavenderAudio.cpp (audio=1) */
''')
patch(f'{tree}/iokit/Kernel/arm/TopazModem.cpp', '''extern "C" void lv_bt_start(void);
''', '''extern "C" void lv_bt_start(void);
extern "C" void lv_audio_start(void);
''')
print('ok')
