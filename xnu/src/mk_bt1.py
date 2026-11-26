"""lavender: Bluetooth step B1 - the WCN3990's Bluetooth answers on its UART (patch 1085).

The stock device tree: bt_wcn3990 (supplies PM660 L9 1.8 V core, L6 1.3 V PA, L19 3.3 V LDO,
PM660L BOB pin; clock RF_CLK1) on the high-speed UART uart@c1af000 (BLSP2 UART1, UARTDM v1.4;
GPIO 16 TX, 17 RX, 18 CTS, 19 RFR, function blsp_uart5; GCC core clock blsp2_uart1_apps,
interface clock blsp2_ahb). Linux hci_qca brings a WCN399x up so: supplies on, host at 2400 baud
sends the power-off pulse 0xC0, host at 115200 sends the power-on pulse 0xFC, 100 ms, then HCI
(H4). btqca asks the SoC version with the vendor command 0xFC00 {0x19} (EDL_PATCH_VER_REQ_CMD).

This step only checks that the controller talks: with bt=1 a thread (started once the modem is
up, which brings the RPM link) powers it, sets up the UART (polled, no DMA), sends the pulses,
then the version request, HCI_Reset (0x0C03) and HCI_Read_Local_Version (0x1001), and logs every
byte that comes back ("bt: ..."). No firmware is loaded yet (B2).

- iokit/Kernel/arm/LavenderBT.cpp (new), iokit/conf/files.arm64
- TopazModem.cpp: lv_bt_start() when the modem reports READY

usage: python mk_bt1.py XNU_TREE   (after mk_diagcntl.py; needs iokit/conf/files.arm64 in the tree)
"""
import sys

tree = sys.argv[1]

src = r'''/*
 * lavender: Bluetooth of the WCN3990 on BLSP2 UART1 (xnu/src/mk_bt1.py and later mk_bt*.py).
 * Polled UARTDM v1.4 (Linux msm_serial.c), power-up of a WCN399x (Linux hci_qca.c, btqca.c).
 */
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>

#define LOG(fmt, ...)       IOLog("bt: " fmt "\n", ##__VA_ARGS__)

extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern "C" bool topaz_rpm_write(uint32_t set, uint32_t type, uint32_t id, uint32_t key, uint32_t value);
extern "C" void lv_bt_start(void);

#define GCC_PA              0x00100000ull
#define TLMM_CENTER_PA      0x03500000ull       /* GPIO 16..19 */
#define UART_PA             0x0C1AF000ull

/* UARTDM v1.4 (msm_serial.c) */
#define U_MR1               0x00
#define U_MR2               0x04
#define U_CSR               0x08                /* write */
#define U_SR                0x08                /* read */
#define U_CR                0x10
#define U_IMR               0x14
#define U_IPR               0x18
#define U_TFWR              0x1C
#define U_RFWR              0x20
#define U_DMRX              0x34
#define U_DMEN              0x3C
#define U_NCF_TX            0x40
#define U_RXFS              0x50
#define U_TF                0x70
#define U_RF                0x70
#define SR_RX_READY         (1u << 0)
#define SR_TX_READY         (1u << 2)
#define SR_TX_EMPTY         (1u << 3)
#define CR_RESET_RX         (1u << 4)
#define CR_RESET_TX         (2u << 4)
#define CR_RESET_ERR        (3u << 4)
#define CR_RESET_BREAK      (4u << 4)
#define CR_RESET_CTS        (7u << 4)
#define CR_RESET_STALE      (8u << 4)
#define CR_RESET_RFR        (14u << 4)
#define CR_PROTECTION_EN    (16u << 4)
#define CR_STALE_EN         (80u << 4)
#define CR_FORCE_STALE      (4u << 8)
#define CR_TX_EN            (1u << 2)
#define CR_RX_EN            (1u << 0)

static volatile uint8_t *gcc, *tlmm, *uart;
static uint32_t rx_slop;
static int rx_count;

static inline uint32_t rd(volatile uint8_t *b, uint32_t o) { return *(volatile uint32_t *)(b + o); }
static inline void wr(volatile uint8_t *b, uint32_t o, uint32_t v) { __asm__ volatile ("dsb sy" ::: "memory"); *(volatile uint32_t *)(b + o) = v; __asm__ volatile ("dsb sy" ::: "memory"); }

/* the UART core clock: blsp2_uart1_apps_clk_src (RCG2 at GCC 0x2700c) = GPLL0 * 192 / 15625 = 7.3728 MHz */
static bool
bt_clocks(void)
{
	uint32_t v;
	wr(gcc, 0x52004, rd(gcc, 0x52004) | (1u << 15));        /* blsp2_ahb_clk vote */
	const uint32_t m = 192, n = 15625, mask = 0xffff;
	wr(gcc, 0x2700c + 0x8, m);                               /* M */
	wr(gcc, 0x2700c + 0xc, ~(n - m) & mask);                 /* N */
	wr(gcc, 0x2700c + 0x10, ~n & mask);                      /* D: 2d = n */
	wr(gcc, 0x2700c + 0x4, (1u << 0) | (1u << 8) | (2u << 12));     /* div 1 (hid 1), src GPLL0, dual edge */
	wr(gcc, 0x2700c, rd(gcc, 0x2700c) | 1);                  /* update */
	for (int i = 0; i < 1000 && (rd(gcc, 0x2700c) & 1); i++) {
		IODelay(10);
	}
	wr(gcc, 0x27004, rd(gcc, 0x27004) | 1);                  /* blsp2_uart1_apps_clk on */
	for (int i = 0; i < 1000 && (rd(gcc, 0x27004) & (1u << 31)); i++) {
		IODelay(10);
	}
	v = rd(gcc, 0x27004);
	LOG("clocks: ahb vote %#x, uart rcg cmd %#x cfg %#x, branch %#x%s", rd(gcc, 0x52004), rd(gcc, 0x2700c), rd(gcc, 0x27010), v,
	    (v & (1u << 31)) ? " (still off)" : "");
	return !(v & (1u << 31));
}

static void
bt_pins(void)
{
	for (unsigned g = 16; g <= 19; g++) {
		wr(tlmm, 0x1000 * (g - 16), 1u << 2);           /* function 1 = blsp_uart5, 2 mA, no pull */
	}
}

/* rate = 7372800: base 460800 / divisor; codes from msm_serial's table */
static void
bt_uart_baud(uint32_t code)
{
	wr(uart, U_CSR, code);
	wr(uart, U_IPR, 31 | (0 << 7));                          /* stale timeout */
	wr(uart, U_RFWR, 48);
	wr(uart, U_TFWR, 10);
	wr(uart, U_CR, CR_PROTECTION_EN);
	wr(uart, U_CR, CR_RESET_RX);
	wr(uart, U_CR, CR_RESET_TX);
	wr(uart, U_CR, CR_RESET_ERR);
	wr(uart, U_CR, CR_RESET_BREAK);
	wr(uart, U_CR, CR_RESET_CTS);
	wr(uart, U_CR, CR_RESET_RFR);
	wr(uart, U_DMEN, 0);                                     /* no DMA */
	wr(uart, U_MR1, 0);                                      /* no hardware flow control */
	wr(uart, U_MR2, (3u << 4) | (1u << 2));                  /* 8 bits, 1 stop, no parity */
	wr(uart, U_CR, CR_TX_EN | CR_RX_EN);
	wr(uart, U_IMR, 0);
	wr(uart, U_CR, CR_RESET_STALE);
	wr(uart, U_DMRX, 0xFFFFFF);
	wr(uart, U_CR, CR_STALE_EN);
	rx_count = 0;
}

static void
bt_put(const uint8_t *p, uint32_t n)
{
	for (uint32_t i = 0; i < n; i++) {
		for (int k = 0; k < 100000 && !(rd(uart, U_SR) & SR_TX_EMPTY); k++) {
			IODelay(1);
		}
		wr(uart, U_NCF_TX, 1);
		(void)rd(uart, U_NCF_TX);
		for (int k = 0; k < 100000 && !(rd(uart, U_SR) & SR_TX_READY); k++) {
			IODelay(1);
		}
		wr(uart, U_TF, p[i]);
	}
	for (int k = 0; k < 100000 && !(rd(uart, U_SR) & SR_TX_EMPTY); k++) {
		IODelay(1);
	}
}

/* one received byte, -1 if none (msm_poll_get_char_dm) */
static int
bt_get(void)
{
	uint8_t *sp = (uint8_t *)&rx_slop;
	if (rx_count != 0) {
		return sp[4 - rx_count--];
	}
	if (!(rd(uart, U_SR) & SR_RX_READY)) {
		int c = (int)((rd(uart, U_RXFS) >> 7) & 7);
		if (c == 0) {
			return -1;
		}
		wr(uart, U_CR, CR_FORCE_STALE);
		rx_slop = rd(uart, U_RF);
		rx_count = c - 1;
		wr(uart, U_CR, CR_RESET_STALE);
		wr(uart, U_DMRX, 0xFFFFFF);
		wr(uart, U_CR, CR_STALE_EN);
		return sp[0];
	}
	rx_slop = rd(uart, U_RF);
	rx_count = 3;
	return sp[0];
}

/* everything that comes within ms, logged as hex lines */
static void
bt_drain(const char *what, unsigned ms)
{
	char line[3 * 48 + 1];
	unsigned n = 0, total = 0;
	for (unsigned t = 0; t < ms * 10; t++) {
		int c;
		bool got = false;
		while ((c = bt_get()) >= 0) {
			got = true;
			snprintf(line + 3 * n, 4, "%02x ", c);
			total++;
			if (++n == 48) {
				LOG("%s: %s", what, line);
				n = 0;
			}
		}
		if (!got) {
			IODelay(100);
		}
	}
	if (n != 0) {
		line[3 * n] = 0;
		LOG("%s: %s", what, line);
	}
	LOG("%s: %u bytes", what, total);
}

static void
bt_cmd(const char *what, uint16_t opcode, const uint8_t *param, uint8_t plen)
{
	uint8_t pkt[4 + 255];
	pkt[0] = 0x01;
	pkt[1] = (uint8_t)opcode;
	pkt[2] = (uint8_t)(opcode >> 8);
	pkt[3] = plen;
	if (plen != 0) {
		memcpy(pkt + 4, param, plen);
	}
	bt_put(pkt, 4u + plen);
	bt_drain(what, 600);
}

static void
bt_thread(__unused void *arg, __unused wait_result_t w)
{
	static const struct { const char *name; uint32_t ldo, uv; } rail[] = {
		{ "core (L9)", 9, 1800000 }, { "pa (L6)", 6, 1304000 }, { "ldo (L19)", 19, 3312000 },
	};
	for (unsigned i = 0; i < 3; i++) {
		bool a = topaz_rpm_write(0, 0x616f646cu, rail[i].ldo, 0x00007675u, rail[i].uv);
		bool b = topaz_rpm_write(0, 0x616f646cu, rail[i].ldo, 0x6e657773u, 1);
		LOG("power %s %u uV: %s/%s", rail[i].name, rail[i].uv, a ? "ok" : "FAILED", b ? "ok" : "FAILED");
	}
	LOG("RF_CLK1: %s", topaz_rpm_write(0, 0x616b6c63u, 4, 0x6e657773u, 1) ? "ok" : "FAILED");
	gcc = (volatile uint8_t *)ml_io_map(GCC_PA, 0x90000);
	tlmm = (volatile uint8_t *)ml_io_map(TLMM_CENTER_PA + 0x10000, 0x4000);
	uart = (volatile uint8_t *)ml_io_map(UART_PA, 0x1000);
	if (gcc == NULL || tlmm == NULL || uart == NULL || !bt_clocks()) {
		LOG("no clocks or mappings, stopping");
		thread_terminate(current_thread());
		return;
	}
	bt_pins();
	IOSleep(10);
	uint8_t pulse = 0xC0;
	bt_uart_baud(0x33);                                      /* 2400: divisor 192 */
	bt_put(&pulse, 1);
	IOSleep(10);
	bt_uart_baud(0xcc);                                      /* 115200: divisor 4 */
	pulse = 0xFC;
	bt_put(&pulse, 1);
	IOSleep(100);
	bt_drain("after the power-on pulse", 200);
	uint8_t ver = 0x19;
	bt_cmd("EDL version (FC00 19)", 0xFC00, &ver, 1);
	bt_cmd("HCI_Reset", 0x0C03, NULL, 0);
	bt_cmd("Read_Local_Version", 0x1001, NULL, 0);
	LOG("B1 done");
	thread_terminate(current_thread());
}

extern "C" void
lv_bt_start(void)
{
	static bool started;
	uint32_t on = 0;
	thread_t t;
	if (started || !PE_parse_boot_argn("bt", &on, sizeof(on)) || on == 0) {
		return;
	}
	started = true;
	if (kernel_thread_start(bt_thread, NULL, &t) == KERN_SUCCESS) {
		thread_deallocate(t);
	}
}
'''

open(f'{tree}/iokit/Kernel/arm/LavenderBT.cpp', 'w', newline='\n').write(src)

p = f'{tree}/iokit/conf/files.arm64'
s = open(p, newline='').read()
anchor = 'iokit/Kernel/arm/SweetWatchdog.cpp                               optional iokitcpp\n'
assert s.count(anchor) == 1
s = s.replace(anchor, anchor + 'iokit/Kernel/arm/LavenderBT.cpp                                  optional iokitcpp\n')
open(p, 'w', newline='\n').write(s)

p = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(p, newline='').read()
old = '''			LOG("modem is up (MODEM READY)");'''
if s.count(old) != 1:
    raise SystemExit('anchor "modem is up" not found')
s = s.replace(old, old + '''
			lv_bt_start();                          /* LavenderBT.cpp (bt=1) */''')
s = s.replace('''extern "C" bool topaz_rpm_write(uint32_t set, uint32_t type, uint32_t id, uint32_t key, uint32_t value);
''', '''extern "C" bool topaz_rpm_write(uint32_t set, uint32_t type, uint32_t id, uint32_t key, uint32_t value);
extern "C" void lv_bt_start(void);
''', 1)
open(p, 'w', newline='\n').write(s)
print('ok')
