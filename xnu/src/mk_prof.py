"""lavender: a statistical CPU profiler for one process (patch 1148).

The SMP sampler reads a thread's saved user state, which for a running thread is where it last entered
the kernel, so it cannot say where backboardd spends ~18 ms of CPU a frame. Now, with boot-arg
sweetprof=NAME, a kernel thread interrupts the other CPUs every sweetprof_us (1000) microseconds for
sweetprof_s (30) seconds, starting sweetprof_first (60) s after boot; each CPU running a thread of NAME
records the interrupted pc and lr (user or kernel). Then the report:
  SPF NAME: N samples (user U, kernel K), M looks
  SPF u pc 0x... n COUNT img 0xBASE+0xOFF NAME   (user pc: the Mach-O image found below it, its LC_ID_DYLIB)
  SPF u lr ...                                    (callers)
  SPF k pc 0x... n COUNT                          (kernel pc: tools/ksym.py)
Shared-cache addresses minus the SMP slide are the cache's own; our dylibs: nm on the CI artifacts.

usage: python mk_prof.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/osfmk/kern/exception.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#endif /* ARM64_BOARD_CONFIG_SWEET */

kern_return_t
bsd_exception(''', '''/*
 * lavender: statistical profiler, boot-arg sweetprof=NAME (xnu/src/mk_prof.py)
 */
#include <arm/cpu_data_internal.h>
extern void qsort(void *a, size_t n, size_t es, int (*cmp)(const void *, const void *));

typedef void (*lvp_func_t)(void *);
extern unsigned int cpu_broadcast_xcall_simple(boolean_t self_xcall, lvp_func_t func, void *parm);
void lv_prof_run(const char *name, task_t task, uint32_t us, uint32_t secs);

#define LVP_N 16384
static uint64_t lvp_pc[LVP_N], lvp_lr[LVP_N];
static uint8_t lvp_user[LVP_N];
static volatile uint32_t lvp_n, lvp_looks;
static task_t lvp_task;

static void
lvp_handler(void *arg __unused)
{
	thread_t th = current_thread();
	arm_saved_state_t *is = (arm_saved_state_t *)getCpuDatap()->cpu_int_state;

	os_atomic_inc(&lvp_looks, relaxed);
	if (is == NULL || get_threadtask(th) != lvp_task) {
		return;
	}
	uint32_t i = os_atomic_inc_orig(&lvp_n, relaxed);
	if (i >= LVP_N) {
		return;
	}
	lvp_user[i] = (get_saved_state_cpsr(is) & PSR64_MODE_EL_MASK) == PSR64_MODE_EL0;
	lvp_pc[i] = get_saved_state_pc(is);
	lvp_lr[i] = get_saved_state_lr(is);
}

static int
lvp_cmp(const void *a, const void *b)
{
	uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
	return x < y ? -1 : x > y;
}

/* the Mach-O image an address of the task is in: its header below it, and its install name */
static uint64_t
lvp_image(vm_map_t map, uint64_t addr, char *name, size_t len)
{
	uint64_t page = addr & ~0x3fffull;
	uint32_t magic = 0;
	strlcpy(name, "?", len);
	for (int i = 0; i < 8192 && page != 0; i++, page -= 0x4000) {
		if (vm_map_read_user(map, page, &magic, 4) != KERN_SUCCESS) {
			return 0;
		}
		if (magic != 0xfeedfacf) {
			continue;
		}
		uint32_t hdr[8], off = 32;
		if (vm_map_read_user(map, page, hdr, sizeof(hdr)) != KERN_SUCCESS) {
			return page;
		}
		strlcpy(name, hdr[3] == 2 ? "main" : "-", len);
		for (uint32_t c = 0; c < hdr[4] && c < 200 && off < 32 + hdr[5]; c++) {
			uint32_t lc[2];
			if (vm_map_read_user(map, page + off, lc, sizeof(lc)) != KERN_SUCCESS || lc[1] < 8) {
				break;
			}
			if (lc[0] == 0xd) {                     /* LC_ID_DYLIB: dylib_command, name at its offset */
				uint32_t noff = 0;
				char buf[128] = {};
				if (vm_map_read_user(map, page + off + 8, &noff, 4) == KERN_SUCCESS &&
				    vm_map_read_user(map, page + off + noff, buf, sizeof(buf) - 1) == KERN_SUCCESS) {
					const char *last = buf;
					for (const char *q = buf; *q; q++) {
						if (*q == '/') {
							last = q + 1;
						}
					}
					strlcpy(name, last, len);
				}
				break;
			}
			off += lc[1];
		}
		return page;
	}
	return 0;
}

/* sorted values: the most frequent ones, printed */
static void
lvp_top(const char *name, const char *what, uint64_t *v, uint32_t n, int top, vm_map_t map)
{
	qsort(v, n, sizeof(v[0]), lvp_cmp);
	for (int t = 0; t < top; t++) {
		uint64_t best = 0;
		uint32_t bestn = 0, run = 0;
		for (uint32_t i = 0; i < n; i++) {
			run = (i > 0 && v[i] == v[i - 1]) ? run + 1 : 1;
			if (v[i] != 0 && run > bestn) {
				bestn = run;
				best = v[i];
			}
		}
		if (bestn < 2) {
			return;
		}
		if (map != NULL) {
			char img[48];
			uint64_t base = lvp_image(map, best, img, sizeof(img));
			printf("SPF %s %s 0x%llx n %u img 0x%llx+0x%llx %s\\n", name, what, best, bestn, base, best - base, img);
		} else {
			printf("SPF %s %s 0x%llx n %u\\n", name, what, (uint64_t)VM_KERNEL_ADDRHIDE(best), bestn);
		}
		for (uint32_t i = 0; i < n; i++) {
			if (v[i] == best) {
				v[i] = 0;
			}
		}
	}
}

void
lv_prof_run(const char *name, task_t task, uint32_t us, uint32_t secs)
{
	static uint64_t ubuf[LVP_N], kbuf[LVP_N];
	uint64_t end, now;
	int dummy = 0;

	lvp_n = lvp_looks = 0;
	lvp_task = task;
	clock_interval_to_deadline(secs, NSEC_PER_SEC, &end);
	printf("SPF %s: sampling every %u us for %u s\\n", name, us, secs);
	do {
		cpu_broadcast_xcall_simple(FALSE, lvp_handler, &dummy);
		delay_for_interval(us, NSEC_PER_USEC);
		now = mach_absolute_time();
	} while (now < end && lvp_n < LVP_N);
	lvp_task = TASK_NULL;
	uint32_t n = lvp_n < LVP_N ? lvp_n : LVP_N, nu = 0, nk = 0;
	for (uint32_t i = 0; i < n; i++) {
		if (lvp_user[i]) {
			ubuf[nu++] = lvp_pc[i];
		} else {
			kbuf[nk++] = lvp_pc[i];
		}
	}
	printf("SPF %s: %u samples (user %u, kernel %u), %u looks\\n", name, n, nu, nk, lvp_looks);
	vm_map_t map = get_task_map(task);
	lvp_top(name, "u pc", ubuf, nu, 60, map);
	lvp_top(name, "k pc", kbuf, nk, 30, NULL);
	nu = 0;
	for (uint32_t i = 0; i < n; i++) {
		if (lvp_user[i]) {
			ubuf[nu++] = lvp_lr[i];
		}
	}
	lvp_top(name, "u lr", ubuf, nu, 40, map);
	printf("SPF %s: done\\n", name);
}

#endif /* ARM64_BOARD_CONFIG_SWEET */

kern_return_t
bsd_exception(''')
open(path, 'w', newline='\n').write(s)

path = f'{tree}/bsd/dev/sweet_sample.c'
s = open(path, newline='').read()
sub('''static void
sweet_sample_thread(__unused void *arg, __unused wait_result_t wr)
{
	static int chan;
''', '''/* lavender: sweetprof=NAME - the statistical profiler (osfmk/kern/exception.c, xnu/src/mk_prof.py) */
extern void lv_prof_run(const char *name, task_t task, uint32_t us, uint32_t secs);
static char lv_prof_name[32];
static task_t lv_prof_task;

static int
lv_prof_find(proc_t p, __unused void *arg)
{
	char name[32];
	proc_name(proc_pid(p), name, sizeof(name));
	if (lv_prof_task == TASK_NULL && strcmp(name, lv_prof_name) == 0 && proc_task(p) != TASK_NULL) {
		lv_prof_task = proc_task(p);
		task_reference(lv_prof_task);
	}
	return PROC_RETURNED;
}

static void
lv_prof_thread(__unused void *arg, __unused wait_result_t wr)
{
	static int chan;
	uint32_t first = 60, us = 1000, secs = 30;
	PE_parse_boot_argn("sweetprof_first", &first, sizeof(first));
	PE_parse_boot_argn("sweetprof_us", &us, sizeof(us));
	PE_parse_boot_argn("sweetprof_s", &secs, sizeof(secs));
	(void)tsleep(&chan, PZERO, "lvprof", (int)first * hz);
	proc_iterate(PROC_ALLPROCLIST, lv_prof_find, NULL, NULL, NULL);
	if (lv_prof_task == TASK_NULL) {
		printf("SPF %s: no such process\\n", lv_prof_name);
		return;
	}
	lv_prof_run(lv_prof_name, lv_prof_task, us < 100 ? 100 : us, secs);
	task_deallocate(lv_prof_task);
}

static void
sweet_sample_thread(__unused void *arg, __unused wait_result_t wr)
{
	static int chan;
	if (PE_parse_boot_argn("sweetprof", lv_prof_name, sizeof(lv_prof_name)) && lv_prof_name[0] != 0) {
		thread_t pt;
		if (kernel_thread_start(lv_prof_thread, NULL, &pt) == KERN_SUCCESS) {
			thread_deallocate(pt);
		}
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
