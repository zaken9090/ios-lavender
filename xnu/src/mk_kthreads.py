"""lavender: CPU time by kernel thread (patch 1142).

kernel_task uses 14% of a core in idle and 40-49% while the UI draws, but
its threads have no user state, so the SMP sampler prints nothing for it.
With sweetsample=kernel_task each round now prints the top kernel threads
by CPU time since the previous round:
  SMT kernel_task tid N ms M name X cont 0x... k 0x...
cont = continuation (blocked threads that gave up their stack), k = saved lr
(blocked threads with a stack). Symbolicate both with tools/ksym.py.

usage: python mk_kthreads.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/osfmk/kern/exception.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''void sweet_sample_task(const char *name, int pid, task_t task);

void
sweet_sample_task(const char *name, int pid, task_t task)
{''', '''void sweet_sample_task(const char *name, int pid, task_t task);

/* lavender: CPU time by kernel thread (xnu/src/mk_kthreads.py) */
extern uint64_t recount_thread_time_mach(struct thread *thread);
extern void thread_get_thread_name(thread_t th, char *name);
#include <kern/clock.h>
static struct { uint64_t tid; uint64_t last; } lv_kt[512];

static void
lv_kthreads(task_t task)
{
	struct { uint64_t tid, d; uint64_t cont, k; char nm[24]; } top[12];
	thread_t thread;
	uint64_t ns;

	bzero(top, sizeof(top));
	task_lock(task);
	queue_iterate(&task->threads, thread, thread_t, task_threads) {
		uint64_t tid = thread->thread_id, t = recount_thread_time_mach(thread), d = 0;
		unsigned slot = (unsigned)(tid % 512), tries = 0;
		while (tries++ < 512 && lv_kt[slot].last != 0 && lv_kt[slot].tid != tid) {
			slot = (slot + 1) % 512;
		}
		if (lv_kt[slot].tid == tid && lv_kt[slot].last != 0 && t >= lv_kt[slot].last) {
			d = t - lv_kt[slot].last;
		}
		lv_kt[slot].tid = tid;
		lv_kt[slot].last = t ? t : 1;
		for (int i = 0; i < 12; i++) {
			if (d > top[i].d) {
				for (int j = 11; j > i; j--) {
					top[j] = top[j - 1];
				}
				char nm[64];
				nm[0] = 0;
				thread_get_thread_name(thread, nm);
				top[i].tid = tid;
				top[i].d = d;
				top[i].cont = (uint64_t)VM_KERNEL_ADDRHIDE(thread->continuation);
				top[i].k = 0;
				if ((thread->state & TH_RUN) == 0 && thread->kernel_stack != 0) {
					top[i].k = (uint64_t)VM_KERNEL_ADDRHIDE(((thread_kernel_state_t)thread->machine.kstackptr)->machine.ss.lr);
				}
				strlcpy(top[i].nm, nm, sizeof(top[i].nm));
				break;
			}
		}
	}
	task_unlock(task);
	for (int i = 0; i < 12 && top[i].d != 0; i++) {
		absolutetime_to_nanoseconds(top[i].d, &ns);
		printf("SMT kernel_task tid %llu ms %llu name %s cont 0x%llx k 0x%llx\\n", top[i].tid, ns / 1000000,
		    top[i].nm[0] ? top[i].nm : "-", top[i].cont, top[i].k);
	}
}

void
sweet_sample_task(const char *name, int pid, task_t task)
{
	if (task == kernel_task) {
		lv_kthreads(task);
		return;
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
