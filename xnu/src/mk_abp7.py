"""lavender: Sahara DONE_RESP says "complete" after the wanted number of images (patch 1069), T3.

Run e69: every session (HELLO, HELLO_RESP, READ_DATA image 0x15, data, END_IMAGE_TX, DONE,
DONE_RESP) went through, and the updater started the next one each time, 14 in a row, until
"Failed disconnecting for image". Sahara carries one image per session, and DONE_RESP's
image_tx_status tells the host what comes next: 0 = more images pending (the device will say
HELLO again), 1 = transfer complete. The stand-in answered 0 every time.

Now it pulls abp_images images (default 1), one per session, each a different id of those not
known bad, and answers the last DONE with status 1; no HELLO follows that.

usage: python mk_abp7.py XNU_TREE   (after mk_abp6.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		w[0] = 6; w[1] = 12; w[2] = 0;
		fItf->rx(w, 12);
		if (lv_abp_stage != LV_ABP_MISSION && lv_abp_hold == 0) {
			lv_abp_set_stage(LV_ABP_MISSION);
		}
		{
			/* what was sent is "running" now and speaks next: the HELLO of the following session */
			uint32_t hello[12] = { 1, 0x30, 2, 1, 0x400, 0, 0, 0, 0, 0, 0, 0 };
			lv_sah_session++;
			lv_sah_served = 0;
			lv_sah_done = false;
''', '''		lv_sah_images++;
		w[0] = 6; w[1] = 12; w[2] = lv_sah_images >= lv_abp_images ? 1 : 0;    /* 1: transfer complete, 0: more pending */
		fItf->rx(w, 12);
		if (lv_abp_stage != LV_ABP_MISSION && lv_abp_hold == 0) {
			lv_abp_set_stage(LV_ABP_MISSION);
		}
		if (w[2] != 0) {
			IOLog("LV ABP sahara: %u image(s) pulled, transfer complete\\n", lv_sah_images);
		} else {
			/* more to pull: the HELLO of the following session (one image per session) */
			uint32_t hello[12] = { 1, 0x30, 2, 1, 0x400, 0, 0, 0, 0, 0, 0, 0 };
			lv_sah_session++;
			lv_sah_done = false;
''')
sub('''static bool lv_sah_done;
''', '''static bool lv_sah_done;
static uint32_t lv_sah_images, lv_abp_images = 1;      /* images pulled in this attempt; how many to pull (abp_images=) */
''')
sub('''	lv_sah_session = -1;
	lv_sah_pending = -1;
	lv_sah_done = false;
}
''', '''	lv_sah_session = -1;
	lv_sah_pending = -1;
	lv_sah_done = false;
	lv_sah_images = 0;
	lv_sah_served = 0;
}
''')
sub('''	lv_sah_session++;
	lv_sah_served = 0;
	lv_sah_pending = -1;
	lv_sah_done = false;
	lv_sah_itf = itf;
''', '''	lv_sah_session++;
	lv_sah_pending = -1;
	lv_sah_done = false;
	lv_sah_itf = itf;
''')
sub('''		(void)PE_parse_boot_argn("abp_imgcode", &lv_abp_imgcode, sizeof(lv_abp_imgcode));
''', '''		(void)PE_parse_boot_argn("abp_imgcode", &lv_abp_imgcode, sizeof(lv_abp_imgcode));
		(void)PE_parse_boot_argn("abp_images", &lv_abp_images, sizeof(lv_abp_images));
''')
open(path, 'w', newline='\n').write(s)
print('ok')
