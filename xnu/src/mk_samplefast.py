"""lavender: sampler timing from boot-args (patch 1032): sweetsample_first=S (90), sweetsample_s=S (120), sweetsample_n=N (40).

To see where an application is during an animation the sampler must run every second or two.

usage: python mk_samplefast.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_sample.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	(void)tsleep(&chan, PZERO, "sweetsmp", 90 * hz);
	for (int i = 0; i < 40; i++) {''', '''	/* lavender: timing from boot-args (xnu/src/mk_samplefast.py) */
	uint32_t first = 90, every = 120, count = 40;
	PE_parse_boot_argn("sweetsample_first", &first, sizeof(first));
	PE_parse_boot_argn("sweetsample_s", &every, sizeof(every));
	PE_parse_boot_argn("sweetsample_n", &count, sizeof(count));
	(void)tsleep(&chan, PZERO, "sweetsmp", (int)first * hz);
	for (int i = 0; i < (int)count; i++) {''')
sub('''		(void)tsleep(&chan, PZERO, "sweetsmp", 120 * hz);''', '''		(void)tsleep(&chan, PZERO, "sweetsmp", (int)(every ? every : 1) * hz);''')
open(path, 'w', newline='\n').write(s)
print('ok')
