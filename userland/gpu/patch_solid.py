"""lavender: glsolid - whole-viewport quads of one colour skipped or drawn as a clear (eagl.c, glsolid=0: off).

From the user's first lavender project (eagl glsolid, 44ae361: home 8.4 -> 10.7 fps there). CoreAnimation
draws whole-screen quads of one colour with its colour-only program (only a matrix uniform), 4-5 a frame
on the lock screen and in Settings, 2.7 Mpx each, read and written by the GPU in sysmem:
- transparent black over premultiplied blending changes nothing: skipped;
- opaque (alpha 1 with src-over blending, or blending off): exactly a clear, which writes without reading.
The picture is the same pixel for pixel. Not done (drawn as they come) with the stencil or depth test on
(glClear ignores them), or while a clear of eagl's own is still pending (e->unclear).

usage: python patch_solid.py EAGL_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


SOLID = r'''/*
 * lavender: glsolid (patch_solid.py) - CoreAnimation's whole-viewport quads of one colour from its
 * colour-only program: transparent black over premultiplied blending skipped, opaque ones as glClear.
 */
#define GL_ACTIVE_UNIFORMS              0x8b86
#define GL_FLOAT_MAT4                   0x8b5c
#define LV_GL_SRC_ALPHA                 0x0302
static int solid_on = 1;
static unsigned solid_skipped, solid_cleared;
static signed char colour_only[2048];          /* per program: 0 not looked at, 1 colour only, -1 not */

static bool
program_colour_only(GLuint program)
{
	if (program == 0 || program >= sizeof(colour_only)) {
		return false;
	}
	if (colour_only[program] == 0) {
		GLint uniforms = 0;
		signed char verdict = 1;

		glGetProgramiv(program, GL_ACTIVE_UNIFORMS, &uniforms);
		for (GLint i = 0; i < uniforms; i++) {
			GLint size = 0;
			GLenum type = 0;
			char name[64];

			glGetActiveUniform(program, (GLuint)i, sizeof(name), NULL, &size, &type, name);
			if (type != GL_FLOAT_MAT4) {
				verdict = -1;
			}
		}
		colour_only[program] = uniforms > 0 ? verdict : -1;
	}
	return colour_only[program] > 0;
}

/* component c of vertex v of array a as a float (float, half float or normalized byte) */
static bool
solid_value(struct eagl *e, unsigned a, unsigned vertex, int c, float *value)
{
	const uint8_t *at = e->arrays[a].pointer;
	GLint size = e->arrays[a].size;
	GLenum type = e->arrays[a].type;
	unsigned bytes = type == GL_FLOAT ? 4 : type == GL_HALF_FLOAT ? 2 : type == GL_UNSIGNED_BYTE ? 1 : 0;

	if (at == NULL || bytes == 0 || c >= size) {
		return false;
	}
	at += (size_t)vertex * (size_t)(e->arrays[a].stride ? e->arrays[a].stride : size * (GLint)bytes) + (size_t)c * bytes;
	if (type == GL_FLOAT) {
		memcpy(value, at, 4);
	} else if (type == GL_HALF_FLOAT) {
		uint16_t h;
		memcpy(&h, at, 2);
		*value = half_float(h);
	} else {
		*value = (float)at[0] / 255;
	}
	return true;
}

/* 1: skipped, 2: drawn as a clear, 0: draw it. 6 indices covering the whole viewport, 4 corners of one colour. */
static int
solid_draw(struct eagl *e, GLenum mode, GLsizei count, GLenum type, const void *indices)
{
	GLint viewport[4];
	float colour[4] = { 0, 0, 0, 0 }, x0 = 1e9f, y0 = 1e9f, x1 = -1e9f, y1 = -1e9f;

	if (!solid_on || mode != GL_TRIANGLES || count != 6 || type != GL_UNSIGNED_SHORT || indices == NULL ||
	    e->unclear != 0 || e->arrays[0].type != GL_FLOAT || e->arrays[0].size < 2 || e->arrays[1].size < 4 ||
	    !program_colour_only(e->program) || glIsEnabled(GL_STENCIL_TEST) || glIsEnabled(GL_DEPTH_TEST)) {
		return 0;
	}
	for (int i = 0; i < 6; i++) {
		unsigned v = ((const uint16_t *)indices)[i];
		float x, y, c[4];

		if (!solid_value(e, 0, v, 0, &x) || !solid_value(e, 0, v, 1, &y)) {
			return 0;
		}
		for (int k = 0; k < 4; k++) {
			if (!solid_value(e, 1, v, k, &c[k])) {
				return 0;
			}
			if (i == 0) {
				colour[k] = c[k];
			} else if (c[k] != colour[k]) {
				return 0;
			}
		}
		x0 = x < x0 ? x : x0;
		x1 = x > x1 ? x : x1;
		y0 = y < y0 ? y : y0;
		y1 = y > y1 ? y : y1;
	}
	glGetIntegerv(GL_VIEWPORT, viewport);
	if (viewport[0] != 0 || viewport[1] != 0 || x0 > 0 || y0 > 0 || x1 < (float)viewport[2] || y1 < (float)viewport[3]) {
		return 0;
	}
	bool blend = glIsEnabled(GL_BLEND);
	GLint src = GL_ONE, dst = 0, srca = GL_ONE, dsta = 0;
	if (blend) {
		glGetIntegerv(GL_BLEND_SRC_RGB, &src);
		glGetIntegerv(GL_BLEND_DST_RGB, &dst);
		glGetIntegerv(GL_BLEND_SRC_ALPHA, &srca);
		glGetIntegerv(GL_BLEND_DST_ALPHA, &dsta);
	}
	bool over = (src == GL_ONE || src == LV_GL_SRC_ALPHA) && dst == GL_ONE_MINUS_SRC_ALPHA &&
	    (srca == GL_ONE || srca == LV_GL_SRC_ALPHA) && dsta == GL_ONE_MINUS_SRC_ALPHA;
	if (blend && over && colour[0] == 0 && colour[1] == 0 && colour[2] == 0 && colour[3] == 0) {
		solid_skipped++;
		return 1;
	}
	if (!blend || (over && colour[3] == 1)) {
		GLfloat was[4];

		glGetFloatv(GL_COLOR_CLEAR_VALUE, was);
		glClearColor(colour[0], colour[1], colour[2], colour[3]);
		glClear(GL_COLOR_BUFFER_BIT);
		glClearColor(was[0], was[1], was[2], was[3]);
		solid_cleared++;
		return 2;
	}
	return 0;
}

static void
my_glDrawElements(void *context, GLenum mode, GLsizei count, GLenum type, const void *indices)
{'''

sub('''static void
my_glDrawElements(void *context, GLenum mode, GLsizei count, GLenum type, const void *indices)
{''', SOLID)
sub('''	if (trace_placing) {
		trace_placed_draw(e, mode, type, indices, 0, count);
	}
	if (group_draw_begin(e, enabled)) {
		glDrawElements(mode, count, type, indices);
		group_draw_end(e, enabled);''', '''	if (trace_placing) {
		trace_placed_draw(e, mode, type, indices, 0, count);
	}
	int solid = solid_draw(e, mode, count, type, indices);       /* lavender: patch_solid.py */
	if (solid != 0) {
		if (eagl_tracing) {
			eagl_trace("    (glsolid: %s)\\n", solid == 1 ? "skipped, changes nothing" : "drawn as a clear");
		}
	} else if (group_draw_begin(e, enabled)) {
		glDrawElements(mode, count, type, indices);
		group_draw_end(e, enabled);''')
sub('''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
''', '''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
		solid_on = strstr(arguments, "glsolid=0") == NULL;      /* lavender: patch_solid.py */
''')
open(path, 'w', newline='\n').write(s)
print('ok')
