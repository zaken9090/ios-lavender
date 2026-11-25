"""lavender performance votes through the RPM (resource power manager).

- TopazRpm.cpp: SDM660's RPM GLINK message RAM is at 0x778000 (DT qcom,glink-rpm-native-xprt),
  doorbell APCS IPC 0x17911008 bit 0, mapped here (the topaz modem driver that owns
  topaz_apcs_kick() does not run on lavender).
- lavender_perf_start() (from SweetPlatformExpert::start) runs a thread that measures a memcpy,
  votes the DDR (BIMC, RPM "clk2" id 0, key "KHz") to boot-arg lv_ddr_khz and measures again.
  lv_ddr_khz=0 (default): no vote, only the measurement. lavender DDR levels (DT): 100800 ...
  1804800 kHz.

usage: python mk_perf.py XNU_TREE
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


PERF = r'''
/*
 * lavender: memcpy speed (DDR bandwidth) and the DDR vote. A thread of its own: the RPM link
 * sleeps while it waits for answers.
 */
#include <kern/thread.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>

#define RPM_MEM_CLK         0x326b6c63u     /* "clk2" */
#define RPM_KEY_KHZ         0x007a484bu     /* "KHz" */

static void
lavender_memcpy_speed(const char *when)
{
	const vm_size_t size = 16u << 20;
	void *a = IOMallocData(size), *b = IOMallocData(size);
	if (a == NULL || b == NULL) {
		LOG("memcpy %s: no memory", when);
	} else {
		memset(a, 0x5a, size);
		memset(b, 0xa5, size);
		uint64_t t0 = mach_absolute_time(), ns;
		for (int i = 0; i < 8; i++) {
			memcpy(i & 1 ? a : b, i & 1 ? b : a, size);
		}
		absolutetime_to_nanoseconds(mach_absolute_time() - t0, &ns);
		LOG("LVDDR memcpy %s: 128 MB in %llu ms, %llu MB/s", when, ns / 1000000,
		    ns ? 128ull * 1000000000ull / ns : 0);
	}
	if (a) {
		IOFreeData(a, size);
	}
	if (b) {
		IOFreeData(b, size);
	}
}

static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{
	uint32_t khz = 0;
	PE_parse_boot_argn("lv_ddr_khz", &khz, sizeof(khz));
	IOSleep(2000);
	lavender_memcpy_speed("before");
	if (khz != 0) {
		bool ok = topaz_rpm_write(0, RPM_MEM_CLK, 0, RPM_KEY_KHZ, khz);
		LOG("LVDDR vote %u kHz -> %s", khz, ok ? "acked" : "FAILED");
		IOSleep(100);
		lavender_memcpy_speed("after");
	}
}

extern "C" void
lavender_perf_start(void)
{
	thread_t thread;
	if (kernel_thread_start(lavender_perf_thread, NULL, &thread) == KERN_SUCCESS) {
		thread_deallocate(thread);
	}
}
'''

edit('iokit/Kernel/arm/TopazRpm.cpp', [
    ('#define MSG_RAM_PA          0x045F0000ull', '#define MSG_RAM_PA          0x00778000ull    /* lavender (SDM660); topaz 0x045F0000 */'),
    ('''extern "C" void topaz_apcs_kick(unsigned bit);''', '''/* lavender: APCS IPC (DT irq-reg-base 0x17911008) */
static void
topaz_apcs_kick(unsigned bit)
{
	static volatile uint32_t *ipc;
	if (ipc == NULL) {
		vm_offset_t m = ml_io_map(0x17911000, 0x1000);
		ipc = m ? (volatile uint32_t *)(m + 8) : NULL;
	}
	if (ipc != NULL) {
		__asm__ volatile ("dsb sy" ::: "memory");
		*ipc = 1u << bit;
		__asm__ volatile ("dsb sy" ::: "memory");
	}
}'''),
    ('''#else
extern "C" bool topaz_rpm_write(''', PERF.lstrip('\n') + '''
#else
extern "C" bool topaz_rpm_write('''),
])

edit('iokit/Kernel/arm/SweetPlatformExpert.cpp', [
    ('''extern "C" void sweet_usb_probe(void);''', '''extern "C" void sweet_usb_probe(void);
extern "C" void lavender_perf_start(void);'''),
    ('''	sweet_usb_probe();     /* lavender: kernel log over USB from early boot (bsd/dev/sweet_usb.c) */''',
     '''	sweet_usb_probe();     /* lavender: kernel log over USB from early boot (bsd/dev/sweet_usb.c) */
	lavender_perf_start();  /* lavender: DDR vote and memcpy speed (TopazRpm.cpp) */'''),
])
print('ok')
