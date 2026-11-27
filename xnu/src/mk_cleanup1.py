"""lavender: cleanup 1 - Wi-Fi tries out, default-on logs made opt-in (patch 1138).

LEFTOVERS.md "Clean up first" 2 and 3:
- 1056 MSA zeroing ("no change", 1 MB zeroed every boot): removed.
- 1081/1082 persist ext4 reader + name listing (persist has no MAC file; the address comes from
  NV 4678, 1083): removed. persist is no longer read at all.
- 1054 PMIC rails readback around the WLAN power-on: only with modem_wlrails=1.
- 1071/1074 QMUX payload log (QMI identifiers in the USB log): qmux_log default 0 (was 1500).
- 1059 baseband user-client call log: only with abp_log=1 (abp=1 still does the power hook).
- 1004 touch report log: sweettouchdiag default 0 (was 40).
- 1008 128 MB memcpy at every boot (+2 s): only with lv_ddr_bench=1 or lv_ddr_khz.
- 1017/1018/1033 process sampler (SMP/SMK/SMS/SMC lines): only when sweetsample= is given.

usage: python mk_cleanup1.py XNU_TREE   (after mk_bt32.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


def cut(path, start, end_after):
    s = open(path, newline='').read()
    a = s.index(start)
    b = s.index(end_after, a) + len(end_after)
    assert s.count(start) == 1
    open(path, 'w', newline='\n').write(s[:a] + s[b:])


tm = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'

# 1056
patch(tm, '''	static bool msa_cleared;
	uint32_t clear = 1;
	(void)PE_parse_boot_argn("modem_msa0", &clear, sizeof(clear));
	if (!msa_cleared && clear != 0) {
		/* lavender: no stale firmware state from the system that ran before this fastboot boot */
		IOMemoryMap *mm = map_phys(WLFW_MSA_BASE, WLFW_MSA_SIZE, true);
		if (mm != NULL) {
			volatile uint32_t *w = (volatile uint32_t *)mm->getVirtualAddress();
			uint32_t nz = 0;
			for (uint32_t i = 0; i < WLFW_MSA_SIZE / 4; i++) {
				nz += w[i] != 0;
			}
			LOG("wlfw: MSA %x+%x had %u non-zero words (first %08x %08x %08x %08x), zeroed", WLFW_MSA_BASE, WLFW_MSA_SIZE, nz,
			    w[0], w[1], w[2], w[3]);
			bzero((void *)mm->getVirtualAddress(), WLFW_MSA_SIZE);
			mb();
			mm->release();
			msa_cleared = true;
		}
	}
''', '')

# 1081/1082
patch(tm, 'static bool wlan_mac_from_persist(void);\n', '')
patch(tm, 'static bool nv_mac_asked, nv_mac_done, persist_mac_done;', 'static bool nv_mac_asked, nv_mac_done;')
patch(tm, '''				persist_mac_done = wlan_mac_from_persist();     /* mk_wlanmac.py */
				if (!persist_mac_done && nv_mac[0] | nv_mac[1] | nv_mac[2] | nv_mac[3] | nv_mac[4] | nv_mac[5]) {''',
      '''				if (nv_mac[0] | nv_mac[1] | nv_mac[2] | nv_mac[3] | nv_mac[4] | nv_mac[5]) {''')
patch(tm, '/* locally administered; persist\'s when found */', '/* locally administered; NV 4678\'s when read */')
cut(tm, '/* ---------------- read-only ext4 on a partition, for persist\'s wlan_mac.bin (mk_wlanmac.py) */\n',
    '''	LOG("wlan mac: %02x:%02x:%02x:**:**:** from persist (read only)", mac[0], mac[1], mac[2]);
	return true;
}
''')

# 1054
patch(tm, '''static void
wlan_rails_log(const char *when)
{
''', '''static void
wlan_rails_log(const char *when)
{
	uint32_t on = 0;
	(void)PE_parse_boot_argn("modem_wlrails", &on, sizeof(on));
	if (on == 0) {
		return;
	}
''')

# 1071/1074
patch(tm, 'static uint32_t qmux_log_max = 1500;', 'static uint32_t qmux_log_max = 0;              /* qmux_log=N: first N messages (QMI identifiers: keep local) */')

# 1059
sw = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
patch(sw, '''	static int verbose = -1;
	static unsigned calls[2];
	if (verbose < 0) {
		uint32_t abp = 0;
		verbose = PE_parse_boot_argn("abp", &abp, sizeof(abp)) && abp != 0;
	}''', '''	static int verbose = -1, calllog = 0;
	static unsigned calls[2];
	if (verbose < 0) {
		uint32_t abp = 0, cl = 0;
		verbose = PE_parse_boot_argn("abp", &abp, sizeof(abp)) && abp != 0;
		calllog = PE_parse_boot_argn("abp_log", &cl, sizeof(cl)) && cl != 0;
	}''')
patch(sw, '	if (verbose > 0 && calls[bb]++ < 300) {', '	if (calllog > 0 && calls[bb]++ < 300) {')

# 1004
patch(f'{tree}/bsd/dev/sweet_touch.c', '	lt.diag = 40;\n', '	lt.diag = 0;\n')

# 1008
rpm = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
patch(rpm, '''	uint32_t khz = 0;
	PE_parse_boot_argn("lv_ddr_khz", &khz, sizeof(khz));
	IOSleep(2000);
	lavender_memcpy_speed("before");
	if (khz != 0) {''', '''	uint32_t khz = 0, bench = 0;
	PE_parse_boot_argn("lv_ddr_khz", &khz, sizeof(khz));
	PE_parse_boot_argn("lv_ddr_bench", &bench, sizeof(bench));
	if (bench != 0 || khz != 0) {
		IOSleep(2000);
		lavender_memcpy_speed("before");
	}
	if (khz != 0) {''')

# sampler
sm = f'{tree}/bsd/dev/sweet_sample.c'
patch(sm, 'sweetsample (comma separated, default "SpringBoard,backboardd"; "-" = off)',
      'sweetsample (comma separated, e.g. "SpringBoard,backboardd"; absent or "-" = off)')
patch(sm, '''	if (!PE_parse_boot_argn("sweetsample", sweet_sample_names, sizeof(sweet_sample_names))) {
		strlcpy(sweet_sample_names, "SpringBoard,backboardd", sizeof(sweet_sample_names));
	}
	if (sweet_sample_names[0] == '-') {''', '''	if (!PE_parse_boot_argn("sweetsample", sweet_sample_names, sizeof(sweet_sample_names))) {
		return;                                 /* opt-in since mk_cleanup1.py */
	}
	if (sweet_sample_names[0] == '-' || sweet_sample_names[0] == 0) {''')
print('ok')
