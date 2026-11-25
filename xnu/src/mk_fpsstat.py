"""lavender: the SWEET FPS line says how frames were shown and how long the GPU was waited for (patch 1027).

Home stayed at ~8 fps whether the GPU core ran at 300 or 600 MHz (2026-11-25), Settings at ~24:
so where does a home frame's time go? The line gains

  ...; direct D copied C, GPU waited G us a frame

direct: shown by pointing the MDP at the surface; copied: composed by the CPU into the splash
(several layers); GPU waited: topaz_surface_drawn() before a direct frame (the kernel waits for
the last submission that named the surface).

usage: python mk_fpsstat.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetFramebuffer.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static uint64_t sweet_fps_wait_ns, sweet_fps_after_ns;''',
    '''static uint32_t lv_fps_direct, lv_fps_copied;      /* lavender: this second's frames by path (mk_fpsstat.py) */
static uint64_t lv_fps_gpu_abs;                    /* ... and the time spent waiting for the GPU before direct ones */
static uint64_t sweet_fps_wait_ns, sweet_fps_after_ns;''')
sub('''		IOLog("SWEET FPS: %u frames in %llu ms, longest gap %llu ms, %u late; a frame: %llu us in present + latch, "
		    "came %llu us after the tick\\n", frames, ns / 1000000, gap_max / 1000000, late,
		    frames ? sweet_fps_wait_ns / 1000 / frames : 0, frames ? sweet_fps_after_ns / 1000 / frames : 0);''',
    '''		uint64_t gpu_ns = 0;
		absolutetime_to_nanoseconds(lv_fps_gpu_abs, &gpu_ns);
		IOLog("SWEET FPS: %u frames in %llu ms, longest gap %llu ms, %u late; a frame: %llu us in present + latch, "
		    "came %llu us after the tick; direct %u copied %u, GPU waited %llu us a frame\\n", frames, ns / 1000000,
		    gap_max / 1000000, late,
		    frames ? sweet_fps_wait_ns / 1000 / frames : 0, frames ? sweet_fps_after_ns / 1000 / frames : 0,
		    lv_fps_direct, lv_fps_copied, lv_fps_direct ? gpu_ns / 1000 / lv_fps_direct : 0);
		lv_fps_direct = lv_fps_copied = 0;
		lv_fps_gpu_abs = 0;''')
sub('''	bool ok = false;
	(void)topaz_surface_drawn(s, 100);''', '''	bool ok = false;
	uint64_t lv_t0 = mach_absolute_time();
	(void)topaz_surface_drawn(s, 100);
	lv_fps_gpu_abs += mach_absolute_time() - lv_t0;''')
sub('''				ok = true;
				IOLockLock(fLock);''', '''				ok = true;
				lv_fps_direct++;
				IOLockLock(fLock);''')
sub('''	IOLockLock(fLock);
	fLastVA = NULL;
	IOLockUnlock(fLock);''', '''	lv_fps_copied++;
	IOLockLock(fLock);
	fLastVA = NULL;
	IOLockUnlock(fLock);''')
open(path, 'w', newline='\n').write(s)
print('ok')
