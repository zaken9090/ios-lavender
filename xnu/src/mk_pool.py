"""lavender: GPU pool buffers described as parts of their chunk's descriptor (patch 1016).

topaz_gpu_pool_md() made a descriptor of its own (withAddressRange) for every Mesa buffer and every
pool surface. For memory the kernel does not manage, a task mapping goes through a device pager of
that descriptor, and the last unmap of it (a buffer or surface let go) destroys the pager's VM
object: backboardd's render thread could wait in vm_object_destroy for good. With gpu=1 this
matched what we saw: the lock screen drawn by the GPU, frames late, no unlock, then a hang.

Now each 64 MB chunk keeps the descriptor it was mapped into the kernel with, for good, and a
buffer gets an IOSubMemoryDescriptor of it: its pager is the chunk's, which never goes away.
Memory outside the pool (or a chunk not mapped yet) still gets a descriptor of its own.
Idea from the user's first lavender project (its patch 1021); code written for this tree.

usage: python mk_pool.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAdreno.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#include <IOKit/IOBufferMemoryDescriptor.h>
''', '''#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IOSubMemoryDescriptor.h>
''')
sub('''static uint8_t *gpu_chunk_va[GPU_POOL_CHUNKS];
''', '''static uint8_t *gpu_chunk_va[GPU_POOL_CHUNKS];
static IOMemoryDescriptor *gpu_chunk_md[GPU_POOL_CHUNKS];  /* lavender: a chunk's descriptor, kept for good */
''')
sub('''extern "C" IOMemoryDescriptor *topaz_gpu_pool_md(uint64_t pa, uint64_t size);
IOMemoryDescriptor *
topaz_gpu_pool_md(uint64_t pa, uint64_t size)
{
	return IOMemoryDescriptor::withAddressRange(pa, size,
	           kIODirectionInOut | (kIOWriteCombineCache << kIOMemoryBufferCacheShift), TASK_NULL);
}''', '''static IOMemoryDescriptor *
gpu_phys_md(uint64_t pa, uint64_t size)
{
	return IOMemoryDescriptor::withAddressRange(pa, size,
	           kIODirectionInOut | (kIOWriteCombineCache << kIOMemoryBufferCacheShift), TASK_NULL);
}

/*
 * lavender: a pool buffer is a part of its chunk's descriptor. A descriptor of its own had a device
 * pager of its own, and the last unmap of it destroyed the pager's VM object, where backboardd's
 * render thread could wait for good (xnu/src/mk_pool.py). The chunk's pager never goes away.
 */
extern "C" IOMemoryDescriptor *topaz_gpu_pool_md(uint64_t pa, uint64_t size);
IOMemoryDescriptor *
topaz_gpu_pool_md(uint64_t pa, uint64_t size)
{
	if (pa >= GPU_POOL_BASE && pa + size <= GPU_POOL_BASE + GPU_POOL_SIZE) {
		unsigned c = (unsigned)((pa - GPU_POOL_BASE) / GPU_POOL_CHUNK);
		uint64_t off = pa - GPU_POOL_BASE - c * GPU_POOL_CHUNK;
		if (gpu_chunk_md[c] != NULL && off + size <= GPU_POOL_CHUNK) {
			return IOSubMemoryDescriptor::withSubRange(gpu_chunk_md[c], (IOByteCount)off, (IOByteCount)size,
			           kIODirectionInOut);
		}
	}
	return gpu_phys_md(pa, size);
}''')
sub('''		IOMemoryDescriptor *md = topaz_gpu_pool_md(GPU_POOL_BASE + c * GPU_POOL_CHUNK, GPU_POOL_CHUNK);''',
    '''		IOMemoryDescriptor *md = gpu_phys_md(GPU_POOL_BASE + c * GPU_POOL_CHUNK, GPU_POOL_CHUNK);''')
sub('''			gpu_chunk_va[c] = (uint8_t *)map->getVirtualAddress();     /* (kept for good, with md) */
''', '''			gpu_chunk_va[c] = (uint8_t *)map->getVirtualAddress();     /* (kept for good, with md) */
			gpu_chunk_md[c] = md;
''')
open(path, 'w', newline='\n').write(s)
print('ok')
