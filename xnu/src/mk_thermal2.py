"""lavender: CPU load next to the temperatures, GPU sensor named (patch 1121).

The user asked for what the first project showed on every boot: fps (SWEET FPS lines already),
the hottest CPU/GPU points and the load. Stock DT: TSENS sensor 8 has the alias "gpu"; the
others are CPU clusters and other blocks.

Now each "temp:" line (every lv_temp seconds, 30 by default) also gives the GPU sensor and the
CPU load over the period: busy share of all cores and of the busiest core, from each processor's
tick counters (processor_info PROCESSOR_CPU_LOAD_INFO: user, system, idle, nice).
Format: "temp: gpu 41.2 C, hottest 45.0 C (sensor 3), load 23% (busiest cpu 2 61%), all: ..."

usage: python mk_thermal2.py XNU_TREE   (after mk_thermal1.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderThermal.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static volatile uint32_t *tm;''', '''static volatile uint32_t *tm;

/* osfmk: per-processor tick counters (struct processor_cpu_load_info: user, system, idle, nice) */
extern "C" processor_t cpu_to_processor(int cpu);
extern "C" int ml_get_max_cpu_number(void);     /* processor_info() comes from <mach/mach_interface.h> */
#define LV_MAX_CPUS         8
static uint32_t last_busy[LV_MAX_CPUS], last_all[LV_MAX_CPUS];

/* busy share in percent since the last call: all cores, and the busiest one */
static void
cpu_load(unsigned *all_pct, unsigned *top_pct, int *top_cpu)
{
	uint64_t busy = 0, total = 0;
	*top_pct = 0;
	*top_cpu = -1;
	for (int c = 0; c <= ml_get_max_cpu_number() && c < LV_MAX_CPUS; c++) {   /* cpus=4: only 0-3 exist (else the cpu_common.c:82 assertion) */
		processor_t p = cpu_to_processor(c);
		integer_t t[4] = { 0, 0, 0, 0 };
		mach_msg_type_number_t n = 4;
		host_t host = HOST_NULL;
		if (p == PROCESSOR_NULL || processor_info(p, PROCESSOR_CPU_LOAD_INFO, &host, (processor_info_t)t, &n) != KERN_SUCCESS) {
			continue;
		}
		uint32_t b = (uint32_t)t[0] + (uint32_t)t[1] + (uint32_t)t[3], a = b + (uint32_t)t[2];
		uint32_t db = b - last_busy[c], da = a - last_all[c];
		last_busy[c] = b;
		last_all[c] = a;
		busy += db;
		total += da;
		if (da != 0 && db * 100 / da >= *top_pct) {
			*top_pct = db * 100 / da;
			*top_cpu = c;
		}
	}
	*all_pct = total != 0 ? (unsigned)(busy * 100 / total) : 0;
}''')
sub('''		if (valid == 0) {
			LOG("no valid sensor (status of sensor 0: %#x)", tm[0xA0 / 4]);
		} else {
			LOG("max %d.%d C (sensor %d)%s, all: %s", max / 10, (max < 0 ? -max : max) % 10, at, max >= 800 ? " HOT" : "", line);
		}''', '''		unsigned all = 0, top = 0;
		int topc = -1;
		cpu_load(&all, &top, &topc);
		int g = (int)(tm[(0xA0 + 4 * 8) / 4] & 0xfff);
		g = (g & 0x800) ? g - 0x1000 : g;
		if (valid == 0) {
			LOG("no valid sensor (status of sensor 0: %#x), load %u%% (busiest cpu %d %u%%)", tm[0xA0 / 4], all, topc, top);
		} else {
			LOG("gpu %d.%d C, hottest %d.%d C (sensor %d)%s, load %u%% (busiest cpu %d %u%%), all: %s", g / 10, (g < 0 ? -g : g) % 10,
			    max / 10, (max < 0 ? -max : max) % 10, at, max >= 800 ? " HOT" : "", all, topc, top, line);
		}''')
open(path, 'w', newline='\n').write(s)
print('ok')
