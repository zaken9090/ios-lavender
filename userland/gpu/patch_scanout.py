"""lavender: the finished frame is shown from a surface CoreAnimation never draws into (eagl.c, glscan=0: off).

CoreAnimation has two display surfaces and starts the next frame in the one the panel is still
showing (87 % of frames, counter of patch_damage.py): the copy of the last frame and the drawing were
seen half done - the trembling bottom of the screen, torn rows. Waiting for the panel (glinuse) cures
it and costs a third of the frames (Settings 50 -> 33 fps).

Now, at the end of a frame, each display-sized surface drawn in it is copied (a GPU blit) into one of
four scanout surfaces of our own - one the display does not hold (IOSurfaceIsInUse) - and that one's
ID is put on the drawn surface as the IOSurface value "lv-show". The kernel (xnu 1167) shows the named
surface in place of the one swapped. CoreAnimation's own two surfaces are never on the panel any more.
When all four are held, the value is cleared and the surface itself is shown as before.

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

sub('''static void frame_functions(struct eagl *e);
static void
frame_end(struct eagl *e, bool finished)
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

/* The frame in `image` (a display surface) is done: copy it to a scanout surface and name that one. */
static void
scan_copy(struct eagl *e, struct image *image)
{
	static uint64_t said;
	GLint read = 0, draw = 0;
	GLboolean boxed;
	int pick = -1;
	uint64_t now = now_us();

	for (int i = 0; i < 4; i++) {
		if (scans[i].surface == NULL && !scan_make(e, i, image->surface)) {
			say("redwood-gl: no scanout surface %d: frames are shown from CoreAnimation's own surfaces''' + NL + '''", i);
			scan_on = 0;
			scan_name(image->surface, 0);
			return;
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
			say("redwood-gl: %u frames copied to scanout surfaces, %u shown from their own (all four held)''' + NL + '''", scan_copies, scan_none);
		}
		said = now;
		scan_copies = scan_none = 0;
	}
	if (pick < 0) {
		scan_none++;
		scan_name(image->surface, 0);           /* all on their way to the panel: this one is shown itself */
		return;
	}
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
	glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, image->texture, 0);
	glBindFramebuffer(GL_DRAW_FRAMEBUFFER, e->writer);
	glFramebufferTexture2D(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, scans[pick].texture, 0);
	glBlitFramebuffer(0, 0, image->width, image->height, 0, 0, image->width, image->height, GL_COLOR_BUFFER_BIT, GL_NEAREST);
	glBindFramebuffer(GL_READ_FRAMEBUFFER, (GLuint)read);
	glBindFramebuffer(GL_DRAW_FRAMEBUFFER, (GLuint)draw);
	(boxed ? glEnable : glDisable)(GL_SCISSOR_TEST);
	scan_name(image->surface, IOSurfaceGetID(scans[pick].surface));
	scan_last = pick;
	scan_copies++;
}

static void frame_functions(struct eagl *e);
static void
frame_end(struct eagl *e, bool finished)
{''')

sub('''	clear_now(e);
	before = now_us();
''', '''	clear_now(e);
	before = now_us();
	for (unsigned i = 0; scan_on && i < e->image_count; i++) {
		struct image *image = &e->images[i];

		/* lavender (patch_scanout.py): a display surface drawn in this frame goes to the panel as a copy */
		if (image->target && image->drawn && image->shared && image->surface != NULL && image->width >= 1000 && image->height >= 2000) {
			scan_copy(e, image);
		}
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
