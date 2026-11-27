"""lavender: image_of() finds a texture's image through a small index instead of walking all images (eagl.c).

The profiler (xnu 1148/1149, sweetprof=backboardd) showed image_of()'s walk over up to 256 images of
216 bytes, on every bind and draw, among the busiest pieces of libtopaz-gl while Settings scrolls. Now a
4096-entry table (texture & 4095 -> index + 1) is tried first and checked; a miss walks as before and
fills the table. image_forget() moves the last image into the freed place: its entry follows it.

usage: python patch_imageof.py EAGL_C   (run by .github/workflows/userland.yml)
"""
import sys

path = sys.argv[1]
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	struct image images[256];
	unsigned image_count;
''', '''	struct image images[256];
	unsigned image_count;
	uint16_t image_slot[4096];      /* lavender: texture & 4095 -> index + 1 (patch_imageof.py) */
''')
sub('''static struct image *
image_of(struct eagl *e, GLuint texture)
{
	for (unsigned i = 0; i < e->image_count; i++) {
		if (e->images[i].texture == texture) {
			return &e->images[i];
		}
	}
	return NULL;
}''', '''static struct image *
image_of(struct eagl *e, GLuint texture)
{
	unsigned k = e->image_slot[texture & 4095];
	if (k != 0 && k - 1 < e->image_count && e->images[k - 1].texture == texture) {
		return &e->images[k - 1];
	}
	for (unsigned i = 0; i < e->image_count; i++) {
		if (e->images[i].texture == texture) {
			e->image_slot[texture & 4095] = (uint16_t)(i + 1);
			return &e->images[i];
		}
	}
	return NULL;
}''')
sub('''		CFRelease(image->surface);
		*image = e->images[--e->image_count];
	}''', '''		CFRelease(image->surface);
		*image = e->images[--e->image_count];
		if (image != &e->images[e->image_count]) {
			e->image_slot[image->texture & 4095] = (uint16_t)(image - e->images + 1);
		}
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
