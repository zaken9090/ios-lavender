"""lavender: the Wi-Fi chip is powered before the WLAN firmware is started (patch 1052).

Runs e48/e49: 13.4 s after the modem starts it dies of "Task starvation: diag"; run e50 with
modem_wlfw=0 (no WLFW handshake) has no such crash. So it is the WLAN firmware, started by our
handshake, that hangs - and the WCN3990 it drives had no supply at all: the base code (topaz)
votes nothing. Android's icnss turns the chip on when the WLFW service arrives, before the first
message. The same here, through the RPM (stock DT, qcom,icnss@18800000):

  vdd-0.8-cx-mx  PM660 LDO5   848000 uV      vdd-1.8-xo   PM660 LDO9  1800000 uV
  vdd-1.3-rfa    PM660 LDO6  1304000 uV      vdd-3.3-ch0  PM660 LDO19 3312000 uV
  cxo_ref_clk_pin: RF_CLK1, RPM clock buffer "clka" id 4, software enable

RPM regulator "ldoa" (0x616f646c), keys "uv" (0x7675) and "swen" (0x6e657773), active set.
modem_wlpwr=0 skips it.

usage: python mk_wlanpower.py XNU_TREE   (after mk_modemwlfw.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	if (wl == 0) {
		LOG("WLFW left alone (modem_wlfw=0)");
		return;
	}
''', '''	if (wl == 0) {
		LOG("WLFW left alone (modem_wlfw=0)");
		return;
	}
	wlan_power_on();
''')
sub('''static unsigned w_arrivals, w_cap_tries, w_cap_retry_ms;
''', '''static unsigned w_arrivals, w_cap_tries, w_cap_retry_ms;

extern "C" bool topaz_rpm_write(uint32_t set, uint32_t type, uint32_t id, uint32_t key, uint32_t value);

/* lavender: the WCN3990's supplies and reference clock, as Android's icnss_hw_power_on() */
static void
wlan_power_on(void)
{
	static bool done;
	static const struct { const char *name; uint32_t ldo, uv; } rail[] = {
		{ "vdd-0.8-cx-mx (L5)", 5, 848000 }, { "vdd-1.8-xo (L9)", 9, 1800000 },
		{ "vdd-1.3-rfa (L6)", 6, 1304000 }, { "vdd-3.3-ch0 (L19)", 19, 3312000 },
	};
	uint32_t on = 1;
	(void)PE_parse_boot_argn("modem_wlpwr", &on, sizeof(on));
	if (done || on == 0) {
		return;
	}
	done = true;
	for (unsigned i = 0; i < sizeof(rail) / sizeof(rail[0]); i++) {
		bool uv = topaz_rpm_write(0, 0x616f646cu, rail[i].ldo, 0x00007675u, rail[i].uv);
		bool en = topaz_rpm_write(0, 0x616f646cu, rail[i].ldo, 0x6e657773u, 1);
		LOG("wlan power: %s %u uV: voltage %s, enable %s", rail[i].name, rail[i].uv, uv ? "acked" : "FAILED", en ? "acked" : "FAILED");
		IODelay(500);
	}
	bool ck = topaz_rpm_write(0, 0x616b6c63u, 4, 0x6e657773u, 1);
	LOG("wlan power: RF_CLK1 (clka 4): %s", ck ? "acked" : "FAILED");
	IOSleep(5);
}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
