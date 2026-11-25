"""lavender: the sampler prints who used the CPUs since the last round (patch 1033): SMC line.

  SMC <interval ms>: all <percent of one core> | name <percent> ...   (the eight biggest)

From each task's cpu_time ledger (get_task_cpu_time, nanoseconds). 400 = four cores full.

usage: python mk_cpustat.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_sample.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static void
sweet_sample_thread(__unused void *arg, __unused wait_result_t wr)
{''', '''/* lavender: CPU time by process since the last round (xnu/src/mk_cpustat.py) */
extern uint64_t get_task_cpu_time(task_t);
extern uint64_t mach_absolute_time(void);
extern void absolutetime_to_nanoseconds(uint64_t abstime, uint64_t *result);
static struct { int pid; uint64_t last; } lv_cpu[512];
static struct { char name[20]; uint64_t d; } lv_top[8];
static uint64_t lv_cpu_sum;

static int
lv_cpu_proc(proc_t p, __unused void *arg)
{
	int pid = proc_pid(p);
	task_t task = proc_task(p);
	uint64_t t, d = 0;
	unsigned slot = (unsigned)pid % 512, tries = 0;

	if (task == TASK_NULL) {
		return PROC_RETURNED;
	}
	t = get_task_cpu_time(task);
	while (tries++ < 512 && lv_cpu[slot].last != 0 && lv_cpu[slot].pid != pid) {
		slot = (slot + 1) % 512;
	}
	if (lv_cpu[slot].pid == pid && lv_cpu[slot].last != 0 && t >= lv_cpu[slot].last) {
		d = t - lv_cpu[slot].last;
	}
	lv_cpu[slot].pid = pid;
	lv_cpu[slot].last = t ? t : 1;
	lv_cpu_sum += d;
	for (int i = 0; i < 8; i++) {
		if (d > lv_top[i].d) {
			for (int j = 7; j > i; j--) {
				lv_top[j] = lv_top[j - 1];
			}
			lv_top[i].d = d;
			proc_name(pid, lv_top[i].name, sizeof(lv_top[i].name));
			break;
		}
	}
	return PROC_RETURNED;
}

static void
lv_cpu_report(void)
{
	static uint64_t before;
	uint64_t now = mach_absolute_time(), ns = 0;
	char line[320];
	int n;

	bzero(lv_top, sizeof(lv_top));
	lv_cpu_sum = 0;
	proc_iterate(PROC_ALLPROCLIST, lv_cpu_proc, NULL, NULL, NULL);
	absolutetime_to_nanoseconds(now - before, &ns);
	if (before != 0 && ns != 0) {
		n = snprintf(line, sizeof(line), "SMC %llu ms: all %llu |", ns / 1000000, lv_cpu_sum * 100 / ns);
		for (int i = 0; i < 8 && lv_top[i].d != 0 && n < (int)sizeof(line) - 40; i++) {
			n += snprintf(line + n, sizeof(line) - n, " %s %llu", lv_top[i].name, lv_top[i].d * 100 / ns);
		}
		printf("%s\\n", line);
	}
	before = now;
}

static void
sweet_sample_thread(__unused void *arg, __unused wait_result_t wr)
{''')
sub('''		sweet_surface_report();
''', '''		sweet_surface_report();
		lv_cpu_report();
''')
open(path, 'w', newline='\n').write(s)
print('ok')
