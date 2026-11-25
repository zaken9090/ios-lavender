"""lavender: a draw that samples a surface drawn into since the last flush flushes first (eagl.c, glorder=0: off).

CoreAnimation draws into a display surface through one texture (attachImage, the target) and
samples the same surface through another (texImageIOSurface, e.g. the backdrop under the
navigation bar's blur). Both are the surface's memory, but to Mesa they are two resources, and
freedreno orders its batches by resource: the batch that reads the surface can run before the one
that writes it, and the read gets an older picture. Settings showed text of earlier frames while
scrolling (rows twice, a ghost of the large title, 2026-11-25), whatever else was tried (preserve,
seed, sysmem, glwait); with glcopy=1 (no shared surfaces) it was right.

Now the surfaces drawn into since the last flush are remembered, and a draw that samples one of
them, or the very texture it draws into, flushes first. Forgotten at a frame's end. The idea comes
from the user's first lavender project (its eagl glorder); this code is written for this base.

usage: python patch_order.py EAGL_C   (after patch_preserve.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static int preserve_frames = 1;''', '''static int order_draws = 1;             /* lavender: boot-arg glorder=0 - no flush before sampling a surface drawn into */
static int preserve_frames = 1;''')
sub('''		preserve_frames = strstr(arguments, "glpreserve=0") == NULL;
''', '''		preserve_frames = strstr(arguments, "glpreserve=0") == NULL;
		order_draws = strstr(arguments, "glorder=0") == NULL;
''')

sub('''/* Something is about to be drawn into the framebuffer that is bound. */
static void
drawing(struct eagl *e)
{
	struct image *image;

	frame_begin(e);''', '''/*
 * lavender: the IOSurfaces drawn into since the last flush. A draw that samples one of them through
 * another texture (Mesa: another resource, ordered on its own), or samples the texture it draws
 * into, flushes first so that it reads what was drawn (patch_order.py).
 */
static uint32_t order_drawn[16];
static unsigned order_count, order_flushes;

static void
order_before(struct eagl *e)
{
	struct image *image;
	bool flush = false;

	if (!order_draws) {
		return;
	}
	for (unsigned unit = 0; unit < 8 && !flush; unit++) {
		GLuint texture = e->bound[unit];

		if (texture == 0) {
			continue;
		}
		if (texture == e->colour) {
			flush = true;
		} else if (order_count != 0 && (image = image_of(e, texture)) != NULL && !image->target && image->surface != NULL) {
			uint32_t id = IOSurfaceGetID(image->surface);

			for (unsigned i = 0; i < order_count; i++) {
				flush |= order_drawn[i] == id;
			}
		}
	}
	if (flush) {
		glFlush();
		order_flushes++;
		order_count = 0;
	}
	if (e->colour != 0 && (image = image_of(e, e->colour)) != NULL && image->target && image->surface != NULL) {
		uint32_t id = IOSurfaceGetID(image->surface);
		bool known = false;

		for (unsigned i = 0; i < order_count; i++) {
			known |= order_drawn[i] == id;
		}
		if (!known) {
			if (order_count == sizeof(order_drawn) / sizeof(order_drawn[0])) {
				glFlush();      /* (too many to follow: everything written out) */
				order_flushes++;
				order_count = 0;
			}
			order_drawn[order_count++] = id;
		}
	}
}

/* Something is about to be drawn into the framebuffer that is bound. */
static void
drawing(struct eagl *e)
{
	struct image *image;

	frame_begin(e);
	order_before(e);                /* lavender */''')
sub('''	e->in_frame = false;
	e->frames++;''', '''	e->in_frame = false;
	e->frames++;
	order_count = 0;                /* lavender: the frame's end flushed everything (patch_order.py) */''')
open(path, 'w', newline='\n').write(s)
print('ok')
