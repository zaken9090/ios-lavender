"""lavender: boot-arg lv_swaplog=N - the first N swaps say which IOSurfaces they show (patch 1158).

With eagl's glpreservelog (which surfaces glpreserve copies between) this tells whether a preserve
copy's source was ever on the panel. Line: "LV SWAP n: layers M ids A B C D".

usage: python mk_swaplog.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()
old = '''AppleCLCD::swap(const uint8_t *rec)
{
	sweet_fps_count();'''
assert s.count(old) == 1
s = s.replace(old, '''AppleCLCD::swap(const uint8_t *rec)
{
	sweet_fps_count();
	/* lavender: lv_swaplog=N (xnu/src/mk_swaplog.py) */
	static int swaplog = -1;
	static uint32_t swapn;
	if (swaplog < 0) {
		swaplog = 0;
		PE_parse_boot_argn("lv_swaplog", &swaplog, sizeof(swaplog));
	}
	if (swaplog > 0) {
		swaplog--;
		IOLog("LV SWAP %u: layers %#x ids %u %u %u %u\\n", ++swapn, get32(rec, 0x104), get32(rec, 0x54), get32(rec, 0x58),
		    get32(rec, 0x5c), get32(rec, 0x60));
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
