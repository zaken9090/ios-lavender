"""lavender: the display's two surfaces are drawn on in one texture, the canvas (eagl.c, boot-arg glcanvas=0: off).

CoreAnimation draws only what changed since the last frame and takes turns between two display
surfaces, so before every display frame patch_preserve.py copied the last frame (the other
surface's texture) into the texture about to be drawn on: a whole screen, 2.74 M pixels read and
written, of the ~34 M a home frame passes. The frame is shown from a scanout surface of our own
anyway (patch_scanout.py): nothing needs the two textures to be apart.

Now, once two surfaces have taken turns 8 times in a row, every texture CoreAnimation has made of
either of them stands for the canvas: glBindTexture and glFramebufferTexture2D (all of them in this
file, CoreAnimation's and ours) are given the canvas in place of such a name. The canvas always
holds the last frame, so the copy is left out. The bookkeeping (image_of, e->colour, e->bound) goes
on with CoreAnimation's names; where the library hands a name back (the framebuffer's attachment,
the texture bound), the canvas is turned back into the name that was given.

A full-size target that is not one of the two (a snapshot) is drawn as before, into its own texture,
with the copy from the canvas.

usage: python patch_canvas.py EAGL_C   (after patch_noastc.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()
NL = chr(92) + 'n'


def sub(old, new, count=1):
    global s
    assert s.count(old) == count, (old[:70], s.count(old))
    s = s.replace(old, new)


# ---- state, the name map and the two macros (after the declarations of the library's functions)
sub('''static __thread struct eagl *current;
''', '''static __thread struct eagl *current;

/*
 * lavender (patch_canvas.py): the canvas - one texture for both of the display's surfaces. A name in
 * canvas_names (CoreAnimation's textures of those surfaces) is the canvas in every glBindTexture and
 * glFramebufferTexture2D of this file, in the context that owns it.
 */
static int canvas_on = 1;               /* boot-arg glcanvas=0 */
static GLuint canvas_tex;
static struct eagl *canvas_e;
static GLsizei canvas_w, canvas_h;
static uint32_t canvas_set[2], canvas_cand[2], canvas_prev;
static unsigned canvas_streak;
static GLuint canvas_names[16];
static GLuint canvas_fb[16], canvas_fb_name[16];        /* framebuffer -> the name attached as the canvas */
static unsigned canvas_fb_next;
static unsigned canvas_frames, canvas_others;

static GLuint
canvas_map(GLuint name)
{
	if (canvas_tex != 0 && name != 0 && current == canvas_e) {
		for (int i = 0; i < 16; i++) {
			if (canvas_names[i] == name) {
				return canvas_tex;
			}
		}
	}
	return name;
}

#define glBindTexture(t, n)                     (glBindTexture)((t), canvas_map(n))
#define glFramebufferTexture2D(t, a, k, n, l)   (glFramebufferTexture2D)((t), (a), (k), canvas_map(n), (l))

static bool
canvas_has(GLuint name)
{
	for (int i = 0; i < 16 && name != 0; i++) {
		if (canvas_names[i] == name) {
			return true;
		}
	}
	return false;
}

static void
canvas_drop(GLuint name)
{
	for (int i = 0; i < 16 && name != 0; i++) {
		if (canvas_names[i] == name) {
			canvas_names[i] = 0;
		}
	}
}

static void
canvas_add(GLuint name)
{
	if (name == 0 || canvas_has(name)) {
		return;
	}
	for (int i = 0; i < 16; i++) {
		if (canvas_names[i] == 0) {
			canvas_names[i] = name;
			return;
		}
	}
	canvas_names[canvas_fb_next % 16] = name;       /* (full: one of the old names goes) */
}

/* glFramebufferTexture2D(CoreAnimation's name) into `framebuffer`: kept, to give the name back */
static void
canvas_note_fb(GLuint framebuffer, GLuint name)
{
	if (canvas_tex == 0 || framebuffer == 0 || canvas_map(name) != canvas_tex) {
		return;
	}
	for (int i = 0; i < 16; i++) {
		if (canvas_fb[i] == framebuffer) {
			canvas_fb_name[i] = name;
			return;
		}
	}
	canvas_fb[canvas_fb_next % 16] = framebuffer;
	canvas_fb_name[canvas_fb_next % 16] = name;
	canvas_fb_next++;
}

/* The library says `name` is attached to `framebuffer`: CoreAnimation's name, if it is the canvas */
static GLuint
canvas_unmap_fb(GLuint framebuffer, GLuint name)
{
	if (canvas_tex == 0 || name != canvas_tex) {
		return name;
	}
	for (int i = 0; i < 16; i++) {
		if (canvas_fb[i] == framebuffer && canvas_fb_name[i] != 0) {
			return canvas_fb_name[i];
		}
	}
	return name;
}
''')

# ---- boot-arg
sub('''		scan_on = strstr(arguments, "glscan=0") == NULL;''', '''		scan_on = strstr(arguments, "glscan=0") == NULL;
		canvas_on = strstr(arguments, "glcanvas=0") == NULL;    /* lavender: patch_canvas.py */''')

# ---- a texture that is deleted is no name of the canvas any more (the name comes back for another)
sub('''	struct image *image = image_of(e, texture);

	if (image != NULL) {
		if (image->mirror != 0) {''', '''	struct image *image = image_of(e, texture);

	canvas_drop(texture);                   /* lavender: patch_canvas.py */
	if (image != NULL) {
		if (image->mirror != 0) {''')

# ---- the frame's start: in the canvas, nothing to copy
sub('''/*
 * lavender: CoreAnimation draws only the damage since the frame before and leaves the rest of the
 * surface as it is, but the display's two surfaces take turns: the rest is two frames old.''', '''/*
 * lavender (patch_canvas.py): a display frame is about to be drawn into `image`. Two surfaces that
 * have taken turns 8 times in a row become the canvas's (its first content: the last frame); true:
 * `image` is one of them, and the canvas holds the last frame already.
 */
static void
canvas_blit(struct eagl *e, GLuint from, GLuint to, GLsizei w, GLsizei h)
{
	GLint read = 0, draw = 0;
	GLboolean boxed = glIsEnabled(GL_SCISSOR_TEST);

	glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &read);
	glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &draw);
	if (e->reader == 0) {
		glGenFramebuffers(1, &e->reader);
	}
	if (e->writer == 0) {
		glGenFramebuffers(1, &e->writer);
	}
	glDisable(GL_SCISSOR_TEST);
	glBindFramebuffer(GL_READ_FRAMEBUFFER, e->reader);
	(glFramebufferTexture2D)(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, from, 0);
	glBindFramebuffer(GL_DRAW_FRAMEBUFFER, e->writer);
	(glFramebufferTexture2D)(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, to, 0);
	glBlitFramebuffer(0, 0, w, h, 0, 0, w, h, GL_COLOR_BUFFER_BIT, GL_NEAREST);
	glBindFramebuffer(GL_READ_FRAMEBUFFER, (GLuint)read);
	glBindFramebuffer(GL_DRAW_FRAMEBUFFER, (GLuint)draw);
	if (boxed) {
		glEnable(GL_SCISSOR_TEST);
	}
}

static bool
canvas_frame(struct eagl *e, struct image *image)
{
	static uint64_t said;
	uint32_t id;
	uint64_t now = now_us();

	if (!canvas_on || !preserve_frames || image->surface == NULL || image->mirror == 0) {
		return false;
	}
	id = IOSurfaceGetID(image->surface);
	if (canvas_prev != 0 && id != canvas_prev) {
		if ((canvas_cand[0] == canvas_prev && canvas_cand[1] == id) || (canvas_cand[0] == id && canvas_cand[1] == canvas_prev)) {
			canvas_streak++;
		} else {
			canvas_cand[0] = canvas_prev;
			canvas_cand[1] = id;
			canvas_streak = 1;
		}
	}
	canvas_prev = id;
	if (canvas_streak >= 8 && !((canvas_set[0] == canvas_cand[0] && canvas_set[1] == canvas_cand[1]) ||
	    (canvas_set[0] == canvas_cand[1] && canvas_set[1] == canvas_cand[0]))) {
		struct image *last = e->last_display != 0 ? image_of(e, e->last_display) : NULL;

		if (canvas_tex == 0) {
			GLint bound = 0;

			glGetIntegerv(GL_TEXTURE_BINDING_2D, &bound);
			glGenTextures(1, &canvas_tex);
			(glBindTexture)(GL_TEXTURE_2D, canvas_tex);
			glTexImage2D(GL_TEXTURE_2D, 0, GL_BGRA, image->width, image->height, 0, GL_BGRA, GL_UNSIGNED_BYTE, NULL);
			glTexParameteri(GL_TEXTURE_2D, 0x2801, 0x2601);         /* min filter: linear */
			glTexParameteri(GL_TEXTURE_2D, 0x2800, 0x2601);         /* mag filter: linear */
			glTexParameteri(GL_TEXTURE_2D, 0x2802, 0x812f);         /* clamp to edge */
			glTexParameteri(GL_TEXTURE_2D, 0x2803, 0x812f);
			(glBindTexture)(GL_TEXTURE_2D, (GLuint)bound);
			canvas_w = image->width;
			canvas_h = image->height;
			canvas_e = e;
		}
		if (canvas_e != e || canvas_w != image->width || canvas_h != image->height) {
			canvas_streak = 0;
			return false;
		}
		/* the last frame into the canvas, unless it is there already */
		if (last != NULL && last->painted && !canvas_has(last->texture) && last->width == canvas_w && last->height == canvas_h) {
			canvas_blit(e, last->texture, canvas_tex, canvas_w, canvas_h);
		}
		memset(canvas_names, 0, sizeof(canvas_names));
		memset(canvas_fb, 0, sizeof(canvas_fb));
		canvas_set[0] = canvas_cand[0];
		canvas_set[1] = canvas_cand[1];
		for (unsigned i = 0; i < e->image_count; i++) {
			struct image *other = &e->images[i];

			if (other->target && other->surface != NULL && other->width == canvas_w && other->height == canvas_h &&
			    (IOSurfaceGetID(other->surface) == canvas_set[0] || IOSurfaceGetID(other->surface) == canvas_set[1])) {
				canvas_add(other->texture);
			}
		}
		say("redwood-gl: canvas: IOSurfaces %u and %u are drawn in one texture (glcanvas=0: apart)\\n", canvas_set[0], canvas_set[1]);
	}
	if (canvas_tex == 0 || canvas_e != e || (id != canvas_set[0] && id != canvas_set[1]) || !canvas_has(image->texture)) {
		if (canvas_tex != 0 && canvas_e == e) {
			canvas_others++;
		}
		return false;
	}
	/* the framebuffer being drawn into may have been given the name before it was the canvas's */
	{
		GLint kind = 0, name = 0;

		glGetFramebufferAttachmentParameteriv(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_FRAMEBUFFER_ATTACHMENT_OBJECT_TYPE, &kind);
		if (kind == GL_TEXTURE) {
			glGetFramebufferAttachmentParameteriv(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_FRAMEBUFFER_ATTACHMENT_OBJECT_NAME, &name);
			if ((GLuint)name == image->texture) {
				(glFramebufferTexture2D)(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, canvas_tex, 0);
				canvas_note_fb(e->framebuffer, image->texture);
			}
		}
	}
	canvas_frames++;
	if (now - said >= 1000000) {
		if (said != 0 && canvas_frames + canvas_others > 2) {
			say("redwood-gl: canvas: %u display frames drawn on it (no copy), %u full-size frames elsewhere\\n", canvas_frames, canvas_others);
		}
		said = now;
		canvas_frames = canvas_others = 0;
	}
	return true;
}

/*
 * lavender: CoreAnimation draws only the damage since the frame before and leaves the rest of the
 * surface as it is, but the display's two surfaces take turns: the rest is two frames old.''')

sub('''	if (preserve_frames && e->last_display != 0 && e->last_display != image->texture &&
	    (last = image_of(e, e->last_display)) != NULL && last->target && last->painted &&''', '''	if (canvas_frame(e, image)) {
		e->last_display = image->texture;       /* lavender: patch_canvas.py - the canvas has the last frame */
		return;
	}
	if (preserve_frames && e->last_display != 0 && e->last_display != image->texture &&
	    (last = image_of(e, e->last_display)) != NULL && last->target && last->painted &&''')

# ---- names the library hands back
sub('''			e->colour = (GLuint)name;''', '''			e->colour = canvas_unmap_fb(framebuffer, (GLuint)name);       /* lavender: patch_canvas.py */''')
sub('''	if (attachment == GL_COLOR_ATTACHMENT0 && target != GL_READ_FRAMEBUFFER) {
		e->colour = texture;
	}''', '''	if (attachment == GL_COLOR_ATTACHMENT0 && target != GL_READ_FRAMEBUFFER) {
		e->colour = texture;
		canvas_note_fb(e->framebuffer, texture);        /* lavender: patch_canvas.py */
	}''')

# ---- -attachImage: the surface's memory goes into CoreAnimation's own texture, then it may be the canvas's
sub('''	glGetIntegerv(GL_TEXTURE_BINDING_2D, &texture);
	pixels = IOSurfaceGetPixelFormat(surface);''', '''	glGetIntegerv(GL_TEXTURE_BINDING_2D, &texture);
	if (canvas_tex != 0 && (GLuint)texture == canvas_tex && e->unit < 8 && e->bound[e->unit] != 0) {
		/* lavender (patch_canvas.py): a name of the canvas attached anew - its own texture again */
		texture = (GLint)e->bound[e->unit];
		canvas_drop((GLuint)texture);
		(glBindTexture)(GL_TEXTURE_2D, (GLuint)texture);
	}
	pixels = IOSurfaceGetPixelFormat(surface);''')
sub('''	e->attaching += now_us() - began;
	if (attached++ < 24) {''', '''	e->attaching += now_us() - began;
	if (canvas_tex != 0 && canvas_e == e && image->width == canvas_w && image->height == canvas_h &&
	    (IOSurfaceGetID(surface) == canvas_set[0] || IOSurfaceGetID(surface) == canvas_set[1])) {
		canvas_add(image->texture);             /* lavender (patch_canvas.py): one of the two surfaces */
		(glBindTexture)(GL_TEXTURE_2D, canvas_tex);
	}
	if (attached++ < 24) {''')

# ---- the copy out is of the whole frame: glBlitFramebuffer obeys the scissor test, and at a frame's end
#      CoreAnimation may have left it on with the box of its last draw (16 of 159 frames, run ag2)
sub('''		glBlitFramebuffer(0, 0, image->width, image->height, 0, image->invert ? image->height : 0, image->width,
		    image->invert ? 0 : image->height, GL_COLOR_BUFFER_BIT, GL_NEAREST);''', '''		{
			GLboolean boxed = glIsEnabled(GL_SCISSOR_TEST);         /* lavender: patch_canvas.py */

			glDisable(GL_SCISSOR_TEST);
			glBlitFramebuffer(0, 0, image->width, image->height, 0, image->invert ? image->height : 0, image->width,
			    image->invert ? 0 : image->height, GL_COLOR_BUFFER_BIT, GL_NEAREST);
			if (boxed) {
				glEnable(GL_SCISSOR_TEST);
			}
		}''')

# ---- the generated table passes arguments on by the library's names
sub('''#define EAGL_GEN_TABLE
#include "eagl_gen.h"''', '''#undef glBindTexture                    /* lavender: patch_canvas.py */
#undef glFramebufferTexture2D
#define EAGL_GEN_TABLE
#include "eagl_gen.h"''')

open(path, 'w', newline='\n').write(s)
print('ok')
