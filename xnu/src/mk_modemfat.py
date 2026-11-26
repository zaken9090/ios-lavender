"""lavender: the modem's firmware files are found by reading the partition's FAT16 volume (patch 1043).

TopazModem.cpp carried three tables made on a PC from topaz's NON-HLOS.bin: where each firmware
file lies in the modem partition (offsets, sizes, CRCs of one HyperOS build). lavender's files are
others (MIUI: image/mba.mbn, modem.mdt + b00..b09, wlanmdsp.mbn, bdwlan.*, ...). Instead of new
tables the kernel now reads the volume itself at modem start: boot sector, the FAT, the root
directory and its subdirectories (8.3 names, lower case, "dir/name"), every file's cluster chain
as extents. Any firmware version on the phone works and no list of a proprietary image is in the
repo. modem_part= defaults to "modem" (lavender has no A/B slots).

Step 1 of docs/MODEM-PLAN.md. With modem=1 the log says "firmware: N files ..." and the sizes of
image/mba.mbn and image/modem.mdt; the rest of the modem code still has topaz's addresses, so
modem=1 stops right after that unless modem_go=1 (until step 2).

usage: python mk_modemfat.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


def cut(start, new):
    """replace from the line that starts a table to its closing "};" line"""
    global s
    assert s.count(start) == 1, (start[:60], s.count(start))
    a = s.index(start)
    b = s.index('\n};\n', a) + 4
    s = s[:a] + new + s[b:]


sub('''static char fw_part[32] = "modem_a";
''', '''static char fw_part[32] = "modem";      /* lavender: no A/B slots */
''')
cut('''static const struct { const char *name; uint32_t off, size, crc; } fw_files[] = {''', '''/*
 * lavender: the files of the volume, found at modem start by fw_scan() (xnu/src/mk_modemfat.py):
 * fw_all[] - path, size and where its extents are in fw_ext[] (byte offset in the partition, length).
 */
struct fw_ext_t { uint32_t off, len; };
struct fw_all_t { char path[96]; uint32_t size, ext, next; };
#define FW_MAX_FILES    1536
#define FW_MAX_EXT      4096
static struct fw_ext_t *fw_ext;
static struct fw_all_t *fw_all;
static unsigned fw_all_n, fw_ext_n;
static int fw_all_find(const char *path);
static bool fw_all_read(int i, uint64_t off, void *dst, uint64_t n);
''')
sub('''static int
fw_find(const char *name)
{
	for (unsigned i = 0; i < sizeof(fw_files) / sizeof(fw_files[0]); i++) {
		if (strcmp(fw_files[i].name, name) == 0) {
			return (int)i;
		}
	}
	return -1;
}
''', '''/* the modem's own files are in image/ */
static int
fw_find(const char *name)
{
	char full[96];
	snprintf(full, sizeof(full), "image/%s", name);
	return fw_all_find(full);
}
''')
sub('''	return i < 0 ? -1 : (int64_t)fw_files[i].size;
}

/* Read the whole file''', '''	return i < 0 ? -1 : (int64_t)fw_all[i].size;
}

/* Read the whole file''')
head = '''	if (i < 0 || fw_files[i].size > max) {'''
tail = '''	return fw_files[i].size;
}
'''
assert s.count(head) == 1 and s.count(tail) == 1
a = s.index(head)
b = s.index(tail, a) + len(tail)
s = s[:a] + '''	if (i < 0 || fw_all[i].size > max) {
		LOG("%s: not in %s or too big (%lld)", name, fw_part, fw_size(name));
		return -1;
	}
	if (!fw_all_read(i, 0, dst, fw_all[i].size)) {
		LOG("%s: read from %s failed", name, fw_part);
		return -1;
	}
	(void)err;
	return fw_all[i].size;
}
''' + s[b:]
sub('''	int i = fw_find(name), err;
''', '''	int i = fw_find(name), err = 0;
''')
cut('''static const struct { uint32_t off, len; } fw_ext[] = {''', '')
cut('''static const struct { const char *path; uint32_t size; uint16_t ext, next; } fw_all[] = {''', '''/*
 * lavender: read the FAT16 volume of the modem partition into fw_all[] / fw_ext[].
 */
static uint16_t *fat_tab;
static uint32_t fat_count, fat_data, fat_clus;   /* FAT entries; byte offset of cluster 2; bytes a cluster */

static void
fat_file(const char *path, uint32_t first, uint32_t size)
{
	if (fw_all_n >= FW_MAX_FILES) {
		return;
	}
	struct fw_all_t *f = &fw_all[fw_all_n];
	strlcpy(f->path, path, sizeof(f->path));
	f->size = size;
	f->ext = fw_ext_n;
	f->next = 0;
	uint32_t left = size, c = first;
	while (left != 0 && c >= 2 && c < fat_count && c < 0xfff8 && fw_ext_n < FW_MAX_EXT) {
		uint32_t run = 1;
		while (c + run < fat_count && fat_tab[c + run - 1] == c + run && (uint64_t)run * fat_clus < left) {
			run++;
		}
		uint32_t len = (uint64_t)run * fat_clus < left ? run * fat_clus : left;
		fw_ext[fw_ext_n].off = fat_data + (c - 2) * fat_clus;
		fw_ext[fw_ext_n].len = len;
		fw_ext_n++;
		f->next++;
		left -= len;
		c = fat_tab[c + run - 1];
	}
	if (left == 0) {
		fw_all_n++;
	} else {
		fw_ext_n = f->ext;      /* a broken chain: the file is left out */
	}
}

static void fat_dir(const char *prefix, uint32_t first, uint32_t root_off, uint32_t root_len, int depth);

/* the 32-byte entries of one piece of a directory; false at the end-of-directory mark */
static bool
fat_entries(const char *prefix, const uint8_t *e, uint32_t len, int depth)
{
	for (uint32_t at = 0; at + 32 <= len; at += 32, e += 32) {
		char name[14], full[96];
		unsigned n = 0;
		if (e[0] == 0) {
			return false;
		}
		if (e[0] == 0xe5 || e[0] == 0x2e || (e[11] & 0x0f) == 0x0f || (e[11] & 0x08) != 0) {
			continue;               /* deleted, "." and "..", long-name pieces, the label */
		}
		for (unsigned i = 0; i < 8 && e[i] != 0x20; i++) {
			name[n++] = (char)(e[i] >= 0x41 && e[i] <= 0x5a ? e[i] + 32 : e[i]);
		}
		if (e[8] != 0x20) {
			name[n++] = 0x2e;
			for (unsigned i = 8; i < 11 && e[i] != 0x20; i++) {
				name[n++] = (char)(e[i] >= 0x41 && e[i] <= 0x5a ? e[i] + 32 : e[i]);
			}
		}
		name[n] = 0;
		snprintf(full, sizeof(full), "%s%s", prefix, name);
		uint32_t first = e[26] | ((uint32_t)e[27] << 8);
		uint32_t size = e[28] | ((uint32_t)e[29] << 8) | ((uint32_t)e[30] << 16) | ((uint32_t)e[31] << 24);
		if (e[11] & 0x10) {
			if (depth < 4) {
				strlcat(full, "/", sizeof(full));
				fat_dir(full, first, 0, 0, depth + 1);
			}
		} else {
			fat_file(full, first, size);
		}
	}
	return true;
}

static void
fat_dir(const char *prefix, uint32_t first, uint32_t root_off, uint32_t root_len, int depth)
{
	uint32_t len = root_len != 0 ? root_len : fat_clus;
	uint8_t *buf = (uint8_t *)IOMallocData(len);
	if (buf == NULL) {
		return;
	}
	if (root_len != 0) {
		if (sweet_ufs_read_part(fw_part, root_off, buf, len) == 0) {
			(void)fat_entries(prefix, buf, len, depth);
		}
	} else {
		uint32_t c = first, guard = 0;
		while (c >= 2 && c < fat_count && c < 0xfff8 && guard++ < 4096) {
			if (sweet_ufs_read_part(fw_part, fat_data + (uint64_t)(c - 2) * fat_clus, buf, len) != 0 ||
			    !fat_entries(prefix, buf, len, depth)) {
				break;
			}
			c = fat_tab[c];
		}
	}
	IOFreeData(buf, len);
}

static bool
fw_scan(void)
{
	uint8_t bs[512];
	if (sweet_ufs_read_part(fw_part, 0, bs, sizeof(bs)) != 0 || bs[510] != 0x55 || bs[511] != 0xaa) {
		LOG("firmware: %s has no boot sector", fw_part);
		return false;
	}
	uint32_t bps = bs[11] | (bs[12] << 8), spc = bs[13], reserved = bs[14] | (bs[15] << 8), nfat = bs[16];
	uint32_t roots = bs[17] | (bs[18] << 8), fatsz = bs[22] | (bs[23] << 8);
	if (bps != 512 || spc == 0 || roots == 0 || fatsz == 0 || nfat == 0) {
		LOG("firmware: %s is not FAT16 (sector %u, cluster %u sectors, root %u, FAT %u sectors)", fw_part, bps, spc, roots, fatsz);
		return false;
	}
	uint32_t fat_off = reserved * bps, root_off = fat_off + nfat * fatsz * bps, root_len = (roots * 32 + bps - 1) / bps * bps;
	fat_count = fatsz * bps / 2;
	fat_data = root_off + root_len;
	fat_clus = spc * bps;
	fat_tab = (uint16_t *)IOMallocData(fatsz * bps);
	fw_all = (struct fw_all_t *)IOMallocData(sizeof(struct fw_all_t) * FW_MAX_FILES);
	fw_ext = (struct fw_ext_t *)IOMallocData(sizeof(struct fw_ext_t) * FW_MAX_EXT);
	if (fat_tab == NULL || fw_all == NULL || fw_ext == NULL ||
	    sweet_ufs_read_part(fw_part, fat_off, fat_tab, (uint64_t)fatsz * bps) != 0) {
		LOG("firmware: cannot read the FAT of %s", fw_part);
		return false;
	}
	fw_all_n = fw_ext_n = 0;
	fat_dir("", 0, root_off, root_len, 0);
	int mba = fw_all_find("image/mba.mbn"), mdt = fw_all_find("image/modem.mdt"), wl = fw_all_find("image/wlanmdsp.mbn");
	LOG("firmware: %u files in %u extents on %s (FAT16, %u-byte clusters); image/mba.mbn %d, image/modem.mdt %d, image/wlanmdsp.mbn %d bytes",
	    fw_all_n, fw_ext_n, fw_part, fat_clus, mba < 0 ? -1 : (int)fw_all[mba].size, mdt < 0 ? -1 : (int)fw_all[mdt].size,
	    wl < 0 ? -1 : (int)fw_all[wl].size);
	return fw_all_n != 0;
}
''')
sub('''	for (unsigned i = 0; i < sizeof(fw_all) / sizeof(fw_all[0]); i++) {
		if (strcmp(fw_all[i].path, path) == 0) {''', '''	for (unsigned i = 0; i < fw_all_n; i++) {
		if (strcmp(fw_all[i].path, path) == 0) {''')
sub('''		err = sweet_ufs_read_part(fw_part, fw_files[0].off, probe, sizeof(probe));
		if (err == EAGAIN) {
			IOSleep(500);
		}
	}
''', '''		err = sweet_ufs_read_part(fw_part, 0, probe, sizeof(probe));
		if (err == EAGAIN) {
			IOSleep(500);
		}
	}
	if (err == 0 && !fw_scan()) {
		err = ENOENT;
	}
	uint32_t go = 0;
	(void)PE_parse_boot_argn("modem_go", &go, sizeof(go));
	if (err == 0 && !go) {
		/* lavender: the addresses below are still topaz's (docs/MODEM-PLAN.md step 2) */
		LOG("firmware found; the modem is not started (modem_go=1 would, with another phone's addresses)");
		return false;
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
