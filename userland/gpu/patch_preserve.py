"""lavender: each frame in a display surface starts from the last frame (eagl.c, boot-arg glpreserve=0: off).

CoreAnimation draws only what changed since the frame before (the damage, inside a scissor box)
and leaves the rest of the picture as it was. The display has two surfaces that take turns, so
the rest of the surface being drawn into is two frames old: while Settings scrolled, rows of the
frame before last showed between the new ones ("Siri & Search" over "Passcode", 2026-11-25).

Now the first drawing of a frame into a display-sized target that is not the one drawn into last
copies that one into it first (a GPU blit, whole surface, scissor off). The idea comes from the
user's first lavender project (its eagl glpreserve); this code is written for this base.

usage: python patch_preserve.py EAGL_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


# the state: the display target drawn into last, and the switch
sub('''	GLuint writer;                  /* ... and one to copy a frame into its surface with (blit_targets) */
''', '''	GLuint writer;                  /* ... and one to copy a frame into its surface with (blit_targets) */
	GLuint last_display;            /* lavender: the display-sized target drawn into last (preserve_frame()) */
''')
sub('''static int sync_frames = 1;''', '''static int preserve_frames = 1;         /* lavender: boot-arg glpreserve=0 - a frame does not start from the last one */
static int sync_frames = 1;''')
sub('''		sync_frames = strstr(arguments, "glsync=0") == NULL;
''', '''		sync_frames = strstr(arguments, "glsync=0") == NULL;
		preserve_frames = strstr(arguments, "glpreserve=0") == NULL;
''')

# the copy, at the first drawing of a frame into a display target
sub('''/* Something is about to be drawn into the framebuffer that is bound. */
static void
drawing(struct eagl *e)
{
	struct image *image;

	frame_begin(e);
	if (e->framebuffer != 0 && e->colour != 0 && (image = image_of(e, e->colour)) != NULL && image->target) {
		image->drawn = image->painted = true;''', '''/*
 * lavender: CoreAnimation draws only the damage since the frame before and leaves the rest of the
 * surface as it is, but the display's two surfaces take turns: the rest is two frames old. Before
 * the first drawing of a frame into a display target, the one drawn into last is copied into it.
 */
static void
preserve_frame(struct eagl *e, struct image *image)
{
	struct image *last;
	GLint read = 0, draw = 0;
	GLboolean boxed;

	if (image->width < 1000 || image->height < 2000) {
		return;
	}
	if (preserve_frames && e->last_display != 0 && e->last_display != image->texture &&
	    (last = image_of(e, e->last_display)) != NULL && last->target && last->painted &&
	    last->width == image->width && last->height == image->height && last->invert == image->invert) {
		glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &read);
		glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &draw);
		boxed = glIsEnabled(GL_SCISSOR_TEST);
		if (e->reader == 0) {
			glGenFramebuffers(1, &e->reader);
		}
		if (e->writer == 0) {
			glGenFramebuffers(1, &e->writer);
		}
		glDisable(GL_SCISSOR_TEST);
		glBindFramebuffer(GL_READ_FRAMEBUFFER, e->reader);
		glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, last->texture, 0);
		glBindFramebuffer(GL_DRAW_FRAMEBUFFER, e->writer);
		glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, image->texture, 0);
		glBlitFramebuffer(0, 0, image->width, image->height, 0, 0, image->width, image->height,
		    GL_COLOR_BUFFER_BIT, GL_NEAREST);
		glBindFramebuffer(GL_READ_FRAMEBUFFER, (GLuint)read);
		glBindFramebuffer(GL_DRAW_FRAMEBUFFER, (GLuint)draw);
		(boxed ? glEnable : glDisable)(GL_SCISSOR_TEST);
	}
	e->last_display = image->texture;
}

/* Something is about to be drawn into the framebuffer that is bound. */
static void
drawing(struct eagl *e)
{
	struct image *image;

	frame_begin(e);
	if (e->framebuffer != 0 && e->colour != 0 && (image = image_of(e, e->colour)) != NULL && image->target) {
		if (!image->drawn) {
			preserve_frame(e, image);       /* lavender: the frame starts from the last one */
		}
		image->drawn = image->painted = true;''')
open(path, 'w', newline='\n').write(s)
print('ok')
