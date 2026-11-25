/*
 * lavender (Redmi Note 7) keys, polled every 20 ms, READ ONLY on the PMICs.
 *
 *   power        PM660  (SID 0) PON 0x800, INT_RT_STS 0x810 bit 0 (KPDPWR_N, 1 = pressed)
 *   volume down  PM660  (SID 0) PON 0x800, INT_RT_STS 0x810 bit 1 (RESIN_N, 1 = pressed)
 *   volume up    PM660L (SID 2) GPIO 7 0xc600, STATUS1 0xc608 bit 0 (input, active low)
 *
 * SPMI arbiter v3 (DT qcom,spmi@800f000): core +0x800 maps channel -> peripheral (bits 19:8 =
 * SID << 8 | peripheral), cnfg +0x700 bits 2:0 = channel owner (0 = application CPU), reads go
 * through observer channel registers at 0x9400000 + 0x8000 * channel.
 * Boot-arg sweetkeys=0 disables.
 */
#if defined(ARM64_BOARD_CONFIG_SWEET)
#include <sys/param.h>
#include <sys/systm.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <kern/sched_prim.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>

extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern void sweet_hid_key(int key, int down);
void sweet_keys_init(void);

#define KEYS_CORE_PA    0x0800f000u
#define KEYS_CNFG_PA    0x0800a000u
#define KEYS_OBS_PA     0x09400000u
#define KEYS_CHANNELS   512u

struct keys_reg {
	uint16_t ppid;          /* SID << 8 | peripheral */
	uint8_t  reg;           /* register within the peripheral */
	vm_offset_t ch;         /* observer channel, mapped */
};

static struct keys_reg keys_pon = { 0x008, 0x10, 0 };  /* PM660 PON INT_RT_STS */
static struct keys_reg keys_gpio = { 0x2c6, 0x08, 0 }; /* PM660L GPIO7 STATUS1 */
static uint32_t keys_last_status;
static bool keys_started;
static int keys_sleep_chan;

static uint32_t
keys_rd(vm_offset_t base, uint32_t off)
{
	uint32_t v = *(volatile uint32_t *)(base + off);
	__asm__ volatile ("dmb oshld" ::: "memory");
	return v;
}

static void
keys_map(struct keys_reg *k, vm_offset_t core, vm_offset_t cnfg)
{
	int found = -1;
	for (uint32_t i = 0; i < KEYS_CHANNELS; i++) {
		uint32_t map = keys_rd(core, 0x800u + 4u * i);
		if (map == 0 || ((map >> 8) & 0xfffu) != k->ppid) {
			continue;
		}
		if (found < 0 || (keys_rd(cnfg, 0x700u + 4u * i) & 7u) == 0) {
			found = (int)i;
		}
	}
	if (found >= 0) {
		k->ch = ml_io_map(KEYS_OBS_PA + 0x8000u * (uint32_t)found, 0x1000);
	}
	printf("SWEET KEYS: ppid %#x -> channel %d\n", k->ppid, found);
}

static bool
keys_read(struct keys_reg *k, uint8_t *out)
{
	if (k->ch == 0) {
		return false;
	}
	__asm__ volatile ("dmb oshst" ::: "memory");
	*(volatile uint32_t *)(k->ch + 0x00) = (1u << 27) | ((uint32_t)k->reg << 4); /* read, 1 byte */
	__asm__ volatile ("dsb osh" ::: "memory");
	for (unsigned i = 0; i < 1000; ++i) {
		keys_last_status = keys_rd(k->ch, 0x08);
		if (keys_last_status & 1u) {
			if (keys_last_status & 0x0eu) {
				return false;
			}
			*out = (uint8_t)keys_rd(k->ch, 0x18);
			return true;
		}
		delay(1);
	}
	return false;
}

static void
keys_wait(void)
{
	uint64_t deadline;
	clock_interval_to_deadline(20, NSEC_PER_MSEC, &deadline);
	(void)assert_wait_deadline(&keys_sleep_chan, THREAD_UNINT, deadline);
	thread_block(THREAD_CONTINUE_NULL);
}

static void
keys_thread(void *arg, wait_result_t result)
{
	int state[3] = {0, 0, 0};
	unsigned errors = 0;
	(void)arg;
	(void)result;
	for (;;) {
		uint8_t pon = 0, gpio = 0;
		bool pok = keys_read(&keys_pon, &pon);
		bool gok = keys_read(&keys_gpio, &gpio);
		int now[3] = {!!(pon & 1u), !(gpio & 1u), !!(pon & 2u)};
		if (!pok || !gok) {
			if ((errors++ % 250u) == 0) {
				printf("SWEET KEYS: read error pon-ok=%d gpio-ok=%d arb-status=%#x\n",
				    pok, gok, keys_last_status);
			}
		} else {
			errors = 0;
		}
		for (int k = 0; k < 3; ++k) {
			if ((k == 1 ? gok : pok) && now[k] != state[k]) {
				state[k] = now[k];
				printf("SWEET KEYS: key=%d down=%d pon=%#x gpio7=%#x\n", k, state[k], pon, gpio);
				sweet_hid_key(k, state[k]);
			}
		}
		keys_wait();
	}
}

void
sweet_keys_init(void)
{
	int enabled = 1;
	thread_t thread;
	if (keys_started) {
		return;
	}
	keys_started = true;
	(void)PE_parse_boot_argn("sweetkeys", &enabled, sizeof(enabled));
	if (!enabled) {
		printf("SWEET KEYS: disabled (sweetkeys=0)\n");
		return;
	}
	vm_offset_t core = ml_io_map(KEYS_CORE_PA, 0x1000);
	vm_offset_t cnfg = ml_io_map(KEYS_CNFG_PA, 0x1000);
	if (!core || !cnfg) {
		printf("SWEET KEYS: MMIO mapping failed\n");
		return;
	}
	keys_map(&keys_pon, core, cnfg);
	keys_map(&keys_gpio, core, cnfg);
	uint8_t pon = 0, gpio = 0;
	bool pok = keys_read(&keys_pon, &pon);
	bool gok = keys_read(&keys_gpio, &gpio);
	printf("SWEET KEYS: lavender pon=%#x/%d gpio7=%#x/%d\n", pon, pok, gpio, gok);
	kern_return_t kr = kernel_thread_start(keys_thread, NULL, &thread);
	if (kr == KERN_SUCCESS) {
		thread_deallocate(thread);
	} else {
		printf("SWEET KEYS: kernel_thread_start failed %d\n", kr);
	}
}
#endif /* ARM64_BOARD_CONFIG_SWEET */
