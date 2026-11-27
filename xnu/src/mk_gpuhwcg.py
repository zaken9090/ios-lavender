"""lavender: GPU hang hunt - hardware clock gating as a boot-arg (patch 1140).

The hangs (GPU-PLAN "GPU hang") stop in a draw with RAS/RB/PC busy; the A5xx init matches Linux and
Xiaomi's KGSL. Clock gating (a512_hwcg table + RBBM_CLOCK_CNTL 0xAAA8AA00) is the classic source of RB
stalls, so it gets a switch: gpu_hwcg=0 leaves every block clock on (RBBM_CLOCK_CNTL 0, as KGSL in ISDB
mode); default 1 = as before. Costs power only, not picture quality.

usage: python mk_gpuhwcg.py XNU_TREE   (after mk_gpuhang1.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


rpm = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
patch(rpm, '''	for (unsigned i = 0; i < sizeof(a512_hwcg) / sizeof(a512_hwcg[0]); i++) {
		g_w(a512_hwcg[i][0], a512_hwcg[i][1]);
	}
	g_w(A5_RBBM_CLOCK_CNTL, 0xAAA8AA00);
	g_w(A5_RBBM_ISDB_CNT, 0x182);''', '''	uint32_t hwcg = 1;
	PE_parse_boot_argn("gpu_hwcg", &hwcg, sizeof(hwcg));
	if (hwcg != 0) {
		for (unsigned i = 0; i < sizeof(a512_hwcg) / sizeof(a512_hwcg[0]); i++) {
			g_w(a512_hwcg[i][0], a512_hwcg[i][1]);
		}
		g_w(A5_RBBM_CLOCK_CNTL, 0xAAA8AA00);
		g_w(A5_RBBM_ISDB_CNT, 0x182);
	} else {
		for (unsigned i = 0; i < sizeof(a512_hwcg) / sizeof(a512_hwcg[0]); i++) {
			g_w(a512_hwcg[i][0], 0);        /* as KGSL a5xx_hwcg_set(false) */
		}
		g_w(A5_RBBM_CLOCK_CNTL, 0);             /* gpu_hwcg=0: all clocks on (mk_gpuhwcg.py) */
		g_w(A5_RBBM_ISDB_CNT, 0);
	}''')
print('ok')
