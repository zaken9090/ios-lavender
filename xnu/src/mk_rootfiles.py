"""lavender: the kernel writes root files from the payload, with a backup (patch 1035).

tools/mkpayload.py --rootfiles DIR packs launchd.plist (the root's /System/Library/xpc/launchd.plist
with the two com.apple.CommCenter jobs of the original back: the root tweaks had removed them, and
vmd then waits for CommCenter for good, spinning, and the Phone application waits for vmd) into
the archive. lavender_userland_install() writes it over the root's, keeping the old file once as
<path>.lv-orig. Boot-arg lv_rootrestore=1 puts the kept files back. In effect from the next boot
(launchd has read its file by then).

usage: python mk_rootfiles.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/topaz_fw.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	const uint8_t *wrap = lavender_fw("backboardd", &size);''', '''	/* lavender: root files from the payload, the old one kept once as <path>.lv-orig (xnu/src/mk_rootfiles.py) */
	static const struct { const char *name, *path; } rootf[] = {
		{ "launchd.plist", "/System/Library/xpc/launchd.plist" },
	};
	uint32_t restore = 0;
	PE_parse_boot_argn("lv_rootrestore", &restore, sizeof(restore));
	for (unsigned i = 0; i < sizeof(rootf) / sizeof(rootf[0]); i++) {
		char kept[96];
		snprintf(kept, sizeof(kept), "%s.lv-orig", rootf[i].path);
		if (restore) {
			if (lv_exists(kept)) {
				printf("LVINSTALL restore %s -> %d\\n", rootf[i].path, lv_copy(kept, rootf[i].path));
			}
			continue;
		}
		const uint8_t *d = lavender_fw(rootf[i].name, &size);
		if (d == NULL || lv_same(rootf[i].path, d, size)) {
			continue;
		}
		if (!lv_exists(kept)) {
			int err = lv_copy(rootf[i].path, kept);
			printf("LVINSTALL keep %s as %s -> %d\\n", rootf[i].path, kept, err);
			if (err) {
				continue;
			}
		}
		changed += lv_write(rootf[i].path, d, size) == 0;
	}
	const uint8_t *wrap = lavender_fw("backboardd", &size);''')
open(path, 'w', newline='\n').write(s)
print('ok')
