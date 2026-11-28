"""lavender: eagl's periodic lines only with boot-arg gllog=1 (eagl.c).
In "bad boots" (2026-11-28: av1 / av2, bn1 / bn2; Settings 49-54 fps, 10-16 % late frames against 58-60 and
4-8 %) nine of ten seconds with a 110-200 ms gap between frames were the seconds in which backboardd wrote
its every-200-frames summary: one line per GL entry point used, some 60 writes to the kernel's log from the
drawing thread. The line every 20 frames and the four once-a-second lines (scanout, canvas, surfaces in
use, glskip) are written from the same thread.
Now, by default, only the first 40 frames get their line (tools/quick.ps1 waits for "frame 40:") and the
summary is written once (frame 30). gllog=1 gives all of it back. One-time messages, errors and the lines
of their own switches (glsumstat, glwho, glcensus, glframes, gltrace, glsharewhy) are not touched.

usage: python patch_quietlog.py EAGL_C   (last of the eagl patches; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static int frame_lines;                 /* boot-arg glframes=1: a line for every frame (see frame_end()) */
''', '''static int frame_lines;                 /* boot-arg glframes=1: a line for every frame (see frame_end()) */
static int log_periodic;                /* lavender: boot-arg gllog=1 - the periodic lines (patch_quietlog.py) */
''')
sub('''		frame_lines = strstr(arguments, "glframes=1") != NULL;
''', '''		frame_lines = strstr(arguments, "glframes=1") != NULL;
		log_periodic = strstr(arguments, "gllog=1") != NULL;    /* lavender: patch_quietlog.py */
''')
sub('''	if (e->frames <= 40 || e->frames % 20 == 0) {
''', '''	if (e->frames <= 40 || (log_periodic && e->frames % 20 == 0)) {
''')
sub('''	if (e->frames == 30 || e->frames % 200 == 0) {
''', '''	if (e->frames == 30 || (log_periodic && e->frames % 200 == 0)) {
''')
sub('''		if (said != 0) {
			say("redwood-gl: %u frames copied to scanout surfaces, %u to their own (all four held)\\n", scan_copies, scan_none);
''', '''		if (said != 0 && log_periodic) {
			say("redwood-gl: %u frames copied to scanout surfaces, %u to their own (all four held)\\n", scan_copies, scan_none);
''')
sub('''		if (said != 0 && canvas_frames + canvas_others > 2) {
''', '''		if (said != 0 && log_periodic && canvas_frames + canvas_others > 2) {
''')
sub('''			if (said != 0 && frames > 2) {
				say("redwood-gl: %u display frames, %u began in a surface in use, %u of them let go while waiting\\n", frames, busy, freed);
''', '''			if (said != 0 && log_periodic && frames > 2) {
				say("redwood-gl: %u display frames, %u began in a surface in use, %u of them let go while waiting\\n", frames, busy, freed);
''')
sub('''		if (who_skips != 0) {
			say("redwood-gl: %u display copies put off (glskip), %u calls copied one out\\n", who_put_off_n, who_made_n);
''', '''		if (who_skips != 0 && log_periodic) {
			say("redwood-gl: %u display copies put off (glskip), %u calls copied one out\\n", who_put_off_n, who_made_n);
''')
open(path, 'w', newline='\n').write(s)
print('ok')
