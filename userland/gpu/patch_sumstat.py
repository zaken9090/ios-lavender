"""lavender: boot-arg glsumstat=1 - what surface_changed() adds up, by kind of surface, a line a second (eagl.c).
surface_changed is ~12-15 % of backboardd's CPU on the home screen (profiles pf7, pf8). Before the kernel
is asked for the pages' modify bits instead (safe only for memory IOSurface owns: wired, never paged
out), count where the time goes: surfaces of IOSurface's own memory against surfaces made around a
client's memory (pixel format 0, "wrapped"), each below / from the full-sum limit (glsummb, 1 MB).
Line: "redwood-gl: sums: own small N looks K KB T us C changed | own big ... | wrapped small ... | wrapped big ..."
(KB = the size of the surfaces looked at, not the bytes read: big ones are sampled).
Diagnostic only.

usage: python patch_sumstat.py EAGL_C   (after patch_sumfast.py; run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static bool
surface_changed(struct eagl *e, struct image *image)
{''', '''static bool surface_changed_do(struct eagl *e, struct image *image);
static int sum_stat;                    /* lavender: boot-arg glsumstat=1 (patch_sumstat.py) */

static bool
surface_changed(struct eagl *e, struct image *image)
{
	static struct {
		unsigned looks, changed;
		uint64_t bytes, us;
	} kinds[4];
	static uint64_t told;
	static const char *const names[4] = { "own small", "own big", "wrapped small", "wrapped big" };

	if (!sum_stat) {
		return surface_changed_do(e, image);
	}
	IOSurfaceRef surface = image->surface;
	size_t size = IOSurfaceGetBytesPerRow(surface) * (size_t)(image->height - 1) +
	    (size_t)image->width * bytes_a_pixel(image->format, image->type);
	unsigned kind = (IOSurfaceGetPixelFormat(surface) == 0 ? 2 : 0) + (size >= sum_full_below ? 1 : 0);
	unsigned looked = image->looked;
	uint64_t began = now_us();
	bool changed = surface_changed_do(e, image);
	uint64_t now = now_us();

	if (image->looked != looked) {          /* (it was added up, not skipped) */
		kinds[kind].looks++;
		kinds[kind].bytes += size;
		kinds[kind].us += now - began;
		kinds[kind].changed += changed;
	}
	if (now - told >= 1000000) {
		char text[400] = "";
		size_t used = 0;

		for (unsigned k = 0; k < 4; k++) {
			used += (size_t)snprintf(text + used, sizeof(text) - used, "%s%s %u looks %llu KB %llu us %u changed",
			    k ? " | " : "", names[k], kinds[k].looks, kinds[k].bytes >> 10, kinds[k].us, kinds[k].changed);
		}
		say("redwood-gl: sums: %s\\n", text);
		bzero(kinds, sizeof(kinds));
		told = now;
	}
	return changed;
}

static bool
surface_changed_do(struct eagl *e, struct image *image)
{''')
sub('''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
''', '''		fetch_offered = strstr(arguments, "glfetch=0") == NULL;
		sum_stat = strstr(arguments, "glsumstat=1") != NULL;        /* lavender: patch_sumstat.py */
''')
open(path, 'w', newline='\n').write(s)
print('ok')
