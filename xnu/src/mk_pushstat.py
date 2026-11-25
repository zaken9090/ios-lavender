"""lavender: count which IOSurfaces the GPU is given and which go out of the CPU cache (patch 1024).

Settings showed rows of earlier frames while scrolling; with glcopy=1 (eagl copies every surface)
they were right, so the GPU reads applications' surfaces it shares in place while the CPU still
holds their new pixels in its cache. RedwoodGPU pushes a surface out of the cache when its seed
moved or 4 ms after the last push, but the log said "0 KB out of the cache". Now the 5-second
line is followed by

  RedwoodGPU: surfaces named N (pool P), pushed K (B KB), skipped S

usage: python mk_pushstat.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/RedwoodGPU.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	uint64_t flushed;                       /* bytes sent out of the cache */
''', '''	uint64_t flushed;                       /* bytes sent out of the cache */
	uint32_t lv_named, lv_pool, lv_pushed, lv_skipped;      /* lavender: surface buffers (mk_pushstat.py) */
	uint64_t lv_pushed_bytes;
''')
sub('''		if (b->surface != NULL && b->surface->gpuPool) {
			continue;                       /* topaz: GPU pool memory is write-combined: nothing in the cache */
		}
		if (b->surface != NULL) {
			uint32_t seed = *(volatile uint32_t *) ((uint8_t *) b->surface->state->getBytesNoCopy() + 0xc);

			if (seed == b->seed && !b->seen && began - b->pushed < again) {
				continue;
			}''', '''		if (b->surface != NULL) {
			gGPUStat.lv_named++;
		}
		if (b->surface != NULL && b->surface->gpuPool) {
			gGPUStat.lv_pool++;
			continue;                       /* topaz: GPU pool memory is write-combined: nothing in the cache */
		}
		if (b->surface != NULL) {
			uint32_t seed = *(volatile uint32_t *) ((uint8_t *) b->surface->state->getBytesNoCopy() + 0xc);

			if (seed == b->seed && !b->seen && began - b->pushed < again) {
				gGPUStat.lv_skipped++;
				continue;
			}
			gGPUStat.lv_pushed++;
			gGPUStat.lv_pushed_bytes += b->size;''')
sub('''		bzero(&gGPUStat, sizeof(gGPUStat));''', '''		IOLog("RedwoodGPU: surfaces named %u (pool %u), pushed %u (%llu KB), skipped %u\\n", gGPUStat.lv_named,
		    gGPUStat.lv_pool, gGPUStat.lv_pushed, gGPUStat.lv_pushed_bytes >> 10, gGPUStat.lv_skipped);
		bzero(&gGPUStat, sizeof(gGPUStat));''')
open(path, 'w', newline='\n').write(s)
print('ok')
