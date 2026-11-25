"""lavender: the kernel installs the GPU user space from the payload (boot-arg gpu=1).

tools/mkpayload.py --fw FW --userland OUT packs the userland CI's files into the firmware archive
(ramdisk slot, lv_fwpa). When the root filesystem is mounted, TopazAdreno's thread calls
lavender_userland_install() (bsd/dev/topaz_fw.c) before it starts the GPU:

  libOSMesa.8.dylib, libtopaz-gl.dylib, libtopaz-inject.dylib -> /usr/lib/<name>
  backboardd (bbd_wrap: DYLD_INSERT_LIBRARIES=/usr/lib/libtopaz-inject.dylib, then execs the real
  one) -> /usr/libexec/backboardd, after the real one is kept as /usr/sbin/backboardd (only when
  that does not exist yet and /usr/libexec/backboardd is not the wrapper already).

Existing directories only (no mkdir). A file is written only when it differs; the old one is
unlinked first (a new file: a running program keeps its pages). Boot-arg lv_uninstall=1 puts the
real backboardd back. launchd may start backboardd before this runs: changes apply from the next
boot (the log says so).

usage: python mk_install.py XNU_TREE
"""
import sys

tree = sys.argv[1]
s = ''
path = ''


def load(rel):
    global s, path
    path = f'{tree}/{rel}'
    s = open(path, newline='').read()


def save():
    open(path, 'w', newline='\n').write(s)


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


# ---- TopazRpm.cpp: lavender_fw maps the whole archive (the userland is ~15 MB)
load('iokit/Kernel/arm/TopazRpm.cpp')
sub('''		ar = (const volatile uint8_t *)ml_io_map_wcomb(fwpa, 0x40000);
		if (ar == NULL || memcmp((const void *)ar, "LVFW0001", 8) != 0) {
			ar = NULL;
			return NULL;
		}''', '''		const volatile uint8_t *head = (const volatile uint8_t *)ml_io_map_wcomb(fwpa, 0x4000);
		if (head == NULL || memcmp((const void *)head, "LVFW0001", 8) != 0) {
			return NULL;
		}
		uint32_t total = *(const volatile uint32_t *)(head + 12) + *(const volatile uint32_t *)(head + 16);
		ar = (const volatile uint8_t *)ml_io_map_wcomb(fwpa, (total + 0x3fff) & ~0x3fffu);
		if (ar == NULL) {
			return NULL;
		}''')
save()

# ---- topaz_fw.c: the installer
load('bsd/dev/topaz_fw.c')
sub('''#include <kern/kalloc.h>
''', '''#include <kern/kalloc.h>
#include <sys/mount.h>
#include <sys/fcntl.h>
#include <sys/vnode_if.h>
#include <pexpert/pexpert.h>
''')
sub('''void
topaz_fw_free(void *data, size_t size)
{
	if (data != NULL) {
		kfree_data(data, size);
	}
}''', '''void
topaz_fw_free(void *data, size_t size)
{
	if (data != NULL) {
		kfree_data(data, size);
	}
}

/* ---- lavender: the GPU user space from the payload (xnu/src/mk_install.py) ---- */
extern const uint8_t *lavender_fw(const char *name, uint32_t *size);   /* TopazRpm.cpp */
extern int unlink1(vfs_context_t, vnode_t, user_addr_t, enum uio_seg, int);
void lavender_userland_install(void);

static int
lv_exists(const char *path)
{
	vnode_t vp = NULLVP;
	if (vnode_lookup(path, 0, &vp, vfs_context_kernel()) != 0) {
		return 0;
	}
	vnode_put(vp);
	return 1;
}

/* 1: same content already, 0: other content or none */
static int
lv_same(const char *path, const uint8_t *data, size_t size)
{
	void *old = NULL;
	size_t osz = 0;
	int same = 0;
	if (topaz_fw_read(path, &old, &osz) == 0) {
		same = osz == size && memcmp(old, data, size) == 0;
		topaz_fw_free(old, osz);
	}
	return same;
}

/* 0 written, -1 already so, else errno */
static int
lv_write(const char *path, const uint8_t *data, size_t size)
{
	vfs_context_t ctx = vfs_context_kernel();
	vnode_t vp = NULLVP;
	int resid = 0, err;

	if (lv_same(path, data, size)) {
		return -1;
	}
	if (lv_exists(path)) {
		err = unlink1(ctx, NULLVP, CAST_USER_ADDR_T(path), UIO_SYSSPACE, 0);
		if (err) {
			printf("LVINSTALL unlink %s: %d\\n", path, err);
			return err;
		}
	}
	err = vnode_open(path, O_CREAT | O_TRUNC | FWRITE, 0755, 0, &vp, ctx);
	if (err) {
		printf("LVINSTALL create %s: %d\\n", path, err);
		return err;
	}
	err = vn_rdwr(UIO_WRITE, vp, (caddr_t)(uintptr_t)data, (int)size, 0, UIO_SYSSPACE, IO_NOAUTH | IO_UNIT,
	    vfs_context_ucred(ctx), &resid, vfs_context_proc(ctx));
	if (!err && resid != 0) {
		err = EIO;
	}
	if (!err) {
		err = VNOP_FSYNC(vp, MNT_WAIT, ctx);
	}
	vnode_close(vp, FWRITE, ctx);
	printf("LVINSTALL %s: %zu bytes -> %d\\n", path, size, err);
	return err;
}

static int
lv_copy(const char *from, const char *to)
{
	void *data = NULL;
	size_t size = 0;
	int err = topaz_fw_read(from, &data, &size);
	if (err == 0) {
		err = lv_write(to, (const uint8_t *)data, size);
		topaz_fw_free(data, size);
	}
	return err < 0 ? 0 : err;
}

void
lavender_userland_install(void)
{
	static const char *const libs[] = { "libOSMesa.8.dylib", "libtopaz-gl.dylib", "libtopaz-inject.dylib" };
	const char *real = "/usr/sbin/backboardd", *bbd = "/usr/libexec/backboardd";
	uint32_t un = 0, size = 0;
	int changed = 0;

	if (PE_parse_boot_argn("lv_uninstall", &un, sizeof(un)) && un) {
		if (lv_exists(real)) {
			printf("LVINSTALL uninstall: real backboardd back -> %d\\n", lv_copy(real, bbd));
		}
		return;
	}
	for (unsigned i = 0; i < sizeof(libs) / sizeof(libs[0]); i++) {
		const uint8_t *d = lavender_fw(libs[i], &size);
		if (d != NULL) {
			char path[64];
			snprintf(path, sizeof(path), "/usr/lib/%s", libs[i]);
			changed += lv_write(path, d, size) == 0;
		}
	}
	const uint8_t *wrap = lavender_fw("backboardd", &size);
	if (wrap != NULL) {
		if (!lv_exists(real)) {
			if (lv_same(bbd, wrap, size)) {
				printf("LVINSTALL: %s is the wrapper and %s is missing: not touched\\n", bbd, real);
				return;
			}
			int err = lv_copy(bbd, real);
			printf("LVINSTALL keep the real backboardd as %s -> %d\\n", real, err);
			if (err) {
				return;
			}
		}
		changed += lv_write(bbd, wrap, size) == 0;
	}
	printf("LVINSTALL done: %d file(s) changed%s\\n", changed, changed ? " (in effect from the next boot)" : "");
}''')
save()

# ---- TopazAdreno.cpp: install before the GPU starts
load('iokit/Kernel/arm/TopazAdreno.cpp')
sub('''extern "C" const uint8_t *lavender_fw(const char *name, uint32_t *size);''',
    '''extern "C" const uint8_t *lavender_fw(const char *name, uint32_t *size);
extern "C" void lavender_userland_install(void);''')
sub('''	IOLockLock(hw_lock);
	bool ok = hw_start();''', '''	lavender_userland_install();     /* the GPU user space from the payload (bsd/dev/topaz_fw.c) */
	IOLockLock(hw_lock);
	bool ok = hw_start();''')
save()
print('ok')
