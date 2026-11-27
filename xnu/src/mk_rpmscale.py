"""lavender: RPM clock scaling on, so a DDR vote takes effect (patch 1141; first project 1025).

The RPM ignores the apps side's clock votes until clock scaling is turned on (Linux clk-smd-rpm.c
clk_smd_rpm_enable_scaling: clk0 id 2, key "Enab" = 1, sleep then active set); before it, BIMC
stayed at 648 MHz whatever lv_ddr_khz voted (memcpy speed unchanged, PLAN.md E8). Once on, a clock
nobody votes for may drop, so first the buses Android's msm_bus keeps up get votes in both sets
(snoc 200, cnoc 100, cnoc_periph 50, mmssnoc_axi 320 - the display -, aggre2 150 MHz).

Boot-args: lv_rpm_scale=1 turns it on (default 0: as before); lv_ddr_khz=N votes DDR (clk2 id 0) in
both sets after that (first project bench: 1804800, measured 1804.8 MHz); the memcpy speed is
measured before and after (as lv_ddr_bench=1).

usage: python mk_rpmscale.py XNU_TREE   (after mk_gpuhwcg.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


rpm = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
patch(rpm, '''	uint32_t khz = 0, bench = 0;
	PE_parse_boot_argn("lv_ddr_khz", &khz, sizeof(khz));
	PE_parse_boot_argn("lv_ddr_bench", &bench, sizeof(bench));
	if (bench != 0 || khz != 0) {
		IOSleep(2000);
		lavender_memcpy_speed("before");
	}
	if (khz != 0) {
		bool ok = topaz_rpm_write(0, RPM_MEM_CLK, 0, RPM_KEY_KHZ, khz);
		LOG("LVDDR vote %u kHz -> %s", khz, ok ? "acked" : "FAILED");''', '''	uint32_t khz = 0, bench = 0, scale = 0;
	PE_parse_boot_argn("lv_ddr_khz", &khz, sizeof(khz));
	PE_parse_boot_argn("lv_ddr_bench", &bench, sizeof(bench));
	PE_parse_boot_argn("lv_rpm_scale", &scale, sizeof(scale));
	if (bench != 0 || khz != 0 || scale != 0) {
		IOSleep(2000);
		lavender_memcpy_speed("before");
	}
	if (scale != 0) {
		/* mk_rpmscale.py: buses kept up in both sets, then clock scaling on (clk0 2 "Enab") */
		static const struct { uint32_t type, id, khz; } bus[] = {
			{ 0x316b6c63u /* clk1 */, 1, 200000 },  /* snoc */
			{ 0x316b6c63u /* clk1 */, 2, 100000 },  /* cnoc */
			{ 0x316b6c63u /* clk1 */, 0, 50000 },   /* cnoc_periph */
			{ 0x69786d6du /* mmxi */, 0, 320000 },  /* mmssnoc_axi */
			{ 0x616b6c63u /* clka */, 2, 150000 },  /* aggre2_noc */
		};
		bool bok = true;
		for (unsigned i = 0; i < sizeof(bus) / sizeof(bus[0]); i++) {
			bok &= topaz_rpm_write(1, bus[i].type, bus[i].id, RPM_KEY_KHZ, bus[i].khz);
			bok &= topaz_rpm_write(0, bus[i].type, bus[i].id, RPM_KEY_KHZ, bus[i].khz);
		}
		if (khz != 0) {
			bok &= topaz_rpm_write(1, RPM_MEM_CLK, 0, RPM_KEY_KHZ, khz);
		}
		bool sok = bok && topaz_rpm_write(1, 0x306b6c63u /* clk0 */, 2, 0x62616e45u /* Enab */, 1) &&
		    topaz_rpm_write(0, 0x306b6c63u /* clk0 */, 2, 0x62616e45u /* Enab */, 1);
		LOG("LVDDR bus votes %s, RPM clock scaling %s", bok ? "ok" : "FAILED", sok ? "ON" : "not on");
		if (khz == 0) {
			IOSleep(100);
			lavender_memcpy_speed("after scaling on");
		}
	}
	if (khz != 0) {
		bool ok = topaz_rpm_write(0, RPM_MEM_CLK, 0, RPM_KEY_KHZ, khz);
		LOG("LVDDR vote %u kHz -> %s", khz, ok ? "acked" : "FAILED");''')
print('ok')
