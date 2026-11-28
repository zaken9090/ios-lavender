"""lavender: GPU SMMU implementation-defined registers - read them, write them one by one (patch 1171).

A GPU memory request waits ~800 ns even when the GPU is nearly idle (LVG latcyc/latn: ~250 cycles at
300 MHz, ~550 at 600 MHz), the same with DDR at 1017.6 and 1804.8 MHz (runs ah3, ah4, ah6): the wait
is neither in the GPU core nor in the DDR. About 3/4 of a home-screen frame's GPU time is that wait
(300 -> 600 MHz gives only 21.6 -> 24.6 fps). All GPU traffic passes the GPU SMMU (bypass) and Linux
programs its attach-impl-defs (DT arm,smmu-kgsl@5040000) under a halt; we never did: the 2026-11-25
try (lv_smmu_impl=1, all at once) hung the phone at 0x6000 (micro-MMU control).

  lv_smmu_impl=2   log the 12 registers' current values (reads only), write nothing
  lv_smmu_impl=3   as 2, then write the ones whose value differs, except 0x6000, each logged first and
                   read back after (lv_smmu_impl_mask=N: only entries whose bit is set, bit 0 = 0x6000)
  lv_smmu_impl=1   as before (all, at once)

usage: python mk_smmuimpl.py XNU_TREE   (after mk_gpuvbif.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


r = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
patch(r, '''	lavender_gpu_smmu_dump("before");
	if (level < 10) {
		return;
	}
	static const uint32_t impl[][2] = {     /* DT attach-impl-defs */
		{ 0x6000, 0x2378 }, { 0x6060, 0x1055 }, { 0x678c, 0x08 }, { 0x6794, 0x28 }, { 0x6800, 0x06 },
		{ 0x6900, 0x3ff }, { 0x6924, 0x204 }, { 0x6928, 0x11000 }, { 0x6930, 0x800 }, { 0x6960, 0xffffffff },
		{ 0x6b64, 0x1a5551 }, { 0x6b68, 0x9a82a382 },
	};
''', '''	lavender_gpu_smmu_dump("before");
	static const uint32_t impl[][2] = {     /* DT attach-impl-defs */
		{ 0x6000, 0x2378 }, { 0x6060, 0x1055 }, { 0x678c, 0x08 }, { 0x6794, 0x28 }, { 0x6800, 0x06 },
		{ 0x6900, 0x3ff }, { 0x6924, 0x204 }, { 0x6928, 0x11000 }, { 0x6930, 0x800 }, { 0x6960, 0xffffffff },
		{ 0x6b64, 0x1a5551 }, { 0x6b68, 0x9a82a382 },
	};
	{
		/* lavender (mk_smmuimpl.py): lv_smmu_impl=2 reads them, 3 also writes those that differ */
		uint32_t mode = 0, mask = 0xffeu;
		PE_parse_boot_argn("lv_smmu_impl", &mode, sizeof(mode));
		PE_parse_boot_argn("lv_smmu_impl_mask", &mask, sizeof(mask));
		if (mode >= 2) {
			for (unsigned i = 0; i < sizeof(impl) / sizeof(impl[0]); i++) {
				LOG("LVSMMU impl read %#x", impl[i][0]);
				uint32_t was = sr(impl[i][0]);
				LOG("LVSMMU impl %#x = %#x (Linux %#x)", impl[i][0], was, impl[i][1]);
				if (mode == 3 && (mask & (1u << i)) && was != impl[i][1]) {
					LOG("LVSMMU impl write %#x = %#x", impl[i][0], impl[i][1]);
					sw(impl[i][0], impl[i][1]);
					LOG("LVSMMU impl %#x now %#x", impl[i][0], sr(impl[i][0]));
				}
			}
		}
	}
	if (level < 10) {
		return;
	}
''')
patch(r, '''	for (unsigned i = 0; do_impl && i < sizeof(impl) / sizeof(impl[0]); i++) {''',
      '''	for (unsigned i = 0; do_impl == 1 && i < sizeof(impl) / sizeof(impl[0]); i++) {''')
print('ok')
