"""lavender: audio A4b - the amplifier is a MAX98937: its register map and sequences (patch 1133).

Runs t7-ta3: the readbacks did not fit mainline MAX98927 (0x22, 0x24, 0x3f, 0x42 kept only some
bits, nothing from 0x82 up, REV 0x1ff = 0, GLOBAL_EN 0x00FF read 0). Xiaomi's lavender driver
(MiCode/Xiaomi_Kernel_OpenSource lavender-q-oss, sound/soc/codecs/max98937/max98937.c, see
docs/MAX98927.md) handles both chips under "maxim,max98927L": 0x01FF bit 6 = MAX98927, else
REV_ID 0x0600 bit 6 = MAX98937 - with another map: global enable 0x0500, speaker enable 0x0039.

Now (all can still be replaced by audio_amp_init / audio_amp_on):
- reset low 1 ms, high, 10 ms; REV 0x01FF and 0x0600 logged;
- the init table of Xiaomi's driver for the 98937 (probe + register defaults), then its
  hw_params values for 16-bit I2S, 48 kHz, 32 BCLK per frame (0x23=0x40, 0x26=0x08, 0x27=0x88,
  0x25=0x02);
- on: 0x0039=1 then 0x0500=1 (read back, with 0x0002 bit 7 power-up done, 0x0003 power-up fail
  bit 0 / boost undervoltage bit 3); off: 0x0500=0 then 0x0039=0;
- the default register read while playing: 0x500,0x39,0x2,0x3,0x1,0x600.

usage: python mk_audio15.py XNU_TREE   (after mk_audio14.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


la = f'{tree}/iokit/Kernel/arm/LavenderAudio.cpp'
s = open(la, newline='').read()
a = s.index('	static const uint16_t init[][2] = {')
b = s.index('	};', a) + len('	};')
s = s[:a] + '''	/* MAX98937 (Xiaomi lavender-q-oss max98937.c, docs/MAX98927.md): probe/defaults, then hw_params */
	static const uint16_t init[][2] = {
		{ 0x0040, 0x01 }, { 0x001E, 0x01 }, { 0x0018, 0x03 }, { 0x001A, 0x03 }, { 0x001C, 0xFC }, { 0x0028, 0x80 },
		{ 0x0029, 0x01 }, { 0x0011, 0x03 }, { 0x0053, 0x00 }, { 0x0055, 0x00 }, { 0x005E, 0x16 }, { 0x005F, 0x00 },
		{ 0x0060, 0x0C }, { 0x0061, 0x0C }, { 0x0062, 0x12 }, { 0x0063, 0x00 }, { 0x0064, 0x0C }, { 0x0065, 0x0C },
		{ 0x0066, 0x0E }, { 0x0067, 0x03 }, { 0x0068, 0x18 }, { 0x0069, 0x18 }, { 0x006A, 0x0A }, { 0x006B, 0x00 },
		{ 0x006C, 0x80 }, { 0x006D, 0x00 }, { 0x005A, 0x00 }, { 0x005B, 0x00 }, { 0x005C, 0x1F }, { 0x005D, 0x00 },
		{ 0x0042, 0x07 }, { 0x0014, 0x75 }, { 0x0015, 0x8C }, { 0x0017, 0x55 }, { 0x003E, 0xF7 }, { 0x0023, 0x40 },
		{ 0x003A, 0x00 }, { 0x001B, 0x00 }, { 0x0019, 0x00 }, { 0x001F, 0x03 }, { 0x001D, 0xFF }, { 0x003D, 0x03 },
		{ 0x0035, 0x00 }, { 0x0036, 0x38 }, { 0x0037, 0x0F }, { 0x003B, 0x55 }, { 0x003C, 0x85 }, { 0x003F, 0x1C },
		{ 0x0041, 0x40 }, { 0x0043, 0x00 }, { 0x0044, 0xFF }, { 0x0016, 0x08 }, { 0x0073, 0x0F }, { 0x0077, 0x01 },
		{ 0x0052, 0x02 }, { 0x0020, 0x00 }, { 0x0021, 0x00 }, { 0x0022, 0x00 }, { 0x004E, 0x10 }, { 0x0079, 0x45 },
		{ 0x007A, 0x2B }, { 0x007B, 0x04 },
		{ 0x0023, 0x40 }, { 0x0026, 0x08 }, { 0x0027, 0x88 }, { 0x0025, 0x02 },     /* 16-bit I2S, 48 kHz, 32 BCLK */
	};''' + s[b:]
s = s.replace('''	pin_rst[1] = 0;                                 /* reset (active low) */
	pin_cfg(pin_rst, CFG_OE);
	IOSleep(2);
	pin_rst[1] = 2;                                 /* release */
	IOSleep(6);
	int rev = lv_amp_read(0x01FF);
	LOG("max98927: revision %#x (0x40 expected)", rev);''', '''	pin_rst[1] = 0;                                 /* reset (active low) */
	pin_cfg(pin_rst, CFG_OE);
	IOSleep(1);
	pin_rst[1] = 2;                                 /* release */
	IOSleep(10);
	int rev = lv_amp_read(0x01FF), rev37 = lv_amp_read(0x0600);
	LOG("max98937: 0x01FF %#x (bit 6: a 98927), 0x0600 %#x (bit 6: a 98937)", rev, rev37);''')
s = s.replace('''		if (i == 0) {
			IOSleep(2);                     /* after the soft reset */
		}
''', '')
s = s.replace('''	LOG("max98927: init table written, %d NAKs; 0x0020=%#x 0x0023=%#x 0x0036=%#x", bad, lv_amp_read(0x0020), lv_amp_read(0x0023),
	    lv_amp_read(0x0036));''', '''	LOG("max98937: init table written, %d NAKs; 0x0023=%#x 0x0025=%#x 0x0027=%#x 0x003C=%#x", bad, lv_amp_read(0x0023),
	    lv_amp_read(0x0025), lv_amp_read(0x0027), lv_amp_read(0x003C));''')
open(la, 'w', newline='\n').write(s)

ta = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
patch(ta, '''				LOG("A4b: amp on: AMP_EN %d GLOBAL_EN %d", lv_amp_write(0x003A, 0x01), lv_amp_write(0x00FF, 0x01));
			}
			LOG("A4b: read back AMP_EN %#x GLOBAL_EN %#x", lv_amp_read(0x003A), lv_amp_read(0x00FF));''', '''				LOG("A4b: amp on: SPK_EN 0x39 %d GLOBAL_EN 0x500 %d", lv_amp_write(0x0039, 0x01), lv_amp_write(0x0500, 0x01));
			}
			IOSleep(20);
			int st2 = lv_amp_read(0x0002), st3 = lv_amp_read(0x0003);
			LOG("A4b: read back SPK_EN %#x GLOBAL_EN %#x; 0x0002 %#x (bit 7 power-up done) 0x0003 %#x (bit 0 power-up fail, bit 3 boost UVLO)",
			    lv_amp_read(0x0039), lv_amp_read(0x0500), st2, st3);''')
patch(ta, '''			LOG("A4b: amp off: GLOBAL_EN %d AMP_EN %d", lv_amp_write(0x00FF, 0x00), lv_amp_write(0x003A, 0x00));''',
      '''			LOG("A4b: amp off: GLOBAL_EN %d SPK_EN %d", lv_amp_write(0x0500, 0x00), lv_amp_write(0x0039, 0x00));''')
patch(ta, '''	char buf[256] = "0x3a,0xff,0x11,0x1,0x2,0x3,0x4,0x5,0x6";''', '''	char buf[256] = "0x500,0x39,0x2,0x3,0x1,0x600";''')
print('ok')
