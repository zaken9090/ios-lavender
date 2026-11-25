"""lavender: who holds the wired IOSurface memory (patch 1018).

With gpu=1 the kernel's wired pages grew to 1.7 GB of the 1.95 GB iOS has (SMM lines, patch 1017)
and the UI paged its code in from disk, throttled. Buffer surfaces are wired kernel memory, capped
at SWEET_SURFACE_WIRED_MAX (1.5 GB). Each sampler round (bsd/dev/sweet_sample.c) now prints

  SMS wired <MB> | live <MB> in <n> | name <pub MB>/<n> <held MB>/<n>(r<retains>) ...

wired: sweet_surface_wired; live: every buffer surface still alive (a list of all of them), by the
process that created them: published (in the table, id lookups work) or only held (nobody can
look it up any more, something still retains it: a mapping, a texture, a leak).

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
	SweetSurface             *allNext, *allPrev;    /* lavender: every live surface, for the SMS line */
''')
sub('''gpuPool = false; poolSize = 0; return OSObject::init(); }''',
    '''gpuPool = false; poolSize = 0; creator[0] = 0; allNext = allPrev = NULL; return OSObject::init(); }''')
save()

load('iokit/Kernel/arm/SweetSurface.cpp')
sub('''	if (ret != kIOReturnSuccess || sweet_surface_creates_logged < 64) {
		char name[32];''', '''	proc_selfname(s->creator, sizeof(s->creator));      /* lavender: for the SMS lines */
	if (ret != kIOReturnSuccess || sweet_surface_creates_logged < 64) {
		char name[32];''')
sub('''OSDefineMetaClassAndStructors(SweetSurface, OSObject);
''', '''OSDefineMetaClassAndStructors(SweetSurface, OSObject);

/*
 * lavender: every live surface is on a list, so that the sampler's SMS line can tell the published
 * ones (in the table, id lookups work) from those only something else still holds, by the process
 * that created them (xnu/src/mk_surfstat.py).
 */
static SweetSurface *sweet_surface_all;     /* sweet_surface_lock */

extern "C" void sweet_surface_report(void);
void
sweet_surface_report(void)
{
	struct { char name[20]; uint64_t pub, held; uint32_t npub, nheld, refs; } by[14];
	unsigned names = 0, n = 0;
	uint64_t all = 0;
	char line[600];
	int len;

	if (sweet_surface_lock == NULL) {
		return;
	}
	IOLockLock(sweet_surface_lock);
	for (SweetSurface *t = sweet_surface_all; t != NULL; t = t->allNext) {
		if (OSDynamicCast(IOBufferMemoryDescriptor, t->memory) == NULL) {
			continue;       /* GPU pool, wrapped client memory, physical: not wired by surfaces */
		}
		bool pub = t->id < SWEET_SURFACE_MAX_ID && sweet_surface_table[t->id] == t;
		n++;
		all += t->allocSize;
		unsigned i;
		for (i = 0; i < names && strncmp(by[i].name, t->creator[0] ? t->creator : "?", sizeof(by[i].name)) != 0; i++) {
		}
		if (i == names && names < 14) {
			strlcpy(by[i].name, t->creator[0] ? t->creator : "?", sizeof(by[i].name));
			by[i].pub = by[i].held = 0;
			by[i].npub = by[i].nheld = by[i].refs = 0;
			names++;
		}
		if (i < names) {
			if (pub) {
				by[i].pub += t->allocSize;
				by[i].npub++;
			} else {
				by[i].held += t->allocSize;
				by[i].nheld++;
				by[i].refs += (uint32_t)t->getRetainCount();
			}
		}
	}
	IOLockUnlock(sweet_surface_lock);
	/* name pubMB/n heldMB/n(retains of the held ones) */
	len = snprintf(line, sizeof(line), "SMS wired %llu | live %llu in %u |", sweet_surface_wired >> 20, all >> 20, n);
	for (unsigned i = 0; i < names && len < (int)sizeof(line) - 60; i++) {
		len += snprintf(line + len, sizeof(line) - len, " %s %llu/%u %llu/%u(r%u)", by[i].name, by[i].pub >> 20,
		    by[i].npub, by[i].held >> 20, by[i].nheld, by[i].refs);
	}
	IOLog("%s\n", line);
}
''')
sub('''void
SweetSurface::free()
{
''', '''void
SweetSurface::free()
{
	if (sweet_surface_lock != NULL) {       /* lavender: off the list of live surfaces */
		IOLockLock(sweet_surface_lock);
		if (allPrev != NULL) {
			allPrev->allNext = allNext;
		} else if (sweet_surface_all == this) {
			sweet_surface_all = allNext;
		}
		if (allNext != NULL) {
			allNext->allPrev = allPrev;
		}
		IOLockUnlock(sweet_surface_lock);
	}
''')
sub('''	SweetSurface *s = OSTypeAlloc(SweetSurface);
	if (s == NULL || !s->init()) {
		OSSafeReleaseNULL(s);
		return NULL;
	}
''', '''	SweetSurface *s = OSTypeAlloc(SweetSurface);
	if (s == NULL || !s->init()) {
		OSSafeReleaseNULL(s);
		return NULL;
	}
	IOLockLock(sweet_surface_lock);         /* lavender: on the list of live surfaces (SMS line) */
	s->allNext = sweet_surface_all;
	if (sweet_surface_all != NULL) {
		sweet_surface_all->allPrev = s;
	}
	sweet_surface_all = s;
	IOLockUnlock(sweet_surface_lock);
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
