'''lavender: the backlight (PM660L WLED) follows iOS: brightness, and off when iOS turns the display off (patch 1042).

The display stayed lit when iOS turned it off (a black frame under a lit backlight) and brightness
did nothing: the code for both drives a DSI panel's DCS commands (topaz), lavender has fDsi = NULL.
lavender's panel (Tianma NT36672A, video mode) is lit by the PM660L's WLED block (stock DT:
qcom,leds@d800 on SPMI slave 3, bl_ctrl_wled, levels 1..0xfff, strings 0 and 1). Registers as in
Linux leds-qpnp-wled.c: module enable ctrl+0x46 bit 7; per string n brightness LSB sink+0x57+0x10n,
MSB (4 bits) sink+0x58+0x10n; sync sink+0x47 = 0x0f then 0. Level 0 = module off.

- sweet_usb.c: lv_pmic_byte() - the SPMI byte access the reboot code has, for other drivers
  (address = slave << 16 | register).
- SweetFramebuffer.cpp: fWled when the block answers and its channels are ours; setPanelLevel()
  writes the WLED (DBV 1..0x7ff -> 3..0xfff); setPanelOn() without DSI only switches the light;
  IOMFBBrightnessLevel and RequestPowerChange work without DSI.
- Display off is still ignored with sweetfb_stayon=1 unless lv_sleep=1 (until waking is proven).
- The backlight service for CoreBrightness stays behind sweetbl=1 as before.

usage: python mk_wled.py XNU_TREE
'''
import sys

tree = sys.argv[1]


def patch(rel, subs):
    path = f'{tree}/{rel}'
    s = open(path, newline='').read()
    for old, new in subs:
        assert s.count(old) == 1, (rel, old[:70], s.count(old))
        s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


patch('bsd/dev/sweet_usb.c', [('''/* Read, change the masked bits, write back. */
static int
spmi_update(''', '''/*
 * lavender: one PMIC byte for other drivers (xnu/src/mk_wled.c): addr = slave << 16 | register.
 * 0 on success, -4 when the peripheral's channel is not the application CPU's to write.
 */
int lv_pmic_byte(int write, unsigned addr, uint8_t *val);
int
lv_pmic_byte(int write, unsigned addr, uint8_t *val)
{
	return spmi_byte(write != 0, addr, val);       /* (spmi_byte: channel of addr >> 8, register addr & 0xff) */
}

/* Read, change the masked bits, write back. */
static int
spmi_update(''')])

patch('iokit/Kernel/arm/SweetFramebuffer.cpp', [
    ('''extern "C" void topaz_modem_init(void);
''', '''extern "C" void topaz_modem_init(void);
extern "C" int lv_pmic_byte(int write, unsigned addr, uint8_t *val);    /* bsd/dev/sweet_usb.c */
#define LV_WLED_CTRL    0x3d800u        /* PM660L (slave 3) WLED control block */
#define LV_WLED_SINK    0x3d900u        /* ... and its current sinks; strings 0 and 1 light the panel */
'''),
    ('''	void          setPanelLevel(uint32_t level);
''', '''	void          setPanelLevel(uint32_t level);
	bool          fWled;          /* lavender: the backlight is the PM660L's WLED (mk_wled.py) */
	bool          fWledOn;
	void          wledLevel(uint32_t level);
'''),
    ('''	fBlCall = thread_call_allocate(&AppleCLCD::blWork, this);
	if (fDsi != NULL) {
		IOLog("SWEET FB: DSI0 ctrl %#x, brightness via DCS 0x51\\n", *(volatile uint32_t *)(fDsi + 0x004));
''', '''	fBlCall = thread_call_allocate(&AppleCLCD::blWork, this);
	{
		/* lavender: is the WLED there, lit by the bootloader, and ours to write? */
		uint8_t en = 0, lsb = 0, msb = 0, same = 0;
		int r = lv_pmic_byte(0, LV_WLED_CTRL + 0x46, &en);
		int r2 = lv_pmic_byte(0, LV_WLED_SINK + 0x57, &lsb) | lv_pmic_byte(0, LV_WLED_SINK + 0x58, &msb);
		int w = r == 0 ? lv_pmic_byte(1, LV_WLED_CTRL + 0x46, &en) : -1;      /* the same value back */
		int w2 = r2 == 0 ? lv_pmic_byte(1, LV_WLED_SINK + 0x57, &lsb) : -1;
		(void)lv_pmic_byte(0, LV_WLED_SINK + 0x67, &same);
		fWled = r == 0 && r2 == 0 && w == 0 && w2 == 0;
		fWledOn = (en & 0x80) != 0;
		IOLog("LV WLED: enable %#x (read %d, write %d), string 0 level %#x (read %d, write %d), string 1 lsb %#x: %s\\n",
		    en, r, w, ((msb & 0xf) << 8) | lsb, r2, w2, same, fWled ? "the backlight follows iOS" : "left alone");
		if (fWled && (((msb & 0xfu) << 8) | lsb) != 0) {
			fBlLevel = ((((uint32_t)msb & 0xf) << 8) | lsb) >> 1;   /* what the bootloader left */
			fBlSent = fBlLevel;
		}
	}
	if (fDsi != NULL || fWled) {
		if (fDsi != NULL) {
			IOLog("SWEET FB: DSI0 ctrl %#x, brightness via DCS 0x51\\n", *(volatile uint32_t *)(fDsi + 0x004));
		}
'''),
    ('''void
AppleCLCD::setPanelOn(bool on)
{
''', '''/*
 * lavender: the WLED at a level of 0..0x7ff (the DBV scale the rest of this file uses); 0 = off.
 * Order as in Linux qpnp_wled_work(): the brightness first, then the module on.
 */
void
AppleCLCD::wledLevel(uint32_t level)
{
	uint32_t w = level == 0 ? 0 : (level > 0x7ff ? 0xfff : level * 2 + 1);
	int r = 0;

	IOLockLock(fBlLock);
	if (w != 0) {
		for (unsigned n = 0; n < 2 && r == 0; n++) {
			uint8_t lsb = (uint8_t)w, msb = (uint8_t)(w >> 8);
			r = lv_pmic_byte(1, LV_WLED_SINK + 0x57 + 0x10 * n, &lsb);
			if (r == 0) {
				r = lv_pmic_byte(1, LV_WLED_SINK + 0x58 + 0x10 * n, &msb);
			}
		}
		if (r == 0) {
			uint8_t sync = 0x0f;
			r = lv_pmic_byte(1, LV_WLED_SINK + 0x47, &sync);
			IODelay(1000);
			sync = 0;
			r |= lv_pmic_byte(1, LV_WLED_SINK + 0x47, &sync);
		}
	}
	if (r == 0 && (w != 0) != fWledOn) {
		uint8_t en = 0;
		r = lv_pmic_byte(0, LV_WLED_CTRL + 0x46, &en);
		if (r == 0) {
			en = (uint8_t)((en & 0x7f) | (w != 0 ? 0x80 : 0));
			r = lv_pmic_byte(1, LV_WLED_CTRL + 0x46, &en);
		}
		if (r == 0) {
			fWledOn = w != 0;
		}
	}
	IOLockUnlock(fBlLock);
	static uint32_t logs;
	if (logs++ < 12 || r != 0) {
		IOLog("LV WLED: level %#x (panel scale %#x): %d\\n", w, level, r);
	}
}

void
AppleCLCD::setPanelOn(bool on)
{
	if (fDsi == NULL) {
		/* lavender: no DSI commands yet - the panel keeps scanning, only the light goes (mk_wled.py) */
		if (fWled && !on) {
			wledLevel(0);
		}
		return;
	}
'''),
    ('''void
AppleCLCD::setPanelLevel(uint32_t level)
{
''', '''void
AppleCLCD::setPanelLevel(uint32_t level)
{
	if (fWled) {
		wledLevel(level);
		return;
	}
'''),
    ('''	if (n == NULL || fDsi == NULL) {
		return kIOReturnUnsupported;
	}
	uint64_t v = n->unsigned64BitValue();''', '''	if (n == NULL || (fDsi == NULL && !fWled)) {
		return kIOReturnUnsupported;
	}
	uint64_t v = n->unsigned64BitValue();'''),
    ('''			if (off && PE_parse_boot_argn("sweetfb_stayon", &stayon, sizeof(stayon)) && stayon) {''',
     '''			int lvsleep = 0;
			(void)PE_parse_boot_argn("lv_sleep", &lvsleep, sizeof(lvsleep));       /* lavender: 1 = really off */
			if (off && !lvsleep && PE_parse_boot_argn("sweetfb_stayon", &stayon, sizeof(stayon)) && stayon) {'''),
    ('''			if (changed && fFB->fDsi != NULL) {''', '''			if (changed && (fFB->fDsi != NULL || fFB->fWled)) {'''),
])
print('ok')
