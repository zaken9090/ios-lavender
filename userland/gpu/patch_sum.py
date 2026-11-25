"""lavender: surface_changed() looks at a sample of a surface, not all of it (eagl.c, boot-arg glsumfull=1: all).

backboardd runs one core flat out while Settings scrolls (SMC line, 2026-11-25) and glBindTexture -
where a copied surface's memory is added up to notice writes nobody announced - was one of the four
biggest GL costs (~2.5 ms of a 13 ms pass). Now a look adds up one 8-byte word in every 512 bytes
(the same words every time) and, in full, one sixteenth of the surface, a different sixteenth each
look: a write anywhere is seen at once if it touches a sampled word and within sixteen looks
otherwise. Surfaces under 64 KB are still added up whole. The idea comes from the user's first
lavender project (its eagl "a word in 512 bytes and one 16th in full a look").

usage: python patch_sum.py EAGL_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	uint64_t sum;                   /* ... and what it added up to */
''', '''	uint64_t sum;                   /* ... and what it added up to */
	uint64_t part_sum[16];          /* lavender: ... and each sixteenth of it, when last added up in full (patch_sum.py) */
	unsigned part, parts_known;     /* ... the sixteenth to add up next, and which have been (a bit each) */
''')
sub('''static int preserve_frames = 1;''', '''static int sum_sampled = 1;             /* lavender: boot-arg glsumfull=1 - surface_changed() adds up all of a surface */
static int preserve_frames = 1;''')
sub('''		preserve_frames = strstr(arguments, "glpreserve=0") == NULL;
''', '''		preserve_frames = strstr(arguments, "glpreserve=0") == NULL;
		sum_sampled = strstr(arguments, "glsumfull=1") == NULL;
''')
sub('''	image->looked = e->frames + 1;
	for (size_t at = 0; at + 8 <= size; at += 8) {
		memcpy(&word, base + at, 8);
		sum = (sum ^ word) * 0x9e3779b97f4a7c15ull;
		sum ^= sum >> 29;
	}
	if (sum == image->sum) {
		image->quiet++;
		return false;
	}
	image->sum = sum;
	image->quiet = 0;
	return true;''', '''	image->looked = e->frames + 1;
	if (sum_sampled && size >= (64u << 10)) {
		/* lavender: a word in every 512 bytes, and one sixteenth in full, a different one each look */
		size_t slice = (size / 16) & ~(size_t)7, from = slice * image->part, to = image->part == 15 ? size : from + slice;
		uint64_t part = slice;
		bool changed = false;

		for (size_t at = 0; at + 8 <= size; at += 512) {
			memcpy(&word, base + at, 8);
			sum = (sum ^ word) * 0x9e3779b97f4a7c15ull;
			sum ^= sum >> 29;
		}
		for (size_t at = from; at + 8 <= to; at += 8) {
			memcpy(&word, base + at, 8);
			part = (part ^ word) * 0x9e3779b97f4a7c15ull;
			part ^= part >> 29;
		}
		if (sum != image->sum) {
			changed = true;
			image->parts_known = 0;         /* (the sixteenths are of another picture now) */
		} else if ((image->parts_known & (1u << image->part)) && part != image->part_sum[image->part]) {
			changed = true;
			image->parts_known = 0;
		}
		image->sum = sum;
		image->part_sum[image->part] = part;
		image->parts_known |= 1u << image->part;
		image->part = (image->part + 1) & 15;
		if (!changed) {
			image->quiet++;
			return false;
		}
		image->quiet = 0;
		return true;
	}
	for (size_t at = 0; at + 8 <= size; at += 8) {
		memcpy(&word, base + at, 8);
		sum = (sum ^ word) * 0x9e3779b97f4a7c15ull;
		sum ^= sum >> 29;
	}
	if (sum == image->sum) {
		image->quiet++;
		return false;
	}
	image->sum = sum;
	image->quiet = 0;
	return true;''')
open(path, 'w', newline='\n').write(s)
print('ok')
