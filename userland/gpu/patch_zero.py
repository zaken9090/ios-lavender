"""lavender: glzero - a texture made with no pixels gets zeros, as on iOS (eagl.c, glzero=0: off).

From the user's first lavender project (eagl glzero, 125fe46). CoreAnimation's blurs draw a picture
smaller into a corner of a scratch texture and then sample a little past what they drew; on iOS a new
empty texture is all zeros. Mesa hands out memory that held other pictures (its buffer cache, the GPU
pool), and the blur behind the notification shade, Spotlight, Control Center showed blocks of old
pictures: the user saw the screen flicker while pulling the shade down (2026-11-27).

The first project cleared the new texture through a framebuffer of its own (glClear); here that gave GPU
hangs (run z1, 2026-11-27). So the texture is made with a buffer of zeros instead of NULL: an ordinary
upload, Mesa's most used path. Up to 4096 x 4096 and 64 MB; the buffer grows as needed and is kept.

usage: python patch_zero.py EAGL_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static void
my_glTexImage2D(void *context, GLenum target, GLint level, GLint internal, GLsizei width, GLsizei height, GLint border,
    GLenum format, GLenum type, const void *pixels)
{''', '''/*
 * lavender: glzero (patch_zero.py) - a texture made with no pixels is all zeros on iOS; CoreAnimation's
 * blurs sample a little past what they draw into scratch textures. Given zeros to upload instead of NULL.
 */
#define LV_GL_UNPACK_ROW_LENGTH         0x0cf2
#define LV_GL_UNPACK_ALIGNMENT          0x0cf5
#define LV_GL_UNPACK_SKIP_ROWS          0x0cf3
#define LV_GL_UNPACK_SKIP_PIXELS        0x0cf4
#define LV_GL_PIXEL_UNPACK_BUFFER_BINDING 0x88ef
static int zero_on = 1;
static unsigned zero_count;
static void *zero_buf;
static size_t zero_len;

static const void *
zero_pixels(GLsizei width, GLsizei height, GLenum format, GLenum type)
{
	GLint row = 0, align = 4, skip_rows = 0, skip_pixels = 0, pbo = 0;

	if (width <= 0 || height <= 0 || width > 4096 || height > 4096) {
		return NULL;
	}
	glGetIntegerv(LV_GL_PIXEL_UNPACK_BUFFER_BINDING, &pbo);
	if (pbo != 0) {
		return NULL;                    /* (pixels would be an offset into a buffer object) */
	}
	glGetIntegerv(LV_GL_UNPACK_ROW_LENGTH, &row);
	glGetIntegerv(LV_GL_UNPACK_ALIGNMENT, &align);
	glGetIntegerv(LV_GL_UNPACK_SKIP_ROWS, &skip_rows);
	glGetIntegerv(LV_GL_UNPACK_SKIP_PIXELS, &skip_pixels);
	size_t bpp = bytes_a_pixel(format, type);
	size_t pitch = (size_t)(row > width ? row : width) * bpp;
	pitch = (pitch + (size_t)(align > 0 ? align : 1) - 1) & ~((size_t)(align > 0 ? align : 1) - 1);
	size_t need = pitch * (size_t)(height + skip_rows) + (size_t)skip_pixels * bpp + 64;
	if (need > (64u << 20)) {
		return NULL;                    /* (bigger than any blur scratch: left as it is) */
	}
	if (need > zero_len) {
		void *grown = calloc(1, need);
		if (grown == NULL) {
			return NULL;
		}
		free(zero_buf);
		zero_buf = grown;
		zero_len = need;
	}
	zero_count++;
	return zero_buf;
}

static void
my_glTexImage2D(void *context, GLenum target, GLint level, GLint internal, GLsizei width, GLsizei height, GLint border,
    GLenum format, GLenum type, const void *pixels)
{''')
sub('''	uint64_t began = slow_calls_us != 0 ? now_us() : 0;
	glTexImage2D(target, level, (GLint)internal_format((GLenum)internal, format), width, height, border, format, type, pixels);
	if (began != 0 && now_us() - began >= slow_calls_us) {''', '''	uint64_t began = slow_calls_us != 0 ? now_us() : 0;
	if (zero_on && pixels == NULL && target == GL_TEXTURE_2D && level == 0) {
		pixels = zero_pixels(width, height, format, type);      /* lavender: patch_zero.py */
	}
	glTexImage2D(target, level, (GLint)internal_format((GLenum)internal, format), width, height, border, format, type, pixels);
	if (began != 0 && now_us() - began >= slow_calls_us) {''')
sub('''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
''', '''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
		zero_on = strstr(arguments, "glzero=0") == NULL;        /* lavender: patch_zero.py */
''')
open(path, 'w', newline='\n').write(s)
print('ok')
