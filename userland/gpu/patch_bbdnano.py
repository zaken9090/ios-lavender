"""lavender: backboardd keeps the nano malloc zone through our wrapper (bbd_wrap.c, boot-arg bbdnano=0: off).

launchd spawns daemons with _POSIX_SPAWN_NANO_ALLOCATOR; xnu then puts "MallocNanoZone=1" among the
apple strings (kern_exec.c, exec_add_apple_strings, only for posix_spawn with attributes). Our wrapper
execv()s the real backboardd, which has no spawn attributes: the string was lost and libmalloc ran every
small allocation through the scalable zone. The profiler (xnu 1149, sweetprof=backboardd, symbols from
the 20H392 dyld cache) put szone_malloc_should_clear / free_tiny at ~8.5% of backboardd's user time
while Settings scrolls. The wrapper now sets MallocNanoZone=1 in the environment (libmalloc reads it
there as well), unless bbdnano=0.

usage: python patch_bbdnano.py BBD_WRAP_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	(void)sysctlbyname("kern.bootargs", bootargs, &blen, NULL, 0);
''', '''	(void)sysctlbyname("kern.bootargs", bootargs, &blen, NULL, 0);
	/* lavender: what launchd's spawn flag gives, lost by execv (patch_bbdnano.py) */
	if (strstr(bootargs, "bbdnano=0") == NULL) {
		setenv("MallocNanoZone", "1", 1);
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
