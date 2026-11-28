"""lavender: which of CoreAnimation's calls end a frame, and the display copy put off at the others (eagl.c).

eagl copies a display frame out to its scanout surface (patch_scanout.py) at every glFlush, glFinish
and glFinishObjectAPPLE that finds it drawn. CoreAnimation calls these several times while it builds
one frame (9.7 copies per frame shown on the home screen, 1.6 in Settings); only the last is shown.

glwho=1: a line a second for every place these are called from (two return addresses, as unslid
shared-cache addresses "c0x18..." or IMAGE+OFFSET), how often, and how often a display frame was
drawn then.
glskip=c0xADDR[,c0xADDR...] (up to 8, the first return address of the glwho lines): at a call from
there a display frame (a mirrored target of the display's size) is not copied out; it stays drawn
and goes out at the next call from anywhere else. A line a second counts the copies put off.

(patch_swaphook.py tried the same by interposing IOMobileFramebufferSwapBegin: dyld's interposing does
not reach calls between the shared cache's own libraries - the hook never ran.)

usage: python patch_flushwho.py EAGL_C   (after patch_scanout.py; .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()
NL = chr(92) + 'n'


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static int scan_on = 1;''', '''static int who_lines;                   /* lavender: boot-arg glwho=1 - where the calls that end a frame come from (patch_flushwho.py) */
static unsigned long who_skip[8];       /* lavender: boot-arg glskip=c0xADDR,... - calls at which the display copy is put off */
static unsigned who_skips;
static bool who_defer;                  /* ... this call is one of them */
static int scan_on = 1;''')
sub('''		scan_on = strstr(arguments, "glscan=0") == NULL;''', '''		scan_on = strstr(arguments, "glscan=0") == NULL;
		who_lines = strstr(arguments, "glwho=1") != NULL;
		{
			const char *k = strstr(arguments, "glskip=");

			for (k = k != NULL ? k + 7 : NULL; k != NULL && who_skips < 8;) {
				char *end;
				unsigned long v;

				if (*k == 'c') {
					k++;
				}
				v = strtoul(k, &end, 16);
				if (end == k || v == 0) {
					break;
				}
				who_skip[who_skips++] = v;
				k = *end == ',' ? end + 1 : NULL;
			}
		}''')

sub('''static void
my_glFinish(void *context)
{''', '''/*
 * lavender (patch_flushwho.py): the calls that end a frame, by caller. kind: 0 glFlush, 1 glFinish,
 * 2 glFinishObjectAPPLE.
 */
extern const void *_dyld_get_shared_cache_range(size_t *length);

static struct {
	uintptr_t at, from;
	unsigned kind, n, shown;
} who[24];
static unsigned who_put_off_n, who_made_n;

/* an address in the shared cache, unslid (as the symbol tables have it); 0: not in it */
static unsigned long
who_unslid(uintptr_t a)
{
	static uintptr_t base;
	static size_t length;

	if (base == 0) {
		base = (uintptr_t)_dyld_get_shared_cache_range(&length);
	}
	return base != 0 && a >= base && a < base + length ? (unsigned long)(a - base + 0x180000000UL) : 0;
}

static void
who_name(uintptr_t a, char *buf, size_t size)
{
	Dl_info info;

	if (who_unslid(a) != 0) {
		snprintf(buf, size, "c%#lx", who_unslid(a));
	} else if (dladdr((const void *)a, &info) && info.dli_fname != NULL) {
		const char *name = strrchr(info.dli_fname, '/');

		snprintf(buf, size, "%s+%#lx", name != NULL ? name + 1 : info.dli_fname, (unsigned long)(a - (uintptr_t)info.dli_fbase));
	} else {
		snprintf(buf, size, "%#lx", (unsigned long)a);
	}
}

/* a display frame whose copy out waits (glskip) */
static bool
who_put_off(struct image *image)
{
	if (!who_defer || image->mirror == 0 || image->width < 1000 || image->height < 2000) {
		return false;
	}
	who_put_off_n++;
	return true;
}

static void
who_note(struct eagl *e, unsigned kind, uintptr_t at, uintptr_t from)
{
	static uint64_t said;
	static const char *const kinds[] = { "glFlush", "glFinish", "glFinishObjectAPPLE" };
	unsigned long c = who_unslid(at);
	bool shown = false;
	uint64_t now;
	int i;

	who_defer = false;
	for (unsigned k = 0; k < who_skips && c != 0; k++) {
		who_defer |= who_skip[k] == c;
	}
	for (unsigned k = 0; k < e->image_count; k++) {
		struct image *image = &e->images[k];

		if (image->target && image->drawn && image->mirror != 0 && image->width >= 1000 && image->height >= 2000) {
			shown = true;
		}
	}
	who_made_n += shown && !who_defer;
	for (i = 0; i < 24 && who_lines; i++) {
		if (who[i].n == 0 || (who[i].at == at && who[i].from == from && who[i].kind == kind)) {
			break;
		}
	}
	if (who_lines && i < 24) {
		who[i].at = at;
		who[i].from = from;
		who[i].kind = kind;
		who[i].n++;
		who[i].shown += shown;
	}
	now = now_us();
	if (now - said < 1000000) {
		return;
	}
	if (said != 0) {
		for (i = 0; i < 24 && who_lines && who[i].n != 0; i++) {
			char a[96], f[96];

			who_name(who[i].at, a, sizeof(a));
			who_name(who[i].from, f, sizeof(f));
			say("redwood-gl: who %s at %s from %s: %u, %u with a display frame drawn''' + NL + '''", kinds[who[i].kind], a, f, who[i].n, who[i].shown);
		}
		if (who_skips != 0) {
			say("redwood-gl: %u display copies put off (glskip), %u calls copied one out''' + NL + '''", who_put_off_n, who_made_n);
		}
	}
	said = now;
	bzero(who, sizeof(who));
	who_put_off_n = who_made_n = 0;
}

#define WHO(e, kind)    do { if (who_lines || who_skips) who_note((e), (kind), (uintptr_t)__builtin_return_address(0), (uintptr_t)__builtin_return_address(1)); } while (0)

static void
my_glFinish(void *context)
{''')

sub('''	EAGL_ENTER(e, 0x2d0);
	if (eagl_tracing) {
		eagl_trace("glFinish()''' + NL + '''");
	}''', '''	EAGL_ENTER(e, 0x2d0);
	WHO(e, 1);
	if (eagl_tracing) {
		eagl_trace("glFinish()''' + NL + '''");
	}''')
sub('''	EAGL_ENTER(e, 0x2d8);
	if (eagl_tracing) {
		eagl_trace("glFlush()''' + NL + '''");
	}''', '''	EAGL_ENTER(e, 0x2d8);
	WHO(e, 0);
	if (eagl_tracing) {
		eagl_trace("glFlush()''' + NL + '''");
	}''')
sub('''	EAGL_ENTER(e, 0xeb8);
	clear_now(e);''', '''	EAGL_ENTER(e, 0xeb8);
	WHO(e, 2);
	clear_now(e);''')

# frame_end: the display frames put off stay drawn (who_put_off is defined below frame_end: declared here)
sub('''static void frame_functions(struct eagl *e);
static void
frame_end(struct eagl *e, bool finished)
{''', '''static void frame_functions(struct eagl *e);
static bool who_put_off(struct image *image);
static void
frame_end(struct eagl *e, bool finished)
{''')
sub('''		if (e->images[i].target && e->images[i].drawn && e->images[i].mirror != 0) {
			target_to_surface(e, &e->images[i]);    /* (the GPU's copy: before what follows sends it out) */''', '''		if (e->images[i].target && e->images[i].drawn && e->images[i].mirror != 0 && !who_put_off(&e->images[i])) {
			target_to_surface(e, &e->images[i]);    /* (the GPU's copy: before what follows sends it out) */''')
sub('''		if (e->images[i].target && e->images[i].drawn) {
			copied += !e->images[i].shared;
			target_to_surface(e, &e->images[i]);''', '''		if (e->images[i].target && e->images[i].drawn && !(who_defer && e->images[i].mirror != 0 && e->images[i].width >= 1000 && e->images[i].height >= 2000)) {
			copied += !e->images[i].shared;
			target_to_surface(e, &e->images[i]);''')
open(path, 'w', newline='\n').write(s)
print('ok')
