"""lavender: lv_mgreset=1 - let MobileGestalt build its cache again (patch 1105).

Run e114 (xnu 1104): /chosen/mac-address-bluetooth0 and -wifi0 are set, bluetoothd's stack is
up, Settings still has no Bluetooth row. MobileGestalt keeps its answers (capabilities among
them) in /private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/
Library/Caches/com.apple.MobileGestalt.plist, valid while the build does not change; it was
written when there was no Bluetooth address, so "bluetooth" stays false. Without the file
MobileGestalt logs "Cache file did not exist. Rebuilding." and asks again.

Now with boot-arg lv_mgreset=1 the root-file installer (before user space) renames that file to
<name>.lv-old (nothing is deleted; the next rename replaces the older copy).

usage: python mk_bt21.py XNU_TREE   (after mk_bt20.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


patch(f'{tree}/bsd/vfs/vfs_syscalls.c', '''/* lavender (xnu/src/mk_bbfw.py): mkdir of a kernel path, for the installer in bsd/dev/topaz_fw.c */
int sweet_mkdir(const char *path, int mode);
''', '''/* lavender (xnu/src/mk_bt21.py): rename of kernel paths, for the installer in bsd/dev/topaz_fw.c */
int sweet_rename(const char *from, const char *to);

int
sweet_rename(const char *from, const char *to)
{
	return renameat_internal(vfs_context_kernel(), AT_FDCWD, CAST_USER_ADDR_T(from), AT_FDCWD, CAST_USER_ADDR_T(to),
	           UIO_SYSSPACE, 0);
}

/* lavender (xnu/src/mk_bbfw.py): mkdir of a kernel path, for the installer in bsd/dev/topaz_fw.c */
int sweet_mkdir(const char *path, int mode);
''')
patch(f'{tree}/bsd/dev/topaz_fw.c', '''	uint32_t restore = 0;
	PE_parse_boot_argn("lv_rootrestore", &restore, sizeof(restore));''', '''	uint32_t restore = 0;
	PE_parse_boot_argn("lv_rootrestore", &restore, sizeof(restore));
	{
		/* lavender (xnu/src/mk_bt21.py): MobileGestalt's cache, rebuilt by iOS when missing */
		extern int sweet_rename(const char *from, const char *to);
		static const char mg[] = "/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/"
		    "Library/Caches/com.apple.MobileGestalt.plist";
		uint32_t mgreset = 0;
		if (PE_parse_boot_argn("lv_mgreset", &mgreset, sizeof(mgreset)) && mgreset != 0 && lv_exists(mg)) {
			printf("LVINSTALL MobileGestalt cache -> .lv-old: %d\\n", sweet_rename(mg, mg ".lv-old"));
		}
	}''')
print('ok')
