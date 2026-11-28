"""lavender: surface_changed() adds up in four independent chains, with prefetch (eagl.c, no boot-arg).
Profile pf7 (xnu 1149 sweetprof=backboardd, home screen swiped, kernel run-46125445657, userland
46121702037): surface_changed was 1941 of 12983 user samples of backboardd (15 %; Settings pf5: 3 %):
~1000 in the full sum of surfaces below 1 MB (icons), ~700 in the word-every-512-bytes look at big ones
(wallpapers 6-9 MB, a cache miss a word) and ~200 in the sixteenth. Every 8 bytes went through one chain
(eor, mul, eor-shift: ~6 cycles a word, nothing to overlap) and the 512-byte stride got no prefetch.
Now four chains run side by side and the sampled look prefetches 16 words ahead. What is compared is
the same (the same words, the same decisions); only the numbers the sums come to differ.

usage: python patch_sumfast.py EAGL_C   (after patch_sumfull.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static bool
surface_changed(struct eagl *e, struct image *image)
{''', '''/* lavender (patch_sumfast.py): four chains of (sum ^ word) * K, folded at the end */
#define LV_MIX(h, w) ((h) = ((h) ^ (w)) * 0x9e3779b97f4a7c15ull, (h) ^= (h) >> 29)

static uint64_t
lv_sum_run(const uint8_t *base, size_t from, size_t to, size_t step, uint64_t seed)
{
	uint64_t h0 = seed, h1 = seed ^ 0x243f6a8885a308d3ull, h2 = seed ^ 0x13198a2e03707344ull,
	    h3 = seed ^ 0xa4093822299f31d0ull, w0, w1, w2, w3;
	size_t at = from;

	if (step == 8) {
		for (; at + 32 <= to; at += 32) {
			memcpy(&w0, base + at, 8);
			memcpy(&w1, base + at + 8, 8);
			memcpy(&w2, base + at + 16, 8);
			memcpy(&w3, base + at + 24, 8);
			LV_MIX(h0, w0);
			LV_MIX(h1, w1);
			LV_MIX(h2, w2);
			LV_MIX(h3, w3);
		}
	} else {
		for (; at + 3 * step + 8 <= to; at += 4 * step) {
			if (at + 20 * step + 8 <= to) {
				__builtin_prefetch(base + at + 16 * step);
				__builtin_prefetch(base + at + 17 * step);
				__builtin_prefetch(base + at + 18 * step);
				__builtin_prefetch(base + at + 19 * step);
			}
			memcpy(&w0, base + at, 8);
			memcpy(&w1, base + at + step, 8);
			memcpy(&w2, base + at + 2 * step, 8);
			memcpy(&w3, base + at + 3 * step, 8);
			LV_MIX(h0, w0);
			LV_MIX(h1, w1);
			LV_MIX(h2, w2);
			LV_MIX(h3, w3);
		}
	}
	for (; at + 8 <= to; at += step) {
		memcpy(&w0, base + at, 8);
		LV_MIX(h0, w0);
	}
	LV_MIX(h0, h1);
	LV_MIX(h0, h2);
	LV_MIX(h0, h3);
	return h0;
}

static bool
surface_changed(struct eagl *e, struct image *image)
{''')
sub('''		for (size_t at = 0; at + 8 <= size; at += 512) {
			memcpy(&word, base + at, 8);
			sum = (sum ^ word) * 0x9e3779b97f4a7c15ull;
			sum ^= sum >> 29;
		}
		for (size_t at = from; at + 8 <= to; at += 8) {
			memcpy(&word, base + at, 8);
			part = (part ^ word) * 0x9e3779b97f4a7c15ull;
			part ^= part >> 29;
		}''', '''		sum = lv_sum_run(base, 0, size, 512, sum);         /* lavender: patch_sumfast.py */
		part = lv_sum_run(base, from, to, 8, part);''')
sub('''	for (size_t at = 0; at + 8 <= size; at += 8) {
		memcpy(&word, base + at, 8);
		sum = (sum ^ word) * 0x9e3779b97f4a7c15ull;
		sum ^= sum >> 29;
	}
	if (sum == image->sum) {''', '''	sum = lv_sum_run(base, 0, size, 8, sum);                   /* lavender: patch_sumfast.py */
	(void)word;
	if (sum == image->sum) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
