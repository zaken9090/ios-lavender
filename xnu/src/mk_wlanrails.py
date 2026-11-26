"""lavender: the Wi-Fi chip's supplies are read back from the PMIC (patch 1054).

Bisect e53: the modem stays up through ind_register, msa_info and msa_ready; it is the WLFW "cap"
request after which the WLAN firmware hangs (diag starvation 12 s later) - the request that makes
the firmware talk to the WCN3990. The RPM acked all four supplies and the clock (1052), but an ack
is not a voltage. The regulators' own registers are read over SPMI before and after the votes:
PM660 (slave 1) LDO n at 0x4000 + 0x100 * (n - 1): STATUS1 +0x08 (bit 7 = output in regulation),
EN_CTL +0x46 (bit 7 = enabled), voltage +0x40/+0x41 (mV, new-style LDOs); PM660 (slave 0) clock
buffers 0x5100..0x5500: STATUS +0x08, EN_CTL +0x46.

usage: python mk_wlanrails.py XNU_TREE   (after mk_wlfwsteps.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''/* lavender: the WCN3990's supplies and reference clock, as Android's icnss_hw_power_on() */
static void
wlan_power_on(void)
{
''', '''extern "C" int lv_pmic_byte(int write, unsigned addr, uint8_t *val);    /* bsd/dev/sweet_usb.c */

static void
wlan_rails_log(const char *when)
{
	static const uint8_t ldo[] = { 5, 9, 6, 19 };
	for (unsigned i = 0; i < sizeof(ldo); i++) {
		unsigned base = (1u << 16) | (0x4000u + 0x100u * (ldo[i] - 1));
		uint8_t st = 0, en = 0, lo = 0, hi = 0;
		int r = lv_pmic_byte(0, base + 0x08, &st) | lv_pmic_byte(0, base + 0x46, &en) | lv_pmic_byte(0, base + 0x40, &lo) |
		    lv_pmic_byte(0, base + 0x41, &hi);
		LOG("wlan rails %s: PM660 L%u status %#x enable %#x voltage %u mV (read %d)", when, ldo[i], st, en, lo | (hi << 8), r);
	}
	for (unsigned c = 0x5100; c <= 0x5500; c += 0x100) {
		uint8_t st = 0, en = 0;
		int r = lv_pmic_byte(0, c + 0x08, &st) | lv_pmic_byte(0, c + 0x46, &en);
		LOG("wlan rails %s: PM660 clock buffer %#x status %#x enable %#x (read %d)", when, c, st, en, r);
	}
}

/* lavender: the WCN3990's supplies and reference clock, as Android's icnss_hw_power_on() */
static void
wlan_power_on(void)
{
''')
sub('''	done = true;
	for (unsigned i = 0; i < sizeof(rail) / sizeof(rail[0]); i++) {''', '''	done = true;
	wlan_rails_log("before");
	for (unsigned i = 0; i < sizeof(rail) / sizeof(rail[0]); i++) {''')
sub('''	LOG("wlan power: RF_CLK1 (clka 4): %s", ck ? "acked" : "FAILED");
	IOSleep(5);
''', '''	LOG("wlan power: RF_CLK1 (clka 4): %s", ck ? "acked" : "FAILED");
	IOSleep(5);
	wlan_rails_log("after");
''')
open(path, 'w', newline='\n').write(s)
print('ok')
