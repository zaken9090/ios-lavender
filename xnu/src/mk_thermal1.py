"""lavender: temperature log from the SoC sensors (patch 1120).

The user noticed the phone is warmer than before; nothing watched the temperature
(thermalmonitord runs without sensors, PLAN-DRIVERS item 16). Stock DT: tsens@10ad000
(qcom,sdm660-tsens, TSENS v2 as msm8998), 14 sensors. TSENS v2 TM: sensor n status at
0x10AE000 (TM, the second page of the DT block 0x10AD000+0x2000; the first page, SROT, is
0x10AD000 and may not be readable from EL1 - the first project read 0x10AE000) + 0xA0 + 4*n, bits 11:0 the last temperature in tenths of a degree (signed),
bit 21 valid.

Now a kernel thread (started with the modem-up hook, before Bluetooth/audio) reads the 14
sensors every 30 s - read only - and logs "temp: max X.Y C (sensor n), all: ..." ; boot-arg
lv_temp=0 turns it off, lv_temp=N sets the period in seconds. Above 80 C it says HOT.

usage: python mk_thermal1.py XNU_TREE   (after mk_audio3.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


open(f'{tree}/iokit/Kernel/arm/LavenderThermal.cpp', 'w', newline='\n').write(r'''/*
 * lavender: SoC temperature log (xnu/src/mk_thermal1.py). TSENS v2 TM at 0x10AE000, read only.
 */
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>

#define LOG(fmt, ...)       IOLog("temp: " fmt "\n", ##__VA_ARGS__)
#define TSENS_TM_PA         0x010AE000ull       /* TM page of the DT block 0x10ad000+0x2000 (first project: 0x10ae000) */
#define TSENS_SENSORS       14

extern "C" vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);
extern "C" void lv_thermal_start(void);

static volatile uint32_t *tm;
static uint32_t period_s = 30;

static void
thermal_thread(__unused void *arg, __unused wait_result_t w)
{
	for (;;) {
		char line[TSENS_SENSORS * 7 + 1];
		int max = -1000, at = -1;
		unsigned n = 0, valid = 0;
		for (unsigned i = 0; i < TSENS_SENSORS; i++) {
			uint32_t v = tm[(0xA0 + 4 * i) / 4];
			int t = (int)(v & 0xfff);
			if (t & 0x800) {
				t -= 0x1000;                    /* signed 12 bit, tenths of a degree */
			}
			if (v & (1u << 21)) {
				valid++;
				if (t > max) {
					max = t;
					at = (int)i;
				}
			}
			n += (unsigned)snprintf(line + n, sizeof(line) - n, "%d ", t / 10);
		}
		if (valid == 0) {
			LOG("no valid sensor (status of sensor 0: %#x)", tm[0xA0 / 4]);
		} else {
			LOG("max %d.%d C (sensor %d)%s, all: %s", max / 10, (max < 0 ? -max : max) % 10, at, max >= 800 ? " HOT" : "", line);
		}
		IOSleep(period_s * 1000);
	}
}

extern "C" void
lv_thermal_start(void)
{
	static bool started;
	thread_t t;
	uint32_t p = 30;
	if (started) {
		return;
	}
	started = true;
	if (PE_parse_boot_argn("lv_temp", &p, sizeof(p)) && p == 0) {
		return;
	}
	period_s = p != 0 ? p : 30;
	tm = (volatile uint32_t *)ml_io_map(TSENS_TM_PA, 0x1000);
	if (tm == NULL) {
		LOG("TSENS map failed");
		return;
	}
	if (kernel_thread_start(thermal_thread, NULL, &t) == KERN_SUCCESS) {
		thread_deallocate(t);
	}
}
''')
patch(f'{tree}/iokit/conf/files.arm64', '''iokit/Kernel/arm/LavenderAudio.cpp                               optional iokitcpp
''', '''iokit/Kernel/arm/LavenderAudio.cpp                               optional iokitcpp
iokit/Kernel/arm/LavenderThermal.cpp                             optional iokitcpp
''')
tm = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
patch(tm, '''			lv_bt_start();                          /* LavenderBT.cpp (bt=1) */
''', '''			lv_thermal_start();                     /* LavenderThermal.cpp (lv_temp=0 off) */
			lv_bt_start();                          /* LavenderBT.cpp (bt=1) */
''')
patch(tm, '''extern "C" void lv_audio_start(void);
''', '''extern "C" void lv_audio_start(void);
extern "C" void lv_thermal_start(void);
''')
print('ok')
