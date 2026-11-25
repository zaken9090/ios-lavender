"""lavender: who holds the wired IOSurface memory (patch 1018).

With gpu=1 the kernel's wired pages grew to 1.7 GB of the 1.95 GB iOS has (SMM lines, patch 1017)
and the UI paged its code in from disk, throttled. Buffer surfaces are wired kernel memory, capped
at SWEET_SURFACE_WIRED_MAX (1.5 GB). Each sampler round (bsd/dev/sweet_sample.c) now prints

  SMS wired <MB> | table <MB> in <n> | name <MB>/<n> ...

wired: sweet_surface_wired (all live buffer surfaces); table: those still published (an id that
can be looked up), by the process that created them. wired - table = surfaces nobody can look
up any more but something still holds (a mapping, a texture, a leak).

usage: python mk_surfstat.py XNU_TREE
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


load('iokit/Kernel/arm/SweetSurface.h')
sub('''	uint64_t                  poolSize;     /* bytes taken from the GPU pool (allocSize and a guard) */
''', '''	uint64_t                  poolSize;     /* bytes taken from the GPU pool (allocSize and a guard) */
	char                      creator[20];  /* lavender: the creating process (xnu/src/mk_surfstat.py) */
''')
sub('''gpuPool = false; poolSize = 0; return OSObject::init(); }''',
    '''gpuPool = false; poolSize = 0; creator[0] = 0; return OSObject::init(); }''')
save()

load('iokit/Kernel/arm/SweetSurface.cpp')
sub('''	if (ret != kIOReturnSuccess || sweet_surface_creates_logged < 64) {
		char name[32];''', '''	proc_selfname(s->creator, sizeof(s->creator));      /* lavender: for the SMS lines */
	if (ret != kIOReturnSuccess || sweet_surface_creates_logged < 64) {
		char name[32];''')
sub('''OSDefineMetaClassAndStructors(SweetSurface, OSObject);
''', '''OSDefineMetaClassAndStructors(SweetSurface, OSObject);

/*
 * lavender: the sampler's SMS line - wired buffer surfaces, and those still in the table by the
 * process that created them (xnu/src/mk_surfstat.py).
 */
extern "C" void sweet_surface_report(void);
void
sweet_surface_report(void)
{
	struct { char name[20]; uint64_t bytes; uint32_t n; } by[12];
	unsigned names = 0, n = 0;
	uint64_t table = 0;
	char line[480];
	int len;

	if (sweet_surface_lock == NULL) {
		return;
	}
	IOLockLock(sweet_surface_lock);
	for (uint32_t id = 1; id < SWEET_SURFACE_MAX_ID; id++) {
		SweetSurface *t = sweet_surface_table[id];
		if (t == NULL || OSDynamicCast(IOBufferMemoryDescriptor, t->memory) == NULL) {
			continue;
		}
		n++;
		table += t->allocSize;
		unsigned i;
		for (i = 0; i < names && strncmp(by[i].name, t->creator, sizeof(by[i].name)) != 0; i++) {
		}
		if (i == names && names < 12) {
			strlcpy(by[i].name, t->creator[0] ? t->creator : "?", sizeof(by[i].name));
			by[i].bytes = 0;
			by[i].n = 0;
			names++;
		}
		if (i < names) {
			by[i].bytes += t->allocSize;
			by[i].n++;
		}
	}
	IOLockUnlock(sweet_surface_lock);
	len = snprintf(line, sizeof(line), "SMS wired %llu | table %llu in %u |", sweet_surface_wired >> 20, table >> 20, n);
	for (unsigned i = 0; i < names && len < (int)sizeof(line) - 40; i++) {
		len += snprintf(line + len, sizeof(line) - len, " %s %llu/%u", by[i].name, by[i].bytes >> 20, by[i].n);
	}
	IOLog("%s\\n", line);
}
''')
save()

load('bsd/dev/sweet_sample.c')
sub('''extern void sweet_sample_start(void);
''', '''extern void sweet_sample_start(void);
extern void sweet_surface_report(void);     /* SweetSurface.cpp: SMS line (xnu/src/mk_surfstat.py) */
''')
sub('''		proc_iterate(PROC_ALLPROCLIST, sweet_sample_proc, NULL, NULL, NULL);
''', '''		proc_iterate(PROC_ALLPROCLIST, sweet_sample_proc, NULL, NULL, NULL);
		sweet_surface_report();
''')
save()
print('ok')
