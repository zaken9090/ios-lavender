"""lavender: boot-arg lv_gpu_mhz=600 - the Adreno 512 core at 600 MHz (GPLL0 / 1) on the TURBO rail level (patch 1026).

The core ran at 300 MHz (GPLL0 / 2) with the GX rail (PM660L S3 over RPM) at level 0x80 (SVS).
The stock table (DT qcom,gpu-pwrlevels) goes up to 647 MHz at gfx corner 7 = rail level 0x180;
588 MHz is corner 6 (0x140). 600 MHz straight from GPLL0 needs no GPU PLL: with lv_gpu_mhz=600 the
rail is voted to 0x180 first (unless lv_gfx_lvl says otherwise) and then the gfx3d RCG divider goes
from 2 to 1. Default stays 300 MHz until measured.

usage: python mk_gpu600.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	uint32_t lvl = 0x80;
	PE_parse_boot_argn("lv_gfx_lvl", &lvl, sizeof(lvl));
	if (lvl) {
		bool en = topaz_rpm_write(0, 0x62706d73u /* smpb */, 3, 0x6e657773u /* swen */, 1);
		bool lv = topaz_rpm_write(0, 0x62706d73u, 3, 0x6c766c76u /* vlvl */, lvl);
		LOG("LVGPU GX rail smpb3 swen %s vlvl %#x %s", en ? "acked" : "FAILED", lvl, lv ? "acked" : "FAILED");
		IODelay(2000);
	}
''', '''	uint32_t lvl = 0x80, mhz = 300;
	/* lavender: lv_gpu_mhz=600 - GPLL0 / 1 on rail level 0x180 (gfx corner 7, good to 647 MHz); mk_gpu600.py */
	PE_parse_boot_argn("lv_gpu_mhz", &mhz, sizeof(mhz));
	if (mhz >= 600) {
		lvl = 0x180;
	}
	PE_parse_boot_argn("lv_gfx_lvl", &lvl, sizeof(lvl));
	if (lvl) {
		bool en = topaz_rpm_write(0, 0x62706d73u /* smpb */, 3, 0x6e657773u /* swen */, 1);
		bool lv = topaz_rpm_write(0, 0x62706d73u, 3, 0x6c766c76u /* vlvl */, lvl);
		LOG("LVGPU GX rail smpb3 swen %s vlvl %#x %s", en ? "acked" : "FAILED", lvl, lv ? "acked" : "FAILED");
		IODelay(2000);
		if (mhz >= 600 && en && lv && lvl >= 0x180) {
			IODelay(3000);                                  /* the rail settles before the clock goes up */
			lv_w(lv_gpucc, 0x1074, (5u << 8) | 1u);         /* GPLL0 / 1 = 600 MHz */
			lv_w(lv_gpucc, 0x1070, lv_r(lv_gpucc, 0x1070) | 1u);
			for (int i = 0; i < 200 && (lv_r(lv_gpucc, 0x1070) & 1u); i++) {
				IODelay(10);
			}
			LOG("LVGPU gfx3d 600 MHz: rcg cmd %#x cfg %#x", lv_r(lv_gpucc, 0x1070), lv_r(lv_gpucc, 0x1074));
		}
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
