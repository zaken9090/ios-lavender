"""lavender: persist's file names are listed, other MAC file names tried (patch 1082).

Run e86: the ext4 reader works (root plus 19 subfolders seen) but there is no wlan_mac.bin. The
names in the root and in the subfolders whose name has "wlan", "wifi", "wcnss", "mac" or "bt" in it
are logged (names only, no contents), and the address is also looked for in files named
wlan_mac.bin, wlan.mac, wifi_mac, mac.bin, wlan_mac (first found wins).

usage: python mk_wlanmac2.py XNU_TREE   (after mk_wlanmac.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


# list a directory's names (one log line per directory)
sub('''/* persist's wlan_mac.bin -> our_mac; false (address unchanged) when not found */''', r'''static bool
e4_interesting(const char *n)
{
	return strnstr(n, "wlan", 64) || strnstr(n, "wifi", 64) || strnstr(n, "wcnss", 64) || strnstr(n, "mac", 64) ||
	       strnstr(n, "bt", 64) || strnstr(n, "WLAN", 64) || strnstr(n, "MAC", 64);
}

/* the names in directory dino, logged; subdirectories with a telling name are listed too (depth 1) */
static void
e4_list(struct e4 *f, uint32_t dino, const char *label, int depth)
{
	uint32_t blk[15], flags;
	uint64_t size;
	uint16_t mode;
	char line[300];
	int n = 0;
	struct { uint32_t ino; char name[40]; } sub[8];
	unsigned nsub = 0;
	if (!e4_inode(f, dino, blk, &size, &flags, &mode)) {
		return;
	}
	uint8_t *b = (uint8_t *)IOMallocData(f->bs);
	if (b == NULL) {
		return;
	}
	n = snprintf(line, sizeof(line), "persist %s:", label);
	for (uint32_t lb = 0; lb < 16 && (uint64_t)lb * f->bs < size; lb++) {
		uint64_t pb = e4_map(blk, flags, lb);
		if (pb == 0 || !e4_rd(f, pb * f->bs, b, f->bs)) {
			break;
		}
		for (uint32_t o = 0; o + 8 <= f->bs;) {
			uint32_t ino = b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | ((uint32_t)b[o + 3] << 24);
			uint16_t rl = (uint16_t)(b[o + 4] | (b[o + 5] << 8));
			uint8_t nl = b[o + 6], ft = b[o + 7];
			if (rl < 8 || o + rl > f->bs) {
				break;
			}
			if (ino != 0 && nl != 0 && nl < 40 && o + 8 + nl <= f->bs) {
				char nm[40];
				memcpy(nm, b + o + 8, nl);
				nm[nl] = 0;
				if (strcmp(nm, ".") != 0 && strcmp(nm, "..") != 0) {
					if (n > (int)sizeof(line) - 48) {
						LOG("%s", line);
						n = snprintf(line, sizeof(line), "persist %s (more):", label);
					}
					n += snprintf(line + n, sizeof(line) - (size_t)n, " %s%s", nm, ft == 2 ? "/" : "");
					if (ft == 2 && depth == 0 && nsub < 8 && e4_interesting(nm)) {
						sub[nsub].ino = ino;
						strlcpy(sub[nsub].name, nm, sizeof(sub[nsub].name));
						nsub++;
					}
				}
			}
			o += rl;
		}
	}
	IOFreeData(b, f->bs);
	LOG("%s", line);
	for (unsigned i = 0; i < nsub; i++) {
		e4_list(f, sub[i].ino, sub[i].name, depth + 1);
	}
}

/* persist's wlan_mac.bin -> our_mac; false (address unchanged) when not found */''')
sub('''	uint32_t subs[24];
	unsigned nsub = 0;
	uint32_t ino = e4_lookup(&f, 2, "wlan_mac.bin", subs, &nsub, 24);
	for (unsigned i = 0; ino == 0 && i < nsub; i++) {
		ino = e4_lookup(&f, subs[i], "wlan_mac.bin", NULL, NULL, 0);
	}
	if (ino == 0) {
		LOG("wlan mac: no wlan_mac.bin on persist (root and %u subfolders)", nsub);
		return false;
	}
''', '''	e4_list(&f, 2, "/", 0);
	static const char *const names[] = { "wlan_mac.bin", "wlan.mac", "wifi_mac", "mac.bin", "wlan_mac" };
	uint32_t ino = 0;
	unsigned nsub = 0;
	for (unsigned k = 0; ino == 0 && k < sizeof(names) / sizeof(names[0]); k++) {
		uint32_t subs[24];
		nsub = 0;
		ino = e4_lookup(&f, 2, names[k], subs, &nsub, 24);
		for (unsigned i = 0; ino == 0 && i < nsub; i++) {
			ino = e4_lookup(&f, subs[i], names[k], NULL, NULL, 0);
		}
		if (ino != 0) {
			LOG("wlan mac: found %s on persist", names[k]);
		}
	}
	if (ino == 0) {
		LOG("wlan mac: no MAC file on persist (root and %u subfolders)", nsub);
		return false;
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
