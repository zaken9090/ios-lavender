"""lavender: a scanout surface gets only what changed since its own last frame (eagl.c, boot-arg glscandmg=0: whole).

With the canvas (patch_canvas.py) every display frame is drawn into one texture, and at its end the
whole of it was copied into one of four scanout surfaces (patch_scanout.py): a screen, 2.74 M pixels
read and written, for a frame that may have changed a clock's digits. A scanout surface holds the
frame it was last given, so it lacks only what the frames since then drew: the boxes CoreAnimation
drew into the canvas (its scissor box at every draw and clear; a draw with the scissor off: all of
it). Those are kept per frame (the last 8), and the copy takes their union - nothing when no frame
since drew. A surface that has not been given a frame of the canvas, or was given it more than 8
frames ago, gets all of it.

usage: python patch_scandamage.py EAGL_C   (after patch_canvas.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()
NL = chr(92) + 'n'


def sub(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static unsigned canvas_frames, canvas_others;
''', '''static unsigned canvas_frames, canvas_others;

/*
 * lavender (patch_scandamage.py): the boxes drawn into the canvas, per frame. dmg_now: this frame's so
 * far; dmg_hist[seq % 8]: frame seq's (all: everything); scan_seq[i]: the frame scanout surface i holds
 * (0: none of the canvas).
 */
static int scandmg_on = 1;              /* boot-arg glscandmg=0 */
struct dmg_box {
	bool all;
	int box[4];                     /* x0 y0 x1 y1; empty when x1 <= x0 */
};
static struct dmg_box dmg_now, dmg_hist[8];
static unsigned dmg_seq;
static unsigned scan_seq[4];
static uint64_t dmg_pixels, dmg_full_pixels;
static unsigned dmg_empty;

static void
dmg_union(struct dmg_box *d, const struct dmg_box *with)
{
	if (d->all || with->all) {
		d->all = true;
		return;
	}
	if (with->box[2] <= with->box[0] || with->box[3] <= with->box[1]) {
		return;
	}
	if (d->box[2] <= d->box[0] || d->box[3] <= d->box[1]) {
		memcpy(d->box, with->box, sizeof(d->box));
		return;
	}
	d->box[0] = with->box[0] < d->box[0] ? with->box[0] : d->box[0];
	d->box[1] = with->box[1] < d->box[1] ? with->box[1] : d->box[1];
	d->box[2] = with->box[2] > d->box[2] ? with->box[2] : d->box[2];
	d->box[3] = with->box[3] > d->box[3] ? with->box[3] : d->box[3];
}

static void
dmg_forget_scans(void)
{
	memset(scan_seq, 0, sizeof(scan_seq));
	dmg_now.all = true;
}
''')

sub('''		canvas_on = strstr(arguments, "glcanvas=0") == NULL;    /* lavender: patch_canvas.py */''',
    '''		canvas_on = strstr(arguments, "glcanvas=0") == NULL;    /* lavender: patch_canvas.py */
		scandmg_on = strstr(arguments, "glscandmg=0") == NULL;  /* lavender: patch_scandamage.py */''')

# the canvas gets new content from elsewhere: no scanout surface is up to date
sub('''			canvas_blit(e, last->texture, canvas_tex, canvas_w, canvas_h);
		}''', '''			canvas_blit(e, last->texture, canvas_tex, canvas_w, canvas_h);
		}
		dmg_forget_scans();                     /* lavender: patch_scandamage.py */''')

# a draw or clear into the canvas: its box
sub('''		image->drawn = image->painted = true;
''', '''		image->drawn = image->painted = true;
		if (scandmg_on && canvas_tex != 0 && canvas_has(image->texture) && !dmg_now.all) {
			/* lavender (patch_scandamage.py): what this draw can touch of the canvas */
			struct dmg_box d = { false, { 0, 0, 0, 0 } };

			if (!glIsEnabled(GL_SCISSOR_TEST)) {
				d.all = true;
			} else {
				GLint b[4] = { 0, 0, 0, 0 };

				glGetIntegerv(GL_SCISSOR_BOX, b);
				d.box[0] = b[0] > 0 ? b[0] : 0;
				d.box[1] = b[1] > 0 ? b[1] : 0;
				d.box[2] = b[0] + b[2] < canvas_w ? b[0] + b[2] : canvas_w;
				d.box[3] = b[1] + b[3] < canvas_h ? b[1] + b[3] : canvas_h;
			}
			dmg_union(&dmg_now, &d);
		}
''')

# the copy out: a box of the canvas, or nothing
sub('''		{
			GLuint scan = scan_pick(e, image);      /* lavender (patch_scanout.py): a surface the panel is not showing */

			glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, scan != 0 ? scan : image->mirror, 0);
		}
		glBlitFramebuffer(0, 0, image->width, image->height, 0, image->invert ? image->height : 0, image->width,
		    image->invert ? 0 : image->height, GL_COLOR_BUFFER_BIT, GL_NEAREST);''', '''		{
			GLuint scan = scan_pick(e, image);      /* lavender (patch_scanout.py): a surface the panel is not showing */
			int w = image->width, h = image->height, x0 = 0, y0 = 0, x1 = w, y1 = h;

			glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, scan != 0 ? scan : image->mirror, 0);
			if (scandmg_on && canvas_tex != 0 && canvas_has(image->texture)) {
				/* lavender (patch_scandamage.py): this frame's boxes, then what the scanout surface lacks */
				struct dmg_box need = { false, { 0, 0, 0, 0 } };
				static uint64_t said;
				uint64_t now = now_us();

				dmg_seq++;
				dmg_hist[dmg_seq % 8] = dmg_now;
				memset(&dmg_now, 0, sizeof(dmg_now));
				if (scan != 0) {
					unsigned had = scan_seq[scan_last];

					if (had == 0 || dmg_seq - had >= 8) {
						need.all = true;
					} else {
						for (unsigned q = had + 1; q <= dmg_seq; q++) {
							dmg_union(&need, &dmg_hist[q % 8]);
						}
					}
					scan_seq[scan_last] = dmg_seq;
					if (!need.all) {
						x0 = need.box[0], y0 = need.box[1], x1 = need.box[2], y1 = need.box[3];
						if (x1 <= x0 || y1 <= y0) {
							x0 = y0 = x1 = y1 = 0;
							dmg_empty++;
						}
					}
				}
				dmg_pixels += (uint64_t)(x1 - x0) * (uint64_t)(y1 - y0);
				dmg_full_pixels += (uint64_t)w * (uint64_t)h;
				if (now - said >= 1000000) {
					if (said != 0 && dmg_full_pixels != 0) {
						say("redwood-gl: scanout copies: %llu of %llu kpx (%llu %%), %u copies of nothing\\n",
						    dmg_pixels / 1000, dmg_full_pixels / 1000, dmg_pixels * 100 / dmg_full_pixels, dmg_empty);
					}
					said = now;
					dmg_pixels = dmg_full_pixels = 0;
					dmg_empty = 0;
				}
			}
			if (x1 > x0 && y1 > y0) {
				GLboolean boxed = glIsEnabled(GL_SCISSOR_TEST);

				glDisable(GL_SCISSOR_TEST);
				glBlitFramebuffer(x0, y0, x1, y1, x0, image->invert ? h - y0 : y0, x1, image->invert ? h - y1 : y1,
				    GL_COLOR_BUFFER_BIT, GL_NEAREST);
				if (boxed) {
					glEnable(GL_SCISSOR_TEST);
				}
			}
		}''')

open(path, 'w', newline='\n').write(s)
print('ok')
