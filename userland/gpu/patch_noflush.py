"""lavender: CoreAnimation's mid-frame glFlush not passed to Mesa (eagl.c), boot-arg glnoflush=1 (try).

CA calls glFlush ~10 times a frame on the home screen at c0x1884b62e0 (patch_flushwho.py), where the
display copy is already put off (glskip). Each flush still ends Mesa's batch: in sysmem mode it costs
CPU (glFlush is the costliest GL call in the profile), with tiles (glgmem=1) every flush resolves and
restores the screen - why GMEM was slower (run ai3: home 15.3 fps against 22). glFlush has no meaning
inside one context beyond "start soon"; Mesa still splits a batch where a later draw reads what it
drew. glnoflush=1: at the calls glskip names, glFlush is skipped (eagl's own frame_end still runs).

usage: python patch_noflush.py EAGL_C   (after patch_flushwho.py; .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static bool who_defer;                  /* ... this call is one of them */''',
    '''static bool who_defer;                  /* ... this call is one of them */
static int noflush_on;                  /* lavender: boot-arg glnoflush=1 - and its glFlush is skipped (patch_noflush.py) */
static unsigned noflush_n;''')
sub('''		who_lines = strstr(arguments, "glwho=1") != NULL;''', '''		who_lines = strstr(arguments, "glwho=1") != NULL;
		noflush_on = strstr(arguments, "glnoflush=1") != NULL;''')
sub('''	clear_now(e);
	began = now_us();
	glFlush();
	e->flushing += now_us() - began;''', '''	clear_now(e);
	began = now_us();
	if (noflush_on && who_defer) {
		noflush_n++;
	} else {
		glFlush();
	}
	e->flushing += now_us() - began;''')
sub('''			say("redwood-gl: %u display copies put off (glskip), %u calls copied one out''', '''			if (noflush_on) {
				say("redwood-gl: %u glFlush skipped (glnoflush)\\n", noflush_n);
				noflush_n = 0;
			}
			say("redwood-gl: %u display copies put off (glskip), %u calls copied one out''')
open(path, 'w', newline='\n').write(s)
print('ok')
