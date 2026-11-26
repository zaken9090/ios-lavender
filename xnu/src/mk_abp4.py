"""lavender: the image sent on "pbl" completes with its size (patch 1066), telephony T3.

Run e66: with the chip id and the key hash right the updater goes on and sends its loader
(sbl1.mbn, 238208 bytes) with sendImage on "pbl" - then closes and fails. libPCITransport's
completion (bh::generateCallback -> th::sendImage block) wants: status 0, the size transferred
equal to the image's size, and takes a "code" it only stores. 1063 completed with {0, 0}. Now
the first argument is the size, the second the code (abp_imgcode=N, default 0).

usage: python mk_abp4.py XNU_TREE   (after mk_abp3.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''			what = "sendImage";
			complete = 2;
''', '''			what = "sendImage";
			complete = 2;
			done[0] = in[1];                        /* size transferred: must equal the image's size */
			done[1] = lv_abp_imgcode;
''')
sub('''static uint32_t lv_abp_stage, lv_abp_hold,''', '''static uint32_t lv_abp_imgcode;
static uint32_t lv_abp_stage, lv_abp_hold,''')
sub('''		(void)PE_parse_boot_argn("abp_fused", &lv_abp_fused, sizeof(lv_abp_fused));
''', '''		(void)PE_parse_boot_argn("abp_fused", &lv_abp_fused, sizeof(lv_abp_fused));
		(void)PE_parse_boot_argn("abp_imgcode", &lv_abp_imgcode, sizeof(lv_abp_imgcode));
''')
open(path, 'w', newline='\n').write(s)
print('ok')
