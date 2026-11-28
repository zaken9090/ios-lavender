"""lavender: boot-arg glsharewhy=N - why the first N IOSurfaces were copied, not shared with the GPU (eagl.c).
A home-screen run (pf7) had 8 IOSurfaces as the textures' own memory and 139 copied; every copied one is
added up each frame (surface_changed, 15 % of backboardd) and filled again when it changes. Line:
"redwood-gl: copied S 'FMT' WxH bpr B (texture WxH, format F type T, invert I alpha-first A plane P): REASON"
with REASON the first condition of surface_shared() that failed ("library" = Mesa refused the EGL image).
Diagnostic only, no behaviour change.

usage: python patch_sharewhy.py EAGL_C   (after patch_canvas.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static bool
surface_shared(struct eagl *e, struct image *image)
{
	IOSurfaceRef surface = image->surface;

	if (!share_surfaces ||''', '''static int share_why;                   /* lavender: boot-arg glsharewhy=N (patch_sharewhy.py) */

static void
share_why_say(struct image *image, const char *why)
{
	IOSurfaceRef surface = image->surface;
	uint32_t f = IOSurfaceGetPixelFormat(surface);

	if (share_why <= 0) {
		return;
	}
	share_why--;
	say("redwood-gl: copied %u '%c%c%c%c' %zux%zu bpr %zu (texture %dx%d, format %#x type %#x, invert %d alpha-first %d "
	    "plane %d): %s\\n", IOSurfaceGetID(surface), (char)(f >> 24), (char)(f >> 16), (char)(f >> 8), (char)f,
	    IOSurfaceGetWidth(surface), IOSurfaceGetHeight(surface), IOSurfaceGetBytesPerRow(surface), image->width,
	    image->height, image->format, image->type, image->invert, image->alpha_first, image->plane, why);
}

static bool
surface_shared(struct eagl *e, struct image *image)
{
	IOSurfaceRef surface = image->surface;

	if (share_why > 0) {
		const char *why = !share_surfaces ? "glcopy" : image->invert ? "invert" : image->alpha_first ? "alpha-first" :
		    image->format != GL_BGRA ? "format" : image->type != GL_UNSIGNED_BYTE ? "type" : image->plane != 0 ? "plane" :
		    (size_t)image->width != IOSurfaceGetWidth(surface) || (size_t)image->height != IOSurfaceGetHeight(surface) ?
		    "size" : NULL;
		if (why != NULL) {
			share_why_say(image, why);
		}
	}
	if (!share_surfaces ||''')
sub('''	    !redwood_gl_surface_texture(e->gl, IOSurfaceGetID(surface))) {
		e->refused++;
		return false;
	}
	image->shared = true;''', '''	    !redwood_gl_surface_texture(e->gl, IOSurfaceGetID(surface))) {
		e->refused++;
		if (share_surfaces && !image->invert && !image->alpha_first && image->format == GL_BGRA &&
		    image->type == GL_UNSIGNED_BYTE && image->plane == 0 && (size_t)image->width == IOSurfaceGetWidth(surface) &&
		    (size_t)image->height == IOSurfaceGetHeight(surface)) {
			share_why_say(image, "library");
		}
		return false;
	}
	image->shared = true;''')
sub('''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
''', '''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
		if ((argument = strstr(arguments, "glsharewhy=")) != NULL) {     /* lavender: patch_sharewhy.py */
			share_why = atoi(argument + 11);
		}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
