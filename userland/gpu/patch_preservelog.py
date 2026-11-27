"""lavender: boot-arg glpreservelog=N - the first N preserve copies are logged: source and target IOSurface ids (eagl.c).

To check whether glpreserve copies from display-sized surfaces that never reach the panel (offscreen
pictures CoreAnimation draws at screen size), against the kernel's list of swapped surfaces
(xnu 1158, lv_swaplog=N). Line: "redwood-gl: preserve S -> T".

usage: python patch_preservelog.py EAGL_C   (after patch_preserve.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		glBlitFramebuffer(0, 0, image->width, image->height, 0, 0, image->width, image->height,
		    GL_COLOR_BUFFER_BIT, GL_NEAREST);
		glBindFramebuffer(GL_READ_FRAMEBUFFER, (GLuint)read);
		glBindFramebuffer(GL_DRAW_FRAMEBUFFER, (GLuint)draw);
		(boxed ? glEnable : glDisable)(GL_SCISSOR_TEST);''', '''		glBlitFramebuffer(0, 0, image->width, image->height, 0, 0, image->width, image->height,
		    GL_COLOR_BUFFER_BIT, GL_NEAREST);
		glBindFramebuffer(GL_READ_FRAMEBUFFER, (GLuint)read);
		glBindFramebuffer(GL_DRAW_FRAMEBUFFER, (GLuint)draw);
		(boxed ? glEnable : glDisable)(GL_SCISSOR_TEST);
		if (preserve_log > 0 && last->surface != NULL && image->surface != NULL) {      /* lavender: patch_preservelog.py */
			preserve_log--;
			say("redwood-gl: preserve %u -> %u\\n", IOSurfaceGetID(last->surface), IOSurfaceGetID(image->surface));
		}''')
sub('''static int preserve_frames = 1;''', '''static int preserve_log;                /* lavender: glpreservelog=N (patch_preservelog.py) */
static int preserve_frames = 1;''')
sub('''		preserve_frames = strstr(arguments, "glpreserve=0") == NULL;''', '''		preserve_frames = strstr(arguments, "glpreserve=0") == NULL;
		if (strstr(arguments, "glpreservelog=") != NULL) {
			preserve_log = atoi(strstr(arguments, "glpreservelog=") + 14);
		}''')
open(path, 'w', newline='\n').write(s)
print('ok')
