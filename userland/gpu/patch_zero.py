"""lavender: glzero - a texture made with no pixels is cleared to transparent black, as on iOS (eagl.c, glzero=0: off).

From the user's first lavender project (eagl glzero, 125fe46). CoreAnimation's blurs draw a picture
smaller into a corner of a scratch texture and then sample a little past what they drew; on iOS a new
empty texture is all zeros. Mesa hands out memory that held other pictures (its buffer cache, the GPU
pool), and the blur behind the notification shade, Spotlight, Control Center showed blocks of old
pictures: the user saw the screen flicker while pulling the shade down (2026-11-27). Now a texture made
with glTexImage2D(..., NULL) is cleared to transparent black at once.

usage: python patch_zero.py EAGL_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	} arrays[8];                    /* the vertex arrays, as given */
	bool in_frame;
''', '''	} arrays[8];                    /* the vertex arrays, as given */
	GLuint zero_fb;                 /* lavender: a framebuffer to clear a new empty texture with (patch_zero.py) */
	bool in_frame;
''')

sub('''static void
my_glTexImage2D(void *context, GLenum target, GLint level, GLint internal, GLsizei width, GLsizei height, GLint border,
    GLenum format, GLenum type, const void *pixels)
{''', '''/*
 * lavender: glzero (patch_zero.py) - a texture made with no pixels is all zeros on iOS; CoreAnimation's
 * blurs sample a little past what they draw into scratch textures. Cleared to transparent black.
 */
#define LV_GL_FRAMEBUFFER_BINDING       0x8ca6
#define LV_GL_COLOR_WRITEMASK           0x0c23
static int zero_on = 1;
static unsigned zero_count;

static void
zero_texture(struct eagl *e, GLuint texture)
{
	GLint was = 0;
	GLfloat colour[4];
	GLboolean mask[4], boxed;

	if (texture == 0) {
		return;
	}
	glGetIntegerv(LV_GL_FRAMEBUFFER_BINDING, &was);
	if (e->zero_fb == 0) {
		glGenFramebuffers(1, &e->zero_fb);
	}
	glBindFramebuffer(GL_FRAMEBUFFER, e->zero_fb);
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
	if (glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE) {
		boxed = glIsEnabled(GL_SCISSOR_TEST);
		glGetFloatv(GL_COLOR_CLEAR_VALUE, colour);
		glGetBooleanv(LV_GL_COLOR_WRITEMASK, mask);
		if (boxed) {
			glDisable(GL_SCISSOR_TEST);
		}
		glColorMask(1, 1, 1, 1);
		glClearColor(0, 0, 0, 0);
		glClear(GL_COLOR_BUFFER_BIT);
		glClearColor(colour[0], colour[1], colour[2], colour[3]);
		glColorMask(mask[0], mask[1], mask[2], mask[3]);
		if (boxed) {
			glEnable(GL_SCISSOR_TEST);
		}
		zero_count++;
	}
	glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, 0, 0);
	glBindFramebuffer(GL_FRAMEBUFFER, (GLuint)was);
}

static void
my_glTexImage2D(void *context, GLenum target, GLint level, GLint internal, GLsizei width, GLsizei height, GLint border,
    GLenum format, GLenum type, const void *pixels)
{''')
sub('''	glTexImage2D(target, level, (GLint)internal_format((GLenum)internal, format), width, height, border, format, type, pixels);
	if (began != 0 && now_us() - began >= slow_calls_us) {''', '''	glTexImage2D(target, level, (GLint)internal_format((GLenum)internal, format), width, height, border, format, type, pixels);
	if (zero_on && pixels == NULL && target == GL_TEXTURE_2D && level == 0 && width > 0 && height > 0 && e->unit < 8) {
		zero_texture(e, e->bound[e->unit]);     /* lavender: patch_zero.py */
	}
	if (began != 0 && now_us() - began >= slow_calls_us) {''')
sub('''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
''', '''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
		zero_on = strstr(arguments, "glzero=0") == NULL;        /* lavender: patch_zero.py */
''')
open(path, 'w', newline='\n').write(s)
print('ok')
