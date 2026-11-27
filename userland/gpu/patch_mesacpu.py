"""lavender: cheaper CPU side of Mesa, from the first lavender project (no picture change).

- redwood_drm.c: DRM_MSM_GEM_MADVISE (0x08: handle, madv, retained) answered in user space with
  retained = 1, which is all RedwoodGPU answers (it never purges); freedreno's buffer cache calls it
  thousands of times a second and each IOKit trip cost ~18% of backboardd's drawing thread
  (first project 99b5fab).
- mk-mesa-mac.sh: LTO and -mcpu=cortex-a73 (SDM660 gold cores; the drawing thread spends ~37% in
  Mesa, spread over the driver; first project d537867).

usage: python patch_mesacpu.py WORK_DIR   (run by .github/workflows/userland.yml, before the Mesa build)
"""
import sys

work = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    open(path, 'w', newline='\n').write(s.replace(old, new))


patch(f'{work}/mesa/redwood-drm/redwood_drm.c', '''drmCommandWriteRead(int fd, unsigned long index, void *data, unsigned long size)
{
	(void)fd;
	return -call(''', '''drmCommandWriteRead(int fd, unsigned long index, void *data, unsigned long size)
{
	(void)fd;
	/* lavender (patch_mesacpu.py): MSM_GEM_MADVISE answered here - the kernel only says retained */
	if (index == 0x08 && data != NULL && size >= 12) {
		((uint32_t *)data)[2] = 1;
		return 0;
	}
	return -call(''')
patch(f'{work}/mesa/mk-mesa-mac.sh', '--buildtype=release -Db_ndebug=true \\',
      '--buildtype=release -Db_ndebug=true -Db_lto=true -Dc_args=-mcpu=cortex-a73 -Dcpp_args=-mcpu=cortex-a73 \\')
print('ok')
