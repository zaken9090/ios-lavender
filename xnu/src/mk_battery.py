"""lavender: iOS gets the battery from the PM660 fuel gauge (patch 1168, boot-arg lv_battery=0: as before).

SweetBattery (the base's IOPMPowerSource) knows the sweet phone's PM6150 and the topaz I2C gauge; on
lavender neither answers and iOS was shown a static 100 %, on external power, not charging. The PM660
has a fuel gauge of its own (Linux qcom fg-gen3) and the charger (smb2), both on SPMI slave 0:

  0x4009        BATT_SOC_FG_MONOTONIC_SOC: the gauge's state of charge, 0..255
  0x4150/51     BATT_INFO_BATT_TEMP: 0.25 K a step, 11 bits
  0x41A0/A1     BATT_INFO_VBATT: 122.07 uV a step
  0x41A2/A3     BATT_INFO_IBATT: 488.281 uA a step, positive = discharging (Linux)
  0x1006        BATTERY_CHARGER_STATUS_1: bits 2..0 = 0 trickle, 1 pre, 2 fast, 3 full-on, 4 taper,
                5 terminated, 6 inhibited, 7 disabled
  0x1310        USBIN_INT_RT_STS: bit 4 = USB plugged in

Read every 10 seconds through lv_pmic_byte (the SPMI lock of patch 1163). Capacity as Linux reports
it: (msoc - 1) * 98 / 253 + 1, rounded up; 100 when the charger has terminated. The design capacity
is the Redmi Note 7 cell's 4000 mAh. Only read: nothing is written to the gauge or the charger.

usage: python mk_battery.py XNU_TREE   (after mk_spmilock.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


b = f'{tree}/iokit/Kernel/arm/SweetBattery.cpp'
patch(b, '''extern "C" int sweet_i2c1_write(uint8_t addr, uint8_t reg, uint8_t val);
''', '''extern "C" int sweet_i2c1_write(uint8_t addr, uint8_t reg, uint8_t val);
/* bsd/dev/sweet_usb.c: one PMIC byte under the SPMI lock (lavender, patch 1163) */
extern "C" int lv_pmic_byte(int write, unsigned addr, uint8_t *val);
''')
patch(b, '''	bool fTimerAdded, fRunning, fReal;
''', '''	bool fTimerAdded, fRunning, fReal, fLavender;
''')
patch(b, '''	bool pollTopaz(void);
''', '''	bool pollTopaz(void);
	bool pollLavender(void);
	unsigned fDesign;
	int fTenths;                    /* battery temperature, 0.1 C (lavender) */
''')
patch(b, '''	fTimerAdded = fRunning = fReal = false;
''', '''	fTimerAdded = fRunning = fReal = fLavender = false;
	fDesign = 5020;
	fTenths = 250;
''')
# capacity and temperature from the source in use
patch(b, '''	const unsigned capacity = (5020u * percent + 50u) / 100u;''', '''	const unsigned capacity = (fDesign * percent + 50u) / 100u;''')
patch(b, '''	setMaxCapacity(5020);''', '''	setMaxCapacity(fDesign);''')
patch(b, '''	putNumber("AppleRawMaxCapacity", 5020);
	putNumber("DesignCapacity", 5020);''', '''	putNumber("AppleRawMaxCapacity", fDesign);
	putNumber("DesignCapacity", fDesign);''')
patch(b, '''	putNumber("Temperature", 2500);''', '''	putNumber("Temperature", (UInt32)(fTenths * 10));''')
patch(b, '''	putBool("SweetBatteryTemperatureEstimated", true);''', '''	putBool("SweetBatteryTemperatureEstimated", !fLavender);''')
patch(b, '''		UInt32 values[] = {capacity, 5020, mv, (UInt32)ma, 0,''', '''		UInt32 values[] = {capacity, fDesign, mv, (UInt32)ma, 0,''')
patch(b, '''		IOLog("SWEET BATTERY: %s, %u%% %umV external=%d charging=%d\\n",
		    measured ? "PM6150 / estimated SOC" : "static fallback",''', '''		IOLog("SWEET BATTERY: %s, %u%% %umV external=%d charging=%d\\n",
		    !measured ? "static fallback" : fLavender ? "PM660 fuel gauge" : "PM6150 / estimated SOC",''')

patch(b, '''void
SweetBattery::poll(void)
{
	if (fReal && pollTopaz()) {''', '''/* lavender (mk_battery.py): the PM660 fuel gauge and charger, read only */
bool
SweetBattery::pollLavender(void)
{
	static const unsigned at[] = { 0x4009, 0x4150, 0x4151, 0x41a0, 0x41a1, 0x41a2, 0x41a3, 0x1006, 0x1310 };
	uint8_t v[sizeof(at) / sizeof(at[0])];
	static unsigned logs;

	for (unsigned i = 0; i < sizeof(at) / sizeof(at[0]); i++) {
		if (lv_pmic_byte(0, at[i], &v[i]) != 0) {
			return false;
		}
	}
	unsigned msoc = v[0];
	int kelvin4 = ((v[2] & 7) << 8) | v[1];
	int mv = (int)(int16_t)(v[3] | (v[4] << 8)) * 12207 / 100000;
	int ma = (int)((int64_t)(int16_t)(v[5] | (v[6] << 8)) * 488281 / 1000000);
	unsigned state = v[7] & 7u;
	bool external = (v[8] & 0x10u) != 0;

	if (mv < 2800 || mv > 4600 || kelvin4 == 0) {
		return false;                   /* (a gauge not running yet: not 0 %) */
	}
	unsigned percent = msoc == 0 ? 0 : ((msoc - 1) * 98u + 252u) / 253u + 1u;
	if (percent > 100) {
		percent = 100;
	}
	bool full = external && state == 5;
	bool charging = external && state <= 4;
	fTenths = ((kelvin4 + 2) / 4 - 273) * 10;
	fDesign = 4000;
	/* IOPMPowerSource: positive = into the battery */
	publish(full ? 100 : percent, (unsigned)mv, -ma, external, external, charging, full, true, true);
	if (logs++ % 30 == 0) {
		IOLog("SWEET BATTERY: PM660 %u%% (msoc %u) %d mV %d mA %d.%d C charger %u usb %d\\n", full ? 100 : percent, msoc, mv, -ma,
		    fTenths / 10, fTenths % 10, state, external);
	}
	return true;
}

void
SweetBattery::poll(void)
{
	if (fLavender && pollLavender()) {
		return;
	}
	if (fLavender) {
		publish(100, 4200, 0, true, true, false, true, false, false);
		return;
	}
	if (fReal && pollTopaz()) {''')
patch(b, '''	fReal = real == 1 && sweet_i2c1_init() == 0;
	/* Publish a complete source BEFORE registerService wakes powerd. */
	poll();
	if (fReal) {''', '''	int lavender = 1;       /* lavender (mk_battery.py): the PM660 gauge; lv_battery=0 for what was before */
	(void)PE_parse_boot_argn("lv_battery", &lavender, sizeof(lavender));
	fLavender = lavender != 0;
	fReal = !fLavender && real == 1 && sweet_i2c1_init() == 0;
	/* Publish a complete source BEFORE registerService wakes powerd. */
	poll();
	if (fReal || fLavender) {''')
patch(b, '''			fReal = false;
			poll();''', '''			fReal = fLavender = false;
			poll();''')
print('ok')
