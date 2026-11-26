"""lavender: the Wi-Fi radio code uses lavender's addresses (patch 1080), MODEM-PLAN step 7.

Run e84 (1078): the WLAN firmware reports FW_READY and takes mission mode. The radio code after
it (copy engines, HTC, WMI, scan; ported for topaz) has topaz's addresses: WCN membase 0x0C800000
and the apps SMMU 0x0C600000 with stream 0x1A0 - with wifi=1 the kernel's modem thread hung at
that SMMU before the modem was even started (run e81). lavender (stock DT qcom,icnss@18800000):
membase 0x18800000 (copy engines at +0x240000, shadow registers at +0x32000), SMMU anoc2 0x16C0000
stream 0x1A00/1 - already handled by lv_wlan_smmu() (1055), which wifi=1 now turns on.

usage: python mk_wlanaddr.py XNU_TREE   (after mk_wlfwcrc.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#define CE_PA               (0x0C800000ull + 0x240000)''', '''#define WCN_MEMBASE         0x18800000ull       /* lavender: qcom,icnss@18800000 (mk_wlanaddr.py) */
#define CE_PA               (WCN_MEMBASE + 0x240000)''')
sub('''#define SHADOW_PA           (0x0C800000ull + 0x32000)''', '''#define SHADOW_PA           (WCN_MEMBASE + 0x32000)''')
sub('''	if (wifi_enabled() && !smmu_identity(WLAN_SID, WLAN_SID_MASK, "WLAN")) {
		LOG("wifi: no SMMU stream for WLAN, the radio stays off");
		wifi_on = 0;
	}
''', '''	if (wifi_enabled()) {
		/* lavender: the WLAN stream sits on the anoc2 SMMU; programmed before the modem starts (lv_wlan_smmu) */
		lv_wlan_smmu_mode = 2;
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
