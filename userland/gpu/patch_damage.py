"""lavender: a frame takes from the last one only what that one changed (eagl.c, boot-arg glpreserve=2).

patch_preserve.py copies the whole last frame into the display surface about to be drawn into, every
frame: 2.74 M pixels of the 20 M a Settings frame passes and of the 55 M of an App Library frame
(GPU counters, xnu 1164; without the copy: Settings 51.0 -> 53.7 fps, home 13.7 -> 15.6), and all of
what an idle frame does (a 60 fps status bar animation copies the screen 60 times a second).

The display's two surfaces take turns, so the one about to be drawn into differs from the last frame
only where the frames since its own turn drew: the scissor boxes CoreAnimation drew them in. Those
boxes are now gathered per surface (a union box; a draw with the scissor off, or a surface without a
history, means all of it), and the copy takes just that box - or nothing when it is empty.

When the frame's first drawing has the scissor off, CoreAnimation is drawing the whole surface anew
and nothing is copied; with the scissor on and no history, everything outside its box is.

glpreserve=2 turns this on (default still the whole copy, until the picture has been checked by eye);
glpreserve=0 is no copy at all as before. With glpreservelog=N each copy logs its rectangles.

Also counted, once a second: display frames that began in a surface the display still held in use
(drawn where the panel can show it half done). glinuse=MS waits up to MS for such a surface first.

usage: python patch_damage.py EAGL_C   (after patch_preservelog.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static int preserve_frames = 1;''', '''static int preserve_damage;             /* lavender: boot-arg glpreserve=2 - copy only what changed (patch_damage.py) */
static int preserve_frames = 1;''')
sub('''		preserve_frames = strstr(arguments, "glpreserve=0") == NULL;''',
    '''		preserve_frames = strstr(arguments, "glpreserve=0") == NULL;
		preserve_damage = strstr(arguments, "glpreserve=2") != NULL;''')

sub('''/*
 * lavender: CoreAnimation draws only the damage since the frame before and leaves the rest of the
''', '''/*
 * lavender (patch_damage.py): what a display surface lacks of the last frame - the union of the boxes
 * drawn into the display's other surfaces since its own turn. `all`: everything (no history, or a
 * draw with the scissor off). The box is x0 y0 x1 y1, empty when x1 <= x0.
 */
struct damage {
	uint32_t surface;               /* IOSurface ID; 0 = free */
	bool all;
	int box[4];
};
static struct damage damages[4];

static struct damage *
damage_slot(uint32_t surface)
{
	static unsigned next;
	struct damage *d;
	int i;

	for (i = 0; i < 4; i++) {
		if (damages[i].surface == surface) {
			return &damages[i];
		}
	}
	for (i = 0; i < 4 && damages[i].surface != 0; i++) {
	}
	d = &damages[i < 4 ? i : (int)(next++ % 4)];
	d->surface = surface;
	d->all = true;                  /* nothing is known of it yet */
	d->box[0] = d->box[1] = d->box[2] = d->box[3] = 0;
	return d;
}

/* A draw or clear is about to go into the display surface `image`: the others now lack its box. */
static void
damage_add(struct image *image)
{
	uint32_t surface = image->surface != NULL ? IOSurfaceGetID(image->surface) : 0;
	GLint box[4] = { 0, 0, 0, 0 };
	GLboolean boxed = glIsEnabled(GL_SCISSOR_TEST);
	int i, x0, y0, x1, y1;

	if (boxed) {
		glGetIntegerv(GL_SCISSOR_BOX, box);
	}
	if (surface != 0) {
		(void)damage_slot(surface);
	}
	x0 = box[0] > 0 ? box[0] : 0;
	y0 = box[1] > 0 ? box[1] : 0;
	x1 = box[0] + box[2] < image->width ? box[0] + box[2] : image->width;
	y1 = box[1] + box[3] < image->height ? box[1] + box[3] : image->height;
	for (i = 0; i < 4; i++) {
		struct damage *d = &damages[i];

		if (d->surface == 0 || (surface != 0 && d->surface == surface) || d->all) {
			continue;
		}
		if (!boxed || surface == 0) {
			d->all = true;
		} else if (x1 > x0 && y1 > y0) {
			if (d->box[2] <= d->box[0] || d->box[3] <= d->box[1]) {
				d->box[0] = x0;
				d->box[1] = y0;
				d->box[2] = x1;
				d->box[3] = y1;
			} else {
				d->box[0] = x0 < d->box[0] ? x0 : d->box[0];
				d->box[1] = y0 < d->box[1] ? y0 : d->box[1];
				d->box[2] = x1 > d->box[2] ? x1 : d->box[2];
				d->box[3] = y1 > d->box[3] ? y1 : d->box[3];
			}
		}
	}
}

/*
 * lavender: CoreAnimation draws only the damage since the frame before and leaves the rest of the
''')

# the copy: the whole surface, or the box this surface lacks, or nothing
sub('''		glBlitFramebuffer(0, 0, image->width, image->height, 0, 0, image->width, image->height,
		    GL_COLOR_BUFFER_BIT, GL_NEAREST);
		glBindFramebuffer(GL_READ_FRAMEBUFFER, (GLuint)read);''', '''		{
			struct damage *d = preserve_damage && image->surface != NULL ? damage_slot(IOSurfaceGetID(image->surface)) : NULL;
			int w = image->width, h = image->height, rect[4][4], rects = 0, i;
			GLint now[4] = { 0, 0, 0, 0 };

			if (d == NULL) {
				rect[0][0] = 0, rect[0][1] = 0, rect[0][2] = w, rect[0][3] = h;
				rects = 1;
			} else if (!boxed) {
				/* lavender (patch_damage.py): the scissor is off - CoreAnimation draws the whole surface anew */
			} else if (!d->all) {
				rect[0][0] = d->box[0], rect[0][1] = d->box[1], rect[0][2] = d->box[2], rect[0][3] = d->box[3];
				rects = 1;                      /* what the frames since its turn drew */
			} else {
				/* everything but the box about to be drawn: below, above, left, right of it */
				int x0, y0, x1, y1;

				glGetIntegerv(GL_SCISSOR_BOX, now);
				x0 = now[0] > 0 ? now[0] : 0;
				y0 = now[1] > 0 ? now[1] : 0;
				x1 = now[0] + now[2] < w ? now[0] + now[2] : w;
				y1 = now[1] + now[3] < h ? now[1] + now[3] : h;
				if (x1 <= x0 || y1 <= y0) {
					x0 = x1 = 0, y0 = y1 = 0;
				}
				rect[0][0] = 0, rect[0][1] = 0, rect[0][2] = w, rect[0][3] = y0;
				rect[1][0] = 0, rect[1][1] = y1, rect[1][2] = w, rect[1][3] = h;
				rect[2][0] = 0, rect[2][1] = y0, rect[2][2] = x0, rect[2][3] = y1;
				rect[3][0] = x1, rect[3][1] = y0, rect[3][2] = w, rect[3][3] = y1;
				rects = 4;
			}
			for (i = 0; i < rects; i++) {
				if (rect[i][2] > rect[i][0] && rect[i][3] > rect[i][1]) {
					glBlitFramebuffer(rect[i][0], rect[i][1], rect[i][2], rect[i][3], rect[i][0], rect[i][1], rect[i][2], rect[i][3],
					    GL_COLOR_BUFFER_BIT, GL_NEAREST);
				}
			}
			if (preserve_damage && preserve_log > 0) {
				say("redwood-gl: preserve %s%s: %d rects, first %d,%d to %d,%d\\n", boxed ? "boxed" : "unboxed", d != NULL && d->all ? " all" : "",
				    rects, rects ? rect[0][0] : 0, rects ? rect[0][1] : 0, rects ? rect[0][2] : 0, rects ? rect[0][3] : 0);
			}
		}
		glBindFramebuffer(GL_READ_FRAMEBUFFER, (GLuint)read);''')

# does a frame begin in a surface the display still holds? (counted; glinuse=MS waits for it to be let go)
sub('''	if (image->width < 1000 || image->height < 2000) {
		return;
	}
	if (preserve_frames && e->last_display != 0''', '''	if (image->width < 1000 || image->height < 2000) {
		return;
	}
	if (image->surface != NULL) {
		/*
		 * lavender (patch_damage.py): the display's driver keeps a surface in use until the panel has
		 * stopped showing it. A frame that begins in such a surface is drawn where it can be seen.
		 */
		static unsigned frames, busy, freed;
		static uint64_t said;
		uint64_t t0 = now_us();

		frames++;
		if (IOSurfaceIsInUse(image->surface)) {
			busy++;
			while (inuse_wait_us != 0 && now_us() - t0 < inuse_wait_us && IOSurfaceIsInUse(image->surface)) {
				usleep(250);
			}
			if (inuse_wait_us != 0 && !IOSurfaceIsInUse(image->surface)) {
				freed++;
			}
		}
		if (t0 - said >= 1000000) {
			if (said != 0 && frames > 2) {
				say("redwood-gl: %u display frames, %u began in a surface in use, %u of them let go while waiting\\n", frames, busy, freed);
			}
			said = t0;
			frames = busy = freed = 0;
		}
	}
	if (preserve_frames && e->last_display != 0''')
sub('''static int preserve_damage;''', '''static uint64_t inuse_wait_us;          /* lavender: boot-arg glinuse=MS - wait so long for a display surface in use (patch_damage.py) */
static int preserve_damage;''')
sub('''		preserve_damage = strstr(arguments, "glpreserve=2") != NULL;''', '''		preserve_damage = strstr(arguments, "glpreserve=2") != NULL;
		if (strstr(arguments, "glinuse=") != NULL) {
			inuse_wait_us = strtoull(strstr(arguments, "glinuse=") + 8, NULL, 10) * 1000;
		}''')
sub('''	e->last_display = image->texture;
}''', '''	if (preserve_damage && image->surface != NULL) {
		struct damage *d = damage_slot(IOSurfaceGetID(image->surface));        /* it has the last frame now (patch_damage.py) */

		d->all = false;
		d->box[0] = d->box[1] = d->box[2] = d->box[3] = 0;
	}
	e->last_display = image->texture;
}''')

# every draw or clear into a display surface is damage to the others
sub('''			preserve_frame(e, image);       /* lavender: the frame starts from the last one */
		}
		image->drawn = image->painted = true;''', '''			preserve_frame(e, image);       /* lavender: the frame starts from the last one */
		}
		image->drawn = image->painted = true;
		if (preserve_damage && image->width >= 1000 && image->height >= 2000) {
			damage_add(image);              /* lavender: patch_damage.py */
		}''')
open(path, 'w', newline='\n').write(s)
print('ok')
