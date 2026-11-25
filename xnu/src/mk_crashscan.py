"""lavender: an abort's crash report also lists main-binary addresses left on the stack (patch 1037).

An uncaught C++ exception inside a dispatch block ends in abort() from _dispatch_client_callout:
the frame-pointer backtrace then shows libdispatch only and not who threw (CommCenter, 2026-11-26).
The frames that were unwound are still in memory below the stack pointer, so for signal 6/5 the
report scans 16 KB below sp and 1 KB above it for values inside the main binary (mh .. mh+32 MB)
and prints the first 28 different ones: "CRASH name scan 0x...". They are return addresses of the
calls that led to the throw (and some stale ones); offset in the binary = value - mh.

usage: python mk_crashscan.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/osfmk/kern/exception.c'
s = open(path, newline='').read()
old = '''	if (sig == 6 || sig == 5) {
		sweet_crash_strings(name);
	}
'''
assert s.count(old) == 1
s = s.replace(old, '''	if (sig == 6 || sig == 5) {
		sweet_crash_strings(name);
		/* lavender: main-binary addresses left on the stack (xnu/src/mk_crashscan.py) */
		uint64_t sp = get_saved_state_sp(ss) & ~7ull, seen[28];
		int found = 0;
		n = snprintf(line, sizeof(line), "CRASH %s scan", name);
		for (uint64_t at = sp - (16u << 10); at < sp + 1024 && found < 28; at += 8) {
			uint64_t word;
			bool again = false;
			if (copyin((user_addr_t)at, &word, sizeof(word)) != 0) {
				at |= PAGE_MASK - 7;            /* (on to the next page) */
				continue;
			}
			if (word < mh + 0x4000 || word >= mh + (32u << 20) || (word & 3) != 0) {
				continue;
			}
			for (int i = 0; i < found; i++) {
				again |= seen[i] == word;
			}
			if (again) {
				continue;
			}
			seen[found++] = word;
			if (n > (int)sizeof(line) - 20) {
				printf("%s\n", line);
				n = snprintf(line, sizeof(line), "CRASH %s scan", name);
			}
			n += snprintf(line + n, sizeof(line) - n, " 0x%llx", word);
		}
		if (found != 0) {
			printf("%s\n", line);
		}
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
