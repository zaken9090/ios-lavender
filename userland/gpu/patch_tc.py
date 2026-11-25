"""lavender: Mesa's driver half on a thread of its own (FD_TC=1), boot-arg gltc=0: one thread (eagl.c).

backboardd's drawing thread runs one core flat out and glDrawElements (Mesa's state emit and draw
packets) is the biggest GL cost (SMC line and eagl's profile, 2026-11-25). Mesa's threaded context
(u_threaded_context; userland/mesa/freedreno-texbarrier.patch turns it on for OSMesa with FD_TC=1
and fixes the a5xx paths under it) queues the calls and a driver thread turns them into GPU
commands on another core.

With it glFlush only queues. What the display is about to take must be with the kernel, so a
frame's end calls OSMesaFlushSync() (same patch: the queue run to its end, no wait for the GPU)
when the library has it. The Mesa patches are from the user's first lavender project (copied with
permission); this eagl side is written for this base.

usage: python patch_tc.py EAGL_C   (after patch_sysmem.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#include <unistd.h>
''', '''#include <unistd.h>
#include <dlfcn.h>
''')

# FD_TC=1 by default, next to sysmem
sub('''		if (strstr(arguments, "glgmem=1") == NULL) {''', '''		if (strstr(arguments, "gltc=0") == NULL) {
			/* lavender: Mesa's driver half on its own thread (patch_tc.py) */
			setenv("FD_TC", "1", 0);
			say("redwood-gl: in the environment by default: FD_TC=1 (gltc=0: Mesa on one thread)\\n");
		}
		if (strstr(arguments, "glgmem=1") == NULL) {''')

# a frame's end: everything queued goes to the kernel
sub('''static void frame_functions(struct eagl *e);
static void
frame_end(struct eagl *e, bool finished)
{''', '''/*
 * lavender: with Mesa's threaded context glFlush only queues; OSMesaFlushSync() (freedreno-
 * texbarrier.patch) runs the queue to its end, so that the kernel has every submission of the frame
 * before the display is told of it. 1: done; 0: the library has no such function.
 */
static int
lv_flush_sync(void)
{
	static void (*sync)(void);
	static int looked;

	if (!looked) {
		looked = 1;
		sync = (void (*)(void))dlsym(RTLD_DEFAULT, "OSMesaFlushSync");
		say("redwood-gl: a frame's end through %s\\n", sync != NULL ? "OSMesaFlushSync" : "glFlush and a fence");
	}
	if (sync == NULL) {
		return 0;
	}
	sync();
	return 1;
}

static void frame_functions(struct eagl *e);
static void
frame_end(struct eagl *e, bool finished)
{''')
sub('''	if (in_place != 0 && !finished && wait_for_frames) {
		glFinish();             /* the display's driver reads the surface as soon as it is told of it */
	} else if (in_place != 0 && !finished && sync_frames) {''', '''	if (in_place != 0 && !finished && wait_for_frames) {
		glFinish();             /* the display's driver reads the surface as soon as it is told of it */
	} else if (in_place != 0 && !finished && sync_frames && lv_flush_sync()) {
		/* lavender: all of the frame is with the kernel now (patch_tc.py) */
	} else if (in_place != 0 && !finished && sync_frames) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
