"""lavender: the next Sahara session starts on the same open interface (patch 1068), telephony T3.

Run e68: session 0 went through (READ_DATA image 0x15 served, END_IMAGE_TX, DONE, DONE_RESP). The
updater then kept reading on the open "sahara" interface: its next phase ("Sending Images")
begins with another HELLO from the device - the loader it has just sent, now running - without
closing and reopening. 1067 queued a HELLO only at open. After DONE_RESP the stand-in now starts
the next session at once: a new HELLO, the image ids of that session.

usage: python mk_abp6.py XNU_TREE   (after mk_abp5.py)
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
		break;
''', '''		w[0] = 6; w[1] = 12; w[2] = 0;
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
			IOLog("LV ABP sahara: session %d begins on the open interface: HELLO\\n", lv_sah_session);
			fItf->rx(hello, sizeof(hello));
		}
		break;
''')
open(path, 'w', newline='\n').write(s)
print('ok')
