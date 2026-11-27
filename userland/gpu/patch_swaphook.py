"""lavender: a display frame is copied to its scanout surface once, when it is swapped (eagl.c + topaz_inject.c).

eagl copied a display frame out (the "mirror" blit, a whole screen) at the end of every glFlush /
glFinish. CoreAnimation flushes several times while it builds one frame: 9.7 copies for every frame
shown on the home screen (App Library), 1.6 in Settings (bench w2a: copies and SWEET FPS a second) -
about half of the pixels the GPU passed for a home screen frame. Only the last copy is ever shown.

Now, for any display-sized surface with a scanout copy (patch_scanout.py), the copy is put off until
CoreAnimation swaps: libtopaz-inject (inserted into backboardd) interposes IOMobileFramebufferSwapBegin
and calls redwood_eagl_before_swap() first, which copies what is pending and hands it to the kernel.
It applies to every display frame of every screen, not to a particular one.

The copies are put off only once the hook has been seen on the thread that draws; a swap from another
thread, or no hook at all (interposing not honoured), leaves the copy at every flush as before.
glswap=0 keeps the old way.

usage: python patch_swaphook.py EAGL_C TOPAZ_INJECT_C   (after patch_scanout.py; .github/workflows/userland.yml)
"""
import sys

NL = chr(92) + 'n'

# ---- eagl.c ----
path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static int scan_on = 1;''', '''static int swap_copy = 1;               /* lavender: boot-arg glswap=0 - a display frame is copied out at every flush (patch_swaphook.py) */
static int scan_on = 1;''')
sub('''		scan_on = strstr(arguments, "glscan=0") == NULL;''', '''		scan_on = strstr(arguments, "glscan=0") == NULL;
		swap_copy = strstr(arguments, "glswap=0") == NULL;''')

sub('''/*
 * lavender (patch_scanout.py): the scanout surfaces - what the panel shows.''', '''/*
 * lavender (patch_swaphook.py): display frames whose copy to the scanout surface waits for the swap.
 * swap_hooked: redwood_eagl_before_swap() has been called on the thread that draws.
 */
#include <pthread.h>
static GLuint swap_pending[4];          /* textures of the display images to copy */
static struct eagl *swap_e;
static pthread_t swap_thread;
static bool swap_hooked, swap_now;
static unsigned swap_put_off, swap_copied;

static bool
swap_defer(struct eagl *e, struct image *image)
{
	if (image->surface == NULL || image->width < 1000 || image->height < 2000) {
		return false;
	}
	swap_e = e;
	swap_thread = pthread_self();
	if (swap_now || !swap_copy || !scan_on || !swap_hooked) {
		return false;
	}
	for (int i = 0; i < 4; i++) {
		if (swap_pending[i] == image->texture) {
			swap_put_off++;
			return true;
		}
	}
	for (int i = 0; i < 4; i++) {
		if (swap_pending[i] == 0) {
			swap_pending[i] = image->texture;
			swap_put_off++;
			return true;
		}
	}
	return false;                           /* no room: copied now */
}

/*
 * lavender (patch_scanout.py): the scanout surfaces - what the panel shows.''')

sub('''	image->drawn = false;
	if (image->mirror != 0) {
		GLint read = 0, draw = 0;
''', '''	image->drawn = false;
	if (image->mirror != 0 && swap_defer(e, image)) {
		return;                         /* lavender (patch_swaphook.py): copied when the frame is swapped */
	}
	if (image->mirror != 0) {
		GLint read = 0, draw = 0;
''')

sub('''/* ---- the entries written by hand''', '''/*
 * lavender (patch_swaphook.py): CoreAnimation is about to swap a frame to the display (called by
 * libtopaz-inject from its IOMobileFramebufferSwapBegin). The display frames put off are copied to
 * their scanout surfaces now and handed to the kernel.
 */
__attribute__((visibility("default"))) void redwood_eagl_before_swap(void);

void
redwood_eagl_before_swap(void)
{
	static uint64_t said;
	static unsigned other;
	struct eagl *e = swap_e;
	GLboolean boxed = 0;
	bool any = false;
	uint64_t now;

	if (e == NULL || !swap_copy) {
		return;
	}
	if (!pthread_equal(pthread_self(), swap_thread)) {
		if (other++ < 3) {
			say("redwood-gl: a swap from a thread that does not draw: frames are copied out at every flush''' + NL + '''");
		}
		swap_hooked = false;            /* (what is pending is copied at that image's next flush) */
		return;
	}
	if (!swap_hooked) {
		swap_hooked = true;
		say("redwood-gl: display frames are copied out when they are swapped (patch_swaphook.py)''' + NL + '''");
	}
	for (int i = 0; i < 4; i++) {
		struct image *image = swap_pending[i] != 0 ? image_of(e, swap_pending[i]) : NULL;

		swap_pending[i] = 0;
		if (image == NULL || image->mirror == 0 || image->surface == NULL) {
			continue;
		}
		if (!any) {
			any = true;
			if (current != e) {
				(void)redwood_gl_make_current(e->gl);
				current = e;
			}
			boxed = glIsEnabled(GL_SCISSOR_TEST);
			glDisable(GL_SCISSOR_TEST);
		}
		swap_now = true;
		target_to_surface(e, image);
		swap_now = false;
		swap_copied++;
	}
	if (any) {
		(boxed ? glEnable : glDisable)(GL_SCISSOR_TEST);
		glFlush();
		(void)lv_flush_sync();
	}
	now = now_us();
	if (now - said >= 1000000) {
		if (said != 0 && swap_put_off != 0) {
			say("redwood-gl: %u display copies put off, %u made at the swap''' + NL + '''", swap_put_off, swap_copied);
		}
		said = now;
		swap_put_off = swap_copied = 0;
	}
}

/* ---- the entries written by hand''')
open(path, 'w', newline='\n').write(s)

# ---- topaz_inject.c: the hook ----
path = sys.argv[2]
t = open(path, newline='').read()
assert 'lv_swap_begin' not in t
t += '''
/*
 * lavender (patch_swaphook.py): CoreAnimation swaps a frame to the display - libtopaz-gl copies the
 * frame to its scanout surface first (redwood_eagl_before_swap). The framework's function is looked up
 * at load (-U at the link, weak: absent, nothing is interposed).
 */
#include <dlfcn.h>
extern int IOMobileFramebufferSwapBegin(void *framebuffer, int *token) __attribute__((weak_import));

static int
lv_swap_begin(void *framebuffer, int *token)
{
	static void (*before)(void);
	static int looked;

	if (!looked) {
		/* (the library is loaded by this file's constructor, not into the global namespace) */
		void *gl = dlopen(TOPAZ_GL, RTLD_NOW);

		before = gl != NULL ? (void (*)(void))dlsym(gl, "redwood_eagl_before_swap") : NULL;
		looked = 1;
	}
	if (before != NULL) {
		before();
	}
	return IOMobileFramebufferSwapBegin(framebuffer, token);
}

__attribute__((used)) static const struct {
	const void *replacement, *replacee;
} lv_interpose_swap_begin __attribute__((section("__DATA,__interpose"))) = {
	(const void *)lv_swap_begin, (const void *)IOMobileFramebufferSwapBegin
};
'''
open(path, 'w', newline='\n').write(t)
print('ok')
