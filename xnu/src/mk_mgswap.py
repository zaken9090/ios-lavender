"""lavender: lv_mgreset=2 - put the old MobileGestalt cache back (patch 1118).

The user sees worse graphics since about the Bluetooth work (unlock flicker blue/black, a frozen
UI), and on 2026-11-26 the flicker came on the old kernel 1084 too - so a state on disk, not a
kernel patch, is the suspect. The one such change: the MobileGestalt cache, renamed by
lv_mgreset=1 (1105, run e115) and rebuilt by iOS with Bluetooth/Wi-Fi addresses present; it also
holds the graphics-related answers.

Now lv_mgreset=2 swaps: the current cache becomes <name>.lv-new and <name>.lv-old (the cache from
before e115) is put back. Nothing is deleted. lv_mgreset=3 swaps back (.lv-new -> cache, cache ->
.lv-old).

usage: python mk_mgswap.py XNU_TREE   (after mk_audio2.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/topaz_fw.c'
s = open(path, newline='').read()
T = chr(9)
old_head = 'if (PE_parse_boot_argn("lv_mgreset", &mgreset, sizeof(mgreset)) && mgreset != 0 && lv_exists(mg)) {'
i = s.index(old_head)
i = s.rindex(chr(10), 0, i) + 1
j = s.index(chr(10), s.index('sweet_rename(mg, LV_MG ".lv-old"));', i))          # end of printf line
j = s.index(chr(10), j + 1) + 1                                                    # the closing brace line
body = [
    'PE_parse_boot_argn("lv_mgreset", &mgreset, sizeof(mgreset));',
    'if (mgreset == 1 && lv_exists(mg)) {',
    T + 'printf("LVINSTALL MobileGestalt cache -> .lv-old: %d' + chr(92) + 'n", sweet_rename(mg, LV_MG ".lv-old"));',
    '} else if (mgreset == 2 && lv_exists(LV_MG ".lv-old")) {',
    T + '/* lavender (xnu/src/mk_mgswap.py): the cache from before e115 back */',
    T + 'int a = lv_exists(mg) ? sweet_rename(mg, LV_MG ".lv-new") : 0;',
    T + 'printf("LVINSTALL MobileGestalt cache -> .lv-new %d, .lv-old -> cache %d' + chr(92) + 'n", a, sweet_rename(LV_MG ".lv-old", mg));',
    '} else if (mgreset == 3 && lv_exists(LV_MG ".lv-new")) {',
    T + 'int a = lv_exists(mg) ? sweet_rename(mg, LV_MG ".lv-old") : 0;',
    T + 'printf("LVINSTALL MobileGestalt cache -> .lv-old %d, .lv-new -> cache %d' + chr(92) + 'n", a, sweet_rename(LV_MG ".lv-new", mg));',
    '}',
]
s = s[:i] + ''.join(T + T + l + chr(10) for l in body) + s[j:]
open(path, 'w', newline='\n').write(s)
print('ok')
