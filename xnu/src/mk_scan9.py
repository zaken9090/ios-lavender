"""lavender: sweetscan=NAME also lists the heap strings of a process that was killed (signal 9) (patch 1040).

driverkitd is killed by jetsam (per-process limit) inside -[NSData initWithContentsOfFile:]: which
file it reads is in its heap, not in the registers (2026-11-26). The string scan ran for aborts
and traps only; now for a kill too. Only for names in sweetscan, as before.

usage: python mk_scan9.py XNU_TREE   (after mk_crashscan.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/osfmk/kern/exception.c'
s = open(path, newline='').read()
old = '''	if (sig == 6 || sig == 5) {
		sweet_crash_strings(name);
'''
assert s.count(old) == 1
s = s.replace(old, '''	if (sig == 9) {
		sweet_crash_strings(name);      /* lavender: a killed process too (xnu/src/mk_scan9.py) */
	}
''' + old)
open(path, 'w', newline='\n').write(s)
print('ok')
