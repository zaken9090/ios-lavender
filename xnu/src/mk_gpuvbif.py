"""lavender: how many bytes the GPU moves to and from memory - an LVV line of VBIF counters (patch 1170).

The home screen is GPU-bound (busy 95 %) at 300 and 600 MHz alike and waits ~220 cycles a memory
request (LVG): it looks memory-bound, ~0.7 Gpx/s. Whether that is the DDR's ceiling (~14.9 GB/s on
LPDDR4x 1866, x32 x2) or something below it (DDR vote, bus clocks, QoS) shows in the bytes the GPU's
bus interface (VBIF) really moves. kgsl gives no a5xx VBIF countable numbers, so the countables are
picked by boot-arg and can be swept:

  lv_vbif=0xDDCCBBAA   countables AA, BB, CC, DD (0..127) on VBIF counters 0-3, every second
  lv_vbif_sweep=1      countables 0-3, then 4-7, ... 124-127, a new four every second (32 s a round)
  (neither: no LVV line, no VBIF register touched - as before)

  LVV <ms>: sel A B C D: vA vB vC vD | pwr P0 P1 P2

Each value is the count over the last period (the counter is cleared after it is read, as kgsl:
CLR 1 then 0, SEL, EN 1; registers from a5xx_reg.h: EN 0x30c0, CLR 0x30c8, SEL 0x30d0, LOW 0x30d8,
HIGH 0x30e0; power counters EN 0x3100, CLR 0x3108, LOW 0x3110, HIGH 0x3118).

usage: python mk_gpuvbif.py XNU_TREE   (after mk_gpuopcode.py / mk_battery.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


ad = f'{tree}/iokit/Kernel/arm/TopazAdreno.cpp'
patch(ad, '''bool redwood_gpu_counters(uint64_t *out, uint32_t count);
''', '''bool redwood_gpu_counters(uint64_t *out, uint32_t count);
bool redwood_gpu_vbif(uint64_t *out, const uint8_t *sel_next);
''')
patch(ad, '''/*
 * lavender (mk_gpucounters.py): the counters of the LVG line, in its order: UCHE 0-3, TP 0-2, SP 0-2,
''', '''/*
 * lavender (mk_gpuvbif.py): VBIF counters 0-3 and power counters 0-2 into out[0..6] (counts since the
 * last call), then cleared and counters 0-3 set to countables sel_next[0..3].
 */
bool
redwood_gpu_vbif(uint64_t *out, const uint8_t *sel_next)
{
	if (!ready) {
		return false;
	}
	for (uint32_t n = 0; n < 4; n++) {
		uint32_t lo = gpu_rd(0x30d8 + n);
		out[n] = ((uint64_t)gpu_rd(0x30e0 + n) << 32) | lo;
		gpu_wr(0x30c8 + n, 1);
		gpu_wr(0x30c8 + n, 0);
		gpu_wr(0x30d0 + n, sel_next[n] & 0x7fu);
		gpu_wr(0x30c0 + n, 1);
	}
	for (uint32_t n = 0; n < 3; n++) {
		uint32_t lo = gpu_rd(0x3110 + n);
		out[4 + n] = ((uint64_t)gpu_rd(0x3118 + n) << 32) | lo;
		gpu_wr(0x3108 + n, 1);
		gpu_wr(0x3108 + n, 0);
		gpu_wr(0x3100 + n, 1);
	}
	return true;
}

/*
 * lavender (mk_gpucounters.py): the counters of the LVG line, in its order: UCHE 0-3, TP 0-2, SP 0-2,
''')

m = f'{tree}/iokit/Kernel/arm/LavenderMetrics.cpp'
patch(m, '''extern "C" bool redwood_gpu_counters(uint64_t *out, uint32_t count);
''', '''extern "C" bool redwood_gpu_counters(uint64_t *out, uint32_t count);
extern "C" bool redwood_gpu_vbif(uint64_t *out, const uint8_t *sel_next);
static uint32_t vbif_sel, vbif_sweep;      /* lv_vbif, lv_vbif_sweep (mk_gpuvbif.py) */
''')
patch(m, '''		if (top_n != 0 && !quiet) {
			proc_line(ns);
		}
''', '''		if (vbif_sel != 0 || vbif_sweep != 0) {
			/* VBIF bytes moved (xnu/src/mk_gpuvbif.py) */
			static uint8_t cur[4];
			static bool vhad;
			static uint32_t base;
			uint8_t next[4];
			uint64_t v[7];
			for (int i = 0; i < 4; i++) {
				next[i] = vbif_sweep != 0 ? (uint8_t)((base + i) & 0x7f) : (uint8_t)(vbif_sel >> (8 * i));
			}
			if (redwood_gpu_vbif(v, next)) {
				if (vhad && ns != 0) {
					IOLog("LVV %llu ms: sel %u %u %u %u: %llu %llu %llu %llu | pwr %llu %llu %llu\\n", ns / 1000000,
					    cur[0], cur[1], cur[2], cur[3], v[0], v[1], v[2], v[3], v[4], v[5], v[6]);
				}
				for (int i = 0; i < 4; i++) {
					cur[i] = next[i];
				}
				if (vbif_sweep != 0) {
					base = (base + 4) & 0x7f;
				}
				vhad = true;
			} else {
				vhad = false;
			}
		}
		if (top_n != 0 && !quiet) {
			proc_line(ns);
		}
''')
patch(m, '''	(void)PE_parse_boot_argn("lv_metrics_top", &top_n, sizeof(top_n));
''', '''	(void)PE_parse_boot_argn("lv_metrics_top", &top_n, sizeof(top_n));
	(void)PE_parse_boot_argn("lv_vbif", &vbif_sel, sizeof(vbif_sel));
	(void)PE_parse_boot_argn("lv_vbif_sweep", &vbif_sweep, sizeof(vbif_sweep));
''')
print('ok')
