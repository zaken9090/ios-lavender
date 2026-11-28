"""lavender: no contiguous-memory hunt for every IOSurface once RAM is fragmented (patch 1172).

With gpu=1 SweetSurface asks for physically contiguous memory first (so that the Adreno, with the SMMU in
pass-through, can take the surface as it is) and falls back to ordinary pages. With ~25 MB free and the
rest in the page cache the request nearly always fails - after vm_page_find_contiguous has scanned all
125 000 pages twice and called zone_gc ("found 0 pages ... scanned 125013 pages ... zone_gc called"):
28 failures in a 40 s bench (au2), ~390 in 8 idle minutes (ar2), each on the thread of the application
that makes the surface, in the middle of a scroll. The user saw it as fps dips everywhere (2026-11-28);
86 % of the late frames in Settings start late after a short frame (touch_lat lines, run au2).
The first lavender project had the same and cured it (its patch 1000): after a failure, ordinary pages
for a while.

  sweetsurf_contig=0        never ask for contiguous memory (beyond the pool, the arena and the reserve)
  lv_contig_backoff_s=20    after a failed request, none for this many seconds
  lv_contig_min_kb=256      smaller surfaces never ask
A line every 10 s while something happened:
  "SWEET SURF: contiguous: N asked, F failed in T ms, S skipped"

usage: python mk_contigbackoff.py XNU_TREE   (after mk_gpudvfs.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new, count=1):
    s = open(path, newline='').read()
    assert s.count(old) == count, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


p = f'{tree}/iokit/Kernel/arm/SweetSurface.cpp'
patch(p, '''			if (mem == NULL && amem == NULL && gpu_low && take <= (16u << 20)) {
				mem = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task,
				    kIODirectionInOut | kIOMemoryKernelUserShared | kIOMemoryPhysicallyContiguous, take,
				    0x0000000FFFFFC000ull);
			}
''', '''			/*
			 * lavender (mk_contigbackoff.py): once RAM is fragmented every contiguous request fails
			 * after two scans of all pages and a zone_gc, on the thread that makes the surface: the
			 * stutter. After a failure, ordinary pages for lv_contig_backoff_s.
			 */
			static uint64_t contig_retry_at, contig_said, contig_fail_abs;
			static uint32_t contig_on = 1, contig_backoff = 20, contig_min_kb = 256, contig_read;
			static uint32_t contig_asked, contig_failed, contig_skipped;
			if (!contig_read) {
				contig_read = 1;
				PE_parse_boot_argn("sweetsurf_contig", &contig_on, sizeof(contig_on));
				PE_parse_boot_argn("lv_contig_backoff_s", &contig_backoff, sizeof(contig_backoff));
				PE_parse_boot_argn("lv_contig_min_kb", &contig_min_kb, sizeof(contig_min_kb));
			}
			if (mem == NULL && amem == NULL && gpu_low && take <= (16u << 20)) {
				uint64_t began = mach_absolute_time();
				if (!contig_on || take < ((uint64_t)contig_min_kb << 10) || began < contig_retry_at) {
					contig_skipped++;
				} else {
					contig_asked++;
					mem = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task,
					    kIODirectionInOut | kIOMemoryKernelUserShared | kIOMemoryPhysicallyContiguous, take,
					    0x0000000FFFFFC000ull);
					if (mem == NULL) {
						uint64_t wait, now = mach_absolute_time();
						nanoseconds_to_absolutetime((uint64_t)contig_backoff * NSEC_PER_SEC, &wait);
						contig_retry_at = now + wait;
						contig_failed++;
						contig_fail_abs += now - began;
					}
				}
				uint64_t every, now = mach_absolute_time();
				nanoseconds_to_absolutetime(10ull * NSEC_PER_SEC, &every);
				if (now - contig_said >= every && (contig_asked | contig_skipped) != 0) {
					uint64_t ns = 0;
					absolutetime_to_nanoseconds(contig_fail_abs, &ns);
					IOLog("SWEET SURF: contiguous: %u asked, %u failed in %llu ms, %u skipped\\n", contig_asked,
					    contig_failed, ns / 1000000, contig_skipped);
					contig_said = now;
					contig_asked = contig_failed = contig_skipped = 0;
					contig_fail_abs = 0;
				}
			}
''')
patch(p, '''#include <pexpert/pexpert.h>
#include <libkern/c++/OSArray.h>
''', '''#include <pexpert/pexpert.h>
#include <kern/clock.h>                 /* lavender: mk_contigbackoff.py */
#include <libkern/c++/OSArray.h>
''')
print('ok')
