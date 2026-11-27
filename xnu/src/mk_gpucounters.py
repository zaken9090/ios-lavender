"""lavender: what the GPU spends its time on - an LVG line of its own counters every second (patch 1164).

fps follow neither the CPU nor the GPU clock and the GPU is busy 94-96 % of the time at 300 and at
600 MHz (docs/PLAN.md P1): to see where its time goes, 14 of the Adreno 5xx performance counters are
selected in a5_hw_init and printed as the change over the period, after the LVM line:

  LVG <ms>: tpbeat spbeat latcyc latn | tpbusy tpreq tpmiss | spalu spbusy spidle | rbbusy rbpass rbstall rbfifo
      tpbeat / spbeat   data beats read from memory for textures / for the shader processor (UCHE 4, 8)
      latcyc / latn     memory latency: cycles waited and requests counted (UCHE 2, 3): latcyc / latn
                        = cycles a request
      tpbusy tpreq tpmiss   texture pipe busy cycles, L1 cache line requests and misses (TP 0, 6, 7)
      spalu spbusy spidle   shader ALU working cycles, busy cycles, wave idle cycles (SP 1, 0, 22)
      rbbusy rbpass rbstall rbfifo   render backend busy cycles, pixels passed, stalls on the CCU and
                        on a full FIFO (RB 0, 17, 1, 3)
Cycles are of the GPU core clock (LVM "gpu .. MHz").

usage: python mk_gpucounters.py XNU_TREE   (after mk_spmilock.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


patch(f'{tree}/iokit/Kernel/arm/TopazRpm.cpp', '''	g_w(A5_SP_PERFCTR_SP_SEL_0, 1);                 /* PERF_SP_ALU_WORKING_CYCLES */
''', '''	g_w(A5_SP_PERFCTR_SP_SEL_0, 1);                 /* PERF_SP_ALU_WORKING_CYCLES */
	/* lavender: counters of the LVG line (xnu/src/mk_gpucounters.py): UCHE, TP, SP, RB select registers */
	g_w(0x0ea0, 4);                                 /* UCHE 0: VBIF read beats, textures */
	g_w(0x0ea1, 8);                                 /* UCHE 1: VBIF read beats, shader processor */
	g_w(0x0ea2, 2);                                 /* UCHE 2: VBIF latency cycles */
	g_w(0x0ea3, 3);                                 /* UCHE 3: VBIF latency samples */
	g_w(0x0f10, 0);                                 /* TP 0: busy cycles */
	g_w(0x0f11, 6);                                 /* TP 1: L1 cache line requests */
	g_w(0x0f12, 7);                                 /* TP 2: L1 cache line misses */
	g_w(0x0ed1, 0);                                 /* SP 1: busy cycles */
	g_w(0x0ed2, 22);                                /* SP 2: wave idle cycles */
	g_w(0x0cd0, 0);                                 /* RB 0: busy cycles */
	g_w(0x0cd1, 17);                                /* RB 1: pixels passed */
	g_w(0x0cd2, 1);                                 /* RB 2: stall cycles, CCU */
	g_w(0x0cd3, 3);                                 /* RB 3: stall cycles, FIFO 0 full */
''')

ad = f'{tree}/iokit/Kernel/arm/TopazAdreno.cpp'
patch(ad, '''bool redwood_gpu_stats(uint64_t *busy, uint32_t *mhz, uint32_t *submits, uint32_t *recovered, uint32_t *failed);
''', '''bool redwood_gpu_stats(uint64_t *busy, uint32_t *mhz, uint32_t *submits, uint32_t *recovered, uint32_t *failed);
bool redwood_gpu_counters(uint64_t *out, uint32_t count);
''')
patch(ad, '''static uint32_t lv_gpu_recovered, lv_gpu_recover_failed;
''', '''static uint32_t lv_gpu_recovered, lv_gpu_recover_failed;

/*
 * lavender (mk_gpucounters.py): the counters of the LVG line, in its order: UCHE 0-3, TP 0-2, SP 0-2,
 * RB 0-3 (RBBM_PERFCTR_*_LO, the high word follows each).
 */
bool
redwood_gpu_counters(uint64_t *out, uint32_t count)
{
	static const uint16_t reg[14] = { 0x408, 0x40a, 0x40c, 0x40e, 0x418, 0x41a, 0x41c, 0x428, 0x42a, 0x42c, 0x440, 0x442, 0x444, 0x446 };

	if (!ready) {
		return false;
	}
	for (uint32_t i = 0; i < count && i < 14; i++) {
		uint32_t lo = gpu_rd(reg[i]);
		out[i] = ((uint64_t)gpu_rd(reg[i] + 1u) << 32) | lo;
	}
	return true;
}
''')

m = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'
patch(m, '''extern "C" bool redwood_gpu_stats(''', '''extern "C" bool redwood_gpu_counters(uint64_t *out, uint32_t count);
extern "C" bool redwood_gpu_stats(''')
patch(m, '''		if (top_n != 0) {
			proc_line(ns);
		}
''', '''		{
			/* the GPU's own counters, as the change over the period (xnu/src/mk_gpucounters.py) */
			static uint64_t was[14];
			static bool had;
			uint64_t c[14], d[14];
			if (redwood_gpu_counters(c, 14)) {
				for (int i = 0; i < 14; i++) {
					d[i] = c[i] >= was[i] ? c[i] - was[i] : 0;      /* (a GPU reset starts them again) */
					was[i] = c[i];
				}
				if (had && ns != 0) {
					IOLog("LVG %llu ms: tpbeat %llu spbeat %llu latcyc %llu latn %llu | tpbusy %llu tpreq %llu tpmiss %llu | "
					    "spalu %llu spbusy %llu spidle %llu | rbbusy %llu rbpass %llu rbstall %llu rbfifo %llu\\n", ns / 1000000,
					    d[0], d[1], d[2], d[3], d[4], d[5], d[6], d[7], d[8], d[9], d[10], d[11], d[12], d[13]);
				}
				had = true;
			} else {
				had = false;
			}
		}
		if (top_n != 0) {
			proc_line(ns);
		}
''')
print('ok')
