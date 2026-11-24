/*
 * lavender (Redmi Note 7, SDM660): touch.
 *
 * Novatek NT36672A, the touch half of the panel's TDDI chip: ABL brings it up with the display,
 * its firmware runs from the chip's flash. It answers on I2C at 0x01 (firmware, data) and 0x62;
 * the bus is SDA GPIO 2 / SCL GPIO 3 with external pull-ups, the event line is GPIO 67 (low while
 * a report is waiting). Values from the stock device tree (novatek@62) and Linux NT36xxx.
 *
 * I2C is done in software on those two pins (open drain: the output value stays 0 and only the
 * output enable moves), so the BLSP QUP controller and its clocks are not needed. ~200 kHz.
 * The report buffer is read only while the event line is low.
 *
 * NT36672A protocol: the 256-byte window at register 0..0xff is selected by writing
 * {0xff, addr >> 16, addr >> 8}; the event buffer is at 0x21c00. A report holds 10 slots of
 * 6 bytes from offset 1: id << 3 | state, x[11:4], y[11:4], x[3:0] << 4 | y[3:0], ...;
 * state 1 or 2 means the finger is down. Coordinates are panel pixels (1080 x 2340).
 * Firmware info at offset 0x78/0x79: version and its complement.
 *
 * Boot-arg sweettouch=0 turns it off. The only writes to the chip select its register window.
 */
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/errno.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <kern/sched_prim.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>

extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern void sweet_hid_touch(int finger, int down, int x, int y);
void sweet_touch_init(void);

/* TLMM: each pin has a 4 KiB block in its tile; CFG at +0, IN_OUT at +4. */
#define TLMM_SOUTH_PA   0x03100000u     /* GPIO 2, 3 */
#define TLMM_NORTH_PA   0x03900000u     /* GPIO 67 */
#define PIN_SDA         2u
#define PIN_SCL         3u
#define PIN_IRQ         67u
#define CFG_PULL_UP     3u
#define CFG_DRIVE_2MA   (0u << 6)
#define CFG_OE          (1u << 9)
#define IO_IN           (1u << 0)

#define NVT_ADDR        0x01
#define NVT_EVENT_BUF   0x21c00u
#define NVT_REPORT_LEN  65u
#define NVT_FINGERS     10u
#define HALF_US         2u              /* half an SCL period */

static struct {
	vm_offset_t sda, scl, irq;      /* the pins' register blocks */
	bool down[NVT_FINGERS];
	int x[NVT_FINGERS], y[NVT_FINGERS];
	uint64_t reports, errors;
} lt;

static inline uint32_t
pin_rd(vm_offset_t pin, uint32_t off)
{
	uint32_t v = *(volatile uint32_t *)(pin + off);
	__asm__ volatile ("dmb oshld" ::: "memory");
	return v;
}

static inline void
pin_wr(vm_offset_t pin, uint32_t off, uint32_t v)
{
	*(volatile uint32_t *)(pin + off) = v;
	__asm__ volatile ("dsb sy" ::: "memory");
}

/* Plain GPIO (function 0), pull-up, output value 0; the line is low only while OE is set. */
static void
pin_setup(vm_offset_t pin)
{
	pin_wr(pin, 4, 0);
	pin_wr(pin, 0, CFG_PULL_UP | CFG_DRIVE_2MA);
}

static inline void
line_low(vm_offset_t pin)
{
	pin_wr(pin, 0, CFG_PULL_UP | CFG_DRIVE_2MA | CFG_OE);
}

static inline void
line_release(vm_offset_t pin)
{
	pin_wr(pin, 0, CFG_PULL_UP | CFG_DRIVE_2MA);
}

static inline bool
line_high(vm_offset_t pin)
{
	return (pin_rd(pin, 4) & IO_IN) != 0;
}

/* Release SCL and wait for it (the chip may stretch the clock). */
static bool
scl_up(void)
{
	line_release(lt.scl);
	for (int i = 0; i < 1000; i++) {
		if (line_high(lt.scl)) {
			delay(HALF_US);
			return true;
		}
		delay(1);
	}
	return false;
}

static bool
i2c_start(void)
{
	line_release(lt.sda);
	if (!scl_up() || !line_high(lt.sda)) {
		return false;                   /* bus stuck */
	}
	line_low(lt.sda);
	delay(HALF_US);
	line_low(lt.scl);
	delay(HALF_US);
	return true;
}

static void
i2c_stop(void)
{
	line_low(lt.sda);
	delay(HALF_US);
	(void)scl_up();
	line_release(lt.sda);
	delay(HALF_US);
}

/* One byte out; returns true on ACK. */
static bool
i2c_write_byte(uint8_t b)
{
	for (int i = 7; i >= 0; i--) {
		if (b & (1u << i)) {
			line_release(lt.sda);
		} else {
			line_low(lt.sda);
		}
		delay(HALF_US);
		if (!scl_up()) {
			return false;
		}
		line_low(lt.scl);
	}
	line_release(lt.sda);
	delay(HALF_US);
	if (!scl_up()) {
		return false;
	}
	bool ack = !line_high(lt.sda);
	line_low(lt.scl);
	return ack;
}

static uint8_t
i2c_read_byte(bool ack)
{
	uint8_t b = 0;
	line_release(lt.sda);
	for (int i = 7; i >= 0; i--) {
		delay(HALF_US);
		(void)scl_up();
		if (line_high(lt.sda)) {
			b |= (uint8_t)(1u << i);
		}
		line_low(lt.scl);
	}
	if (ack) {
		line_low(lt.sda);
	}
	delay(HALF_US);
	(void)scl_up();
	line_low(lt.scl);
	line_release(lt.sda);
	return b;
}

/* Write len bytes to addr; returns 0 or an errno. */
static int
i2c_write(uint8_t addr, const uint8_t *buf, unsigned len)
{
	int error = 0;
	if (!i2c_start()) {
		return EBUSY;
	}
	if (!i2c_write_byte((uint8_t)(addr << 1))) {
		error = ENXIO;
	}
	for (unsigned i = 0; !error && i < len; i++) {
		if (!i2c_write_byte(buf[i])) {
			error = EIO;
		}
	}
	i2c_stop();
	return error;
}

/* Register reg of addr, then len bytes (repeated start). */
static int
i2c_read(uint8_t addr, uint8_t reg, uint8_t *buf, unsigned len)
{
	int error = 0;
	if (!i2c_start()) {
		return EBUSY;
	}
	if (!i2c_write_byte((uint8_t)(addr << 1)) || !i2c_write_byte(reg)) {
		error = ENXIO;
	} else if (!i2c_start() || !i2c_write_byte((uint8_t)(addr << 1 | 1))) {
		error = EIO;
	} else {
		for (unsigned i = 0; i < len; i++) {
			buf[i] = i2c_read_byte(i + 1 < len);
		}
	}
	i2c_stop();
	return error;
}

/* Nine clocks with SDA released free a slave that was left mid-byte, then a stop. */
static void
i2c_recover(void)
{
	line_release(lt.sda);
	for (int i = 0; i < 9 && !line_high(lt.sda); i++) {
		line_low(lt.scl);
		delay(HALF_US);
		(void)scl_up();
	}
	i2c_stop();
}

static int
nvt_set_window(uint32_t addr)
{
	const uint8_t cmd[3] = { 0xff, (uint8_t)(addr >> 16), (uint8_t)(addr >> 8) };
	return i2c_write(NVT_ADDR, cmd, sizeof(cmd));
}

static void
touch_sleep_ms(unsigned ms)
{
	static int chan;
	uint64_t deadline;
	clock_interval_to_deadline(ms, NSEC_PER_MSEC, &deadline);
	(void)assert_wait_deadline(&chan, THREAD_UNINT, deadline);
	thread_block(THREAD_CONTINUE_NULL);
}

static void
touch_report(const uint8_t *r)
{
	bool now[NVT_FINGERS] = { false };
	int nx[NVT_FINGERS], ny[NVT_FINGERS];

	for (unsigned i = 0; i < NVT_FINGERS; i++) {
		const uint8_t *p = r + 1 + 6 * i;
		unsigned id = p[0] >> 3, state = p[0] & 7;
		if (id == 0 || id > NVT_FINGERS || (state != 1 && state != 2)) {
			continue;
		}
		int x = (p[1] << 4) | (p[3] >> 4), y = (p[2] << 4) | (p[3] & 0x0f);
		if (x >= 1080 || y >= 2340) {
			continue;
		}
		now[id - 1] = true;
		nx[id - 1] = x;
		ny[id - 1] = y;
	}
	for (unsigned f = 0; f < NVT_FINGERS; f++) {
		if (now[f]) {
			lt.down[f] = true;
			lt.x[f] = nx[f];
			lt.y[f] = ny[f];
			sweet_hid_touch((int)f, 1, nx[f], ny[f]);
		} else if (lt.down[f]) {
			lt.down[f] = false;
			sweet_hid_touch((int)f, 0, lt.x[f], lt.y[f]);
		}
	}
}

static void
touch_thread(void *arg __unused, wait_result_t wr __unused)
{
	uint8_t r[NVT_REPORT_LEN + 1];
	uint8_t info[2];
	int error = EIO;

	for (int tries = 0; tries < 5 && error; tries++) {
		i2c_recover();
		error = nvt_set_window(NVT_EVENT_BUF);
		if (!error) {
			error = i2c_read(NVT_ADDR, 0x78, info, sizeof(info));
		}
		if (error) {
			touch_sleep_ms(200);
		}
	}
	if (error) {
		printf("SWEET TOUCH: NT36672A does not answer at 0x%02x (%d), SDA %u SCL %u\n",
		    NVT_ADDR, error, line_high(lt.sda), line_high(lt.scl));
		return;
	}
	printf("SWEET TOUCH: NT36672A firmware 0x%02x (check 0x%02x %s), event line %s\n",
	    info[0], info[1], (uint8_t)(info[0] + info[1]) == 0xff ? "ok" : "BAD",
	    line_high(lt.irq) ? "high" : "low");

	bool any_down = false;
	for (;;) {
		/* A report waits while the line is low; after the last finger lifts, read once more. */
		if (!line_high(lt.irq) || any_down) {
			if (i2c_read(NVT_ADDR, 0x00, r, NVT_REPORT_LEN + 1) == 0) {
				lt.reports++;
				touch_report(r);
			} else if (++lt.errors <= 10) {
				printf("SWEET TOUCH: read failed\n");
				i2c_recover();
			}
			any_down = false;
			for (unsigned f = 0; f < NVT_FINGERS; f++) {
				any_down |= lt.down[f];
			}
		}
		touch_sleep_ms(any_down ? 8 : 12);
	}
}

void
sweet_touch_init(void)
{
	static bool started;
	int enabled = 1;
	thread_t thread;

	PE_parse_boot_argn("sweettouch", &enabled, sizeof(enabled));
	if (!enabled || started) {
		return;
	}
	started = true;
	vm_offset_t south = ml_io_map(TLMM_SOUTH_PA, 0x4000);
	vm_offset_t north = ml_io_map(TLMM_NORTH_PA + 0x40000, 0x4000);     /* 16 KiB pages: 64-67 */
	if (south == 0 || north == 0) {
		printf("SWEET TOUCH: TLMM map failed\n");
		return;
	}
	lt.sda = south + 0x1000 * PIN_SDA;
	lt.scl = south + 0x1000 * PIN_SCL;
	lt.irq = north + 0x1000 * (PIN_IRQ - 64);
	printf("SWEET TOUCH: pins before: SDA cfg 0x%x SCL cfg 0x%x IRQ cfg 0x%x in %u\n",
	    pin_rd(lt.sda, 0), pin_rd(lt.scl, 0), pin_rd(lt.irq, 0), pin_rd(lt.irq, 4) & IO_IN);
	pin_setup(lt.sda);
	pin_setup(lt.scl);
	pin_wr(lt.irq, 0, CFG_PULL_UP | CFG_DRIVE_2MA);    /* GPIO input; the chip pulls it low */
	if (kernel_thread_start(touch_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	}
}
#endif /* ARM64_BOARD_CONFIG_SWEET */
