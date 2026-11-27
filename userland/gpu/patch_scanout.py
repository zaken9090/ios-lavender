"""lavender: the finished frame is shown from a surface CoreAnimation never draws into (eagl.c, glscan=0: off).

CoreAnimation has two display surfaces and starts the next frame while the panel still shows the one
it is about to use (86 % of frames, counter of patch_damage.py). It draws a display frame into a
texture of its own, and at the frame's end that texture is copied by the GPU into the surface's memory
(blit_targets, the "mirror"): it was this copy that landed in a surface on the panel, seen half done -
the trembling bottom of the screen, torn rows. Waiting for the panel (glinuse) cures it and costs a
third of the frames (Settings 50 -> 33 fps).

Now that copy goes into one of four scanout surfaces of our own instead - one the display does not
hold (IOSurfaceIsInUse) - and that one's ID is put on CoreAnimation's surface as the IOSurface value
"lv-show". The kernel (xnu 1167) shows the named surface in place of the one swapped. No copy is
added. When all four are held, the value is cleared and the copy goes into the surface itself as before.

usage: python patch_scanout.py EAGL_C   (after patch_damage.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()
NL = chr(92) + 'n'


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static int preserve_damage;''', '''static int scan_on = 1;                 /* lavender: boot-arg glscan=0 - frames shown from CoreAnimation's own surfaces (patch_scanout.py) */
static int preserve_damage;''')
sub('''		preserve_damage = strstr(arguments, "glpreserve=2") != NULL;''', '''		preserve_damage = strstr(arguments, "glpreserve=2") != NULL;
		scan_on = strstr(arguments, "glscan=0") == NULL;''')

sub('''static void
target_to_surface(struct eagl *e, struct image *image)
{''', '''/*
 * lavender (patch_scanout.py): the scanout surfaces - what the panel shows. A finished frame is copied
 * into one the display does not hold, and the surface CoreAnimation swaps names it ("lv-show").
 */
static struct {
	IOSurfaceRef surface;
	GLuint texture;
} scans[4];
static int scan_last = -1;
static unsigned scan_copies, scan_none;

static void
scan_number(CFMutableDictionaryRef d, CFStringRef key, long value)
{
	int32_t v = (int32_t)value;
	CFNumberRef n = CFNumberCreate(NULL, kCFNumberSInt32Type, &v);

	if (n != NULL) {
		CFDictionarySetValue(d, key, n);
		CFRelease(n);
	}
}

static bool
scan_make(struct eagl *e, int i, IOSurfaceRef like)
{
	CFMutableDictionaryRef d = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
	GLint bound = 0;
	bool ok;

	if (d == NULL) {
		return false;
	}
	scan_number(d, kIOSurfaceWidth, (long)IOSurfaceGetWidth(like));
	scan_number(d, kIOSurfaceHeight, (long)IOSurfaceGetHeight(like));
	scan_number(d, kIOSurfaceBytesPerElement, (long)IOSurfaceGetBytesPerElement(like));
	scan_number(d, kIOSurfaceBytesPerRow, (long)IOSurfaceGetBytesPerRow(like));
	scan_number(d, kIOSurfaceAllocSize, (long)IOSurfaceGetAllocSize(like));
	scan_number(d, kIOSurfacePixelFormat, (long)IOSurfaceGetPixelFormat(like));
	scans[i].surface = IOSurfaceCreate(d);
	CFRelease(d);
	if (scans[i].surface == NULL) {
		return false;
	}
	glGetIntegerv(GL_TEXTURE_BINDING_2D, &bound);
	glGenTextures(1, &scans[i].texture);
	glBindTexture(GL_TEXTURE_2D, scans[i].texture);
	ok = redwood_gl_surface_texture(e->gl, IOSurfaceGetID(scans[i].surface));
	glBindTexture(GL_TEXTURE_2D, (GLuint)bound);
	if (!ok) {
		glDeleteTextures(1, &scans[i].texture);
		CFRelease(scans[i].surface);
		scans[i].surface = NULL;
		scans[i].texture = 0;
	}
	return ok;
}

static void
scan_name(IOSurfaceRef surface, uint32_t id)
{
	int32_t v = (int32_t)id;
	CFNumberRef n = CFNumberCreate(NULL, kCFNumberSInt32Type, &v);

	if (n != NULL) {
		IOSurfaceSetValue(surface, CFSTR("lv-show"), n);
		CFRelease(n);
	}
}

/*
 * The frame in `image` (a display surface with a mirror) is about to be copied out: the texture of a
 * scanout surface the display does not hold, which the surface now names - or 0 (all four are held, or
 * none could be made): the copy goes into the surface itself as before.
 */
static GLuint
scan_pick(struct eagl *e, struct image *image)
{
	static uint64_t said;
	int pick = -1;
	uint64_t now = now_us();

	if (!scan_on || image->surface == NULL || image->width < 1000 || image->height < 2000) {
		return 0;
	}
	for (int i = 0; i < 4; i++) {
		if (scans[i].surface == NULL && !scan_make(e, i, image->surface)) {
			say("redwood-gl: no scanout surface %d: frames are shown from CoreAnimation's own surfaces''' + NL + '''", i);
			scan_on = 0;
			scan_name(image->surface, 0);
			return 0;
		}
	}
	for (int n = 1; n <= 4 && pick < 0; n++) {
		int i = (scan_last + n) % 4;

		if (!IOSurfaceIsInUse(scans[i].surface)) {
			pick = i;
		}
	}
	if (now - said >= 1000000) {
		if (said != 0) {
			say("redwood-gl: %u frames copied to scanout surfaces, %u to their own (all four held)''' + NL + '''", scan_copies, scan_none);
		}
		said = now;
		scan_copies = scan_none = 0;
	}
	if (pick < 0) {
		scan_none++;
		scan_name(image->surface, 0);
		return 0;
	}
	scan_name(image->surface, IOSurfaceGetID(scans[pick].surface));
	scan_last = pick;
	scan_copies++;
	return scans[pick].texture;
}

static void
target_to_surface(struct eagl *e, struct image *image)
{''')

sub('''		glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, image->mirror, 0);
		glBlitFramebuffer(0, 0, image->width, image->height, 0, image->invert ? image->height : 0, image->width,''', '''		{
			GLuint scan = scan_pick(e, image);      /* lavender (patch_scanout.py): a surface the panel is not showing */

			glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, scan != 0 ? scan : image->mirror, 0);
		}
		glBlitFramebuffer(0, 0, image->width, image->height, 0, image->invert ? image->height : 0, image->width,''')
open(path, 'w', newline='\n').write(s)
print('ok')
