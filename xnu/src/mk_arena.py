"""lavender: a contiguous arena for GPU-shareable IOSurfaces (patch 1029), boot-arg sweetsurf_arena=MB.

With the GPU's SMMU in pass-through the GPU reads a surface in place only if its memory is
physically contiguous. By the time applications make their surfaces RAM is in pieces (the log is
full of vm_page_find_contiguous ... found 0 pages; "0 contiguous buffers of 12 MB set aside"), so
eagl copies them into textures: glTexImage2D was the most expensive GL call of a frame and Settings
stayed at ~24 fps whatever the GPU clock or the vsync rate (2026-11-25).

At IOCoreSurfaceRoot start, while RAM is still whole, chunks of 32 MB of contiguous kernel memory
are set aside (boot-arg sweetsurf_arena=MB; none by default: measured, hardly used). Surfaces the GPU can take as they are
(4 bytes a pixel, one plane, rows 64-byte aligned, 64 KB or more) are cut from them in 16 KB
units, with the 64 guard rows, as IOSubMemoryDescriptors of the chunk. A part freed while
something still holds its descriptor (a mapping, a GPU buffer) waits until only the arena does.
Arena memory is cached: RedwoodGPU already pushes such surfaces out of the CPU cache.
The idea comes from the user's first lavender project (its patches 1018/1019); code written here.

usage: python mk_arena.py XNU_TREE
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
sub('''	char                      creator[20];''', '''	int                       arenaChunk;   /* lavender: memory from the contiguous arena (-1: not), mk_arena.py */
	uint32_t                  arenaFirst, arenaUnits;       /* ... its 16 KB units there */
	char                      creator[20];''')
sub('''creator[0] = 0; allNext = allPrev = NULL;''', '''creator[0] = 0; arenaChunk = -1; arenaFirst = arenaUnits = 0; allNext = allPrev = NULL;''')
save()

load('iokit/Kernel/arm/SweetSurface.cpp')
if '#include <IOKit/IOSubMemoryDescriptor.h>' not in s:
    sub('''#include <IOKit/IOLocks.h>
''', '''#include <IOKit/IOLocks.h>
#include <IOKit/IOSubMemoryDescriptor.h>
''')

sub('''OSDefineMetaClassAndStructors(SweetSurface, OSObject);
''', '''/*
 * lavender: the contiguous arena (xnu/src/mk_arena.py). Chunks of contiguous kernel memory taken at
 * IOCoreSurfaceRoot start; GPU-shareable surfaces are parts of them, so the GPU reads them in place.
 */
#define SWEET_ARENA_CHUNK       (32u << 20)
#define SWEET_ARENA_UNIT        (16u << 10)
#define SWEET_ARENA_UNITS       (SWEET_ARENA_CHUNK / SWEET_ARENA_UNIT)  /* 2048 */
#define SWEET_ARENA_MAX         16
#define SWEET_ARENA_WAIT        128
static IOBufferMemoryDescriptor *sweet_arena_md[SWEET_ARENA_MAX];
static uint8_t                  *sweet_arena_va[SWEET_ARENA_MAX];
static uint64_t                  sweet_arena_map[SWEET_ARENA_MAX][SWEET_ARENA_UNITS / 64];     /* bit set: used */
static uint32_t                  sweet_arena_used, sweet_arena_most, sweet_arena_missed;        /* units; sweet_surface_lock */
static unsigned                  sweet_arena_n;
static struct {
	IOMemoryDescriptor *md;
	int chunk;
	uint32_t first, units;
} sweet_arena_wait[SWEET_ARENA_WAIT];                  /* freed while held: sweet_surface_lock */

static void
sweet_arena_mark(int c, uint32_t first, uint32_t units, bool used)
{
	for (uint32_t u = first; u < first + units; u++) {
		if (used) {
			sweet_arena_map[c][u / 64] |= 1ull << (u % 64);
		} else {
			sweet_arena_map[c][u / 64] &= ~(1ull << (u % 64));
		}
	}
	sweet_arena_used = used ? sweet_arena_used + units : sweet_arena_used - units;
	if (sweet_arena_used > sweet_arena_most) {
		sweet_arena_most = sweet_arena_used;
	}
}

static void
sweet_arena_fill(void)
{
	static bool filled;
	uint32_t gpu = 0, mb = 0;

	if (filled) {
		return;
	}
	filled = true;
	/*
	 * Off by default (measured 2026-11-25: at most 12 MB used, fps unchanged): applications' layers
	 * are mostly surfaces around their own memory (wrapped), which no arena can hold. sweetsurf_arena=MB.
	 */
	(void)gpu;
	PE_parse_boot_argn("sweetsurf_arena", &mb, sizeof(mb));
	unsigned want = mb / (SWEET_ARENA_CHUNK >> 20), n = 0;
	if (want > SWEET_ARENA_MAX) {
		want = SWEET_ARENA_MAX;
	}
	for (; n < want; n++) {
		IOBufferMemoryDescriptor *m = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task,
		    kIODirectionInOut | kIOMemoryKernelUserShared | kIOMemoryPhysicallyContiguous, SWEET_ARENA_CHUNK,
		    0x0000000FFFFFC000ull);
		if (m == NULL) {
			break;
		}
		sweet_arena_md[n] = m;
		sweet_arena_va[n] = (uint8_t *)m->getBytesNoCopy();
	}
	sweet_arena_n = n;
	if (want != 0) {
		IOLog("SWEET SURF: arena: %u of %u contiguous chunks of %u MB\\n", n, want, SWEET_ARENA_CHUNK >> 20);
	}
}

/* Lock held: parts freed while something held them go back once only the arena does. */
static void
sweet_arena_sweep_locked(void)
{
	for (unsigned i = 0; i < SWEET_ARENA_WAIT; i++) {
		if (sweet_arena_wait[i].md != NULL && sweet_arena_wait[i].md->getRetainCount() == 1) {
			sweet_arena_wait[i].md->release();
			sweet_arena_wait[i].md = NULL;
			sweet_arena_mark(sweet_arena_wait[i].chunk, sweet_arena_wait[i].first, sweet_arena_wait[i].units, false);
		}
	}
}

/* Contiguous memory of size bytes from the arena for s, or NULL. */
static IOMemoryDescriptor *
sweet_arena_take(SweetSurface *s, uint64_t size)
{
	uint32_t units = (uint32_t)((size + SWEET_ARENA_UNIT - 1) / SWEET_ARENA_UNIT);
	int chunk = -1;
	uint32_t first = 0;

	if (sweet_arena_n == 0 || units == 0 || units > SWEET_ARENA_UNITS) {
		return NULL;
	}
	IOLockLock(sweet_surface_lock);
	sweet_arena_sweep_locked();
	for (unsigned c = 0; c < sweet_arena_n && chunk < 0; c++) {
		uint32_t run = 0;
		for (uint32_t u = 0; u < SWEET_ARENA_UNITS; u++) {
			if (sweet_arena_map[c][u / 64] & (1ull << (u % 64))) {
				run = 0;
			} else if (++run == units) {
				chunk = (int)c;
				first = u + 1 - units;
				break;
			}
		}
	}
	if (chunk >= 0) {
		sweet_arena_mark(chunk, first, units, true);
	} else {
		sweet_arena_missed++;
	}
	IOLockUnlock(sweet_surface_lock);
	if (chunk < 0) {
		return NULL;
	}
	IOMemoryDescriptor *md = IOSubMemoryDescriptor::withSubRange(sweet_arena_md[chunk],
	    (IOByteCount)first * SWEET_ARENA_UNIT, (IOByteCount)units * SWEET_ARENA_UNIT, kIODirectionInOut);
	if (md == NULL) {
		IOLockLock(sweet_surface_lock);
		sweet_arena_mark(chunk, first, units, false);
		IOLockUnlock(sweet_surface_lock);
		return NULL;
	}
	s->arenaChunk = chunk;
	s->arenaFirst = first;
	s->arenaUnits = units;
	return md;
}

/* s's arena part goes back: now, or once nobody else holds its descriptor. Takes s's reference on it. */
static void
sweet_arena_give(SweetSurface *s)
{
	IOMemoryDescriptor *md = s->memory;
	bool kept = false;

	IOLockLock(sweet_surface_lock);
	if (md->getRetainCount() == 1) {
		sweet_arena_mark(s->arenaChunk, s->arenaFirst, s->arenaUnits, false);
	} else {
		for (unsigned i = 0; i < SWEET_ARENA_WAIT && !kept; i++) {
			if (sweet_arena_wait[i].md == NULL) {
				sweet_arena_wait[i].md = md;
				sweet_arena_wait[i].chunk = s->arenaChunk;
				sweet_arena_wait[i].first = s->arenaFirst;
				sweet_arena_wait[i].units = s->arenaUnits;
				kept = true;
			}
		}
		/* (no room to wait: the units stay used for good rather than be shared twice) */
	}
	IOLockUnlock(sweet_surface_lock);
	if (!kept) {
		md->release();
	}
	s->memory = NULL;
	s->arenaChunk = -1;
}

OSDefineMetaClassAndStructors(SweetSurface, OSObject);
''')

# the SMS line also says how full the arena is
sub('''	len = snprintf(line, sizeof(line), "SMS wired %llu | live %llu in %u |", sweet_surface_wired >> 20, all >> 20, n);''',
    '''	len = snprintf(line, sizeof(line), "SMS wired %llu | arena %u of %u MB, most %u, missed %u | live %llu in %u |",
	    sweet_surface_wired >> 20, sweet_arena_used / 64, sweet_arena_n * (SWEET_ARENA_CHUNK >> 20), sweet_arena_most / 64,
	    sweet_arena_missed, all >> 20, n);''')

# free and the kernel's view
sub('''	OSSafeReleaseNULL(kernelMap);
	OSSafeReleaseNULL(values);
	if (gpuPool && memory != NULL) {''', '''	OSSafeReleaseNULL(kernelMap);
	OSSafeReleaseNULL(values);
	if (arenaChunk >= 0 && memory != NULL) {
		sweet_arena_give(this);         /* lavender: back to the arena (memory is NULL after) */
	}
	if (gpuPool && memory != NULL) {''')
sub('''	IOBufferMemoryDescriptor *buffer = OSDynamicCast(IOBufferMemoryDescriptor, memory);
	if (buffer != NULL) {
		return (uintptr_t)buffer->getBytesNoCopy();
	}''', '''	IOBufferMemoryDescriptor *buffer = OSDynamicCast(IOBufferMemoryDescriptor, memory);
	if (buffer != NULL) {
		return (uintptr_t)buffer->getBytesNoCopy();
	}
	if (arenaChunk >= 0) {          /* lavender: the arena chunk is mapped in the kernel already */
		return (uintptr_t)(sweet_arena_va[arenaChunk] + (uint64_t)arenaFirst * SWEET_ARENA_UNIT);
	}''')

# the root takes the chunks while RAM is whole
sub('''	sweet_surface_init_lock();
	setProperty(kIOUserClientClassKey, "IOSurfaceRootUserClient");''', '''	sweet_surface_init_lock();
	sweet_arena_fill();             /* lavender: contiguous chunks while RAM is still whole (mk_arena.py) */
	setProperty(kIOUserClientClassKey, "IOSurfaceRootUserClient");''')

# create: a shareable surface comes from the arena
sub('''			uint64_t take = gpu_low ? sweet_round_upage(s->allocSize + 64ull * s->bytesPerRow) : s->allocSize;
			if (gpu_low) {
				sweet_res_fill();''', '''			uint64_t take = gpu_low ? sweet_round_upage(s->allocSize + 64ull * s->bytesPerRow) : s->allocSize;
			/* lavender: what the GPU can read as it is comes from the contiguous arena */
			if (gpu_low && s->bytesPerElement == 4 && s->planeCount <= 1 && (s->bytesPerRow & 63) == 0 &&
			    s->allocSize >= (64u << 10)) {
				amem = sweet_arena_take(s, take);
			}
			if (gpu_low && amem == NULL) {
				sweet_res_fill();''')
sub('''			if (mem == NULL && gpu_low && take <= (16u << 20)) {''',
    '''			if (mem == NULL && amem == NULL && gpu_low && take <= (16u << 20)) {''')
sub('''			if (mem == NULL) {
				mem = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
				    kIODirectionInOut | kIOMemoryKernelUserShared, take, SWEET_UPAGE);
			}
		}
		if (mem == NULL) {
			OSAddAtomic64(-(SInt64)s->allocSize, (volatile SInt64 *)&sweet_surface_wired);
			ret = kIOReturnNoMemory;
		} else {''', '''			if (mem == NULL && amem == NULL) {
				mem = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
				    kIODirectionInOut | kIOMemoryKernelUserShared, take, SWEET_UPAGE);
			}
		}
		if (amem != NULL) {
			/* lavender: arena memory is the arena's, not counted as this surface's wired bytes */
			OSAddAtomic64(-(SInt64)s->allocSize, (volatile SInt64 *)&sweet_surface_wired);
			s->memory = amem;
			bzero((void *)s->kernelAddress(), (size_t)s->arenaUnits * SWEET_ARENA_UNIT);
			s->mapCache = kIOMapDefaultCache;
			if (!sweet_surface_publish(s)) {
				ret = kIOReturnNoResources;
			}
		} else if (mem == NULL) {
			OSAddAtomic64(-(SInt64)s->allocSize, (volatile SInt64 *)&sweet_surface_wired);
			ret = kIOReturnNoMemory;
		} else {''')
sub('''		IOBufferMemoryDescriptor *mem = NULL;
		if ((uint64_t)OSAddAtomic64(s->allocSize, (volatile SInt64 *)&sweet_surface_wired) +''',
    '''		IOBufferMemoryDescriptor *mem = NULL;
		IOMemoryDescriptor *amem = NULL;        /* lavender: from the arena */
		if ((uint64_t)OSAddAtomic64(s->allocSize, (volatile SInt64 *)&sweet_surface_wired) +''')
save()
print('ok')
