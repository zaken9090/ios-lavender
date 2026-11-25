"""lavender: the process sampler also shows where each waiting thread is in the kernel (patch 1017).

sweet_sample_task() (osfmk/kern/exception.c, from the base) prints each thread's user pc and
backtrace ("SMP name tN ..."). A thread blocked in the kernel shows only the syscall stub there.
Now a second line follows for a thread that is not running:

  SMK name tN st 0x<state> hint <block_hint> ev 0x<wait_event, unslid when static> k 0x<lr> 0x<caller> ...

state: TH_WAIT 0x1, TH_SUSP 0x2, TH_RUN 0x4, TH_UNINT 0x8. The kernel frames come from the
thread's saved kernel context (fp/lr at the top of its kernel stack), walked inside its stack only,
and are unslid: symbolize them with the kernel's own symbols (tools/ksym.py).

usage: python mk_ksample.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/osfmk/kern/exception.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		printf("%s\\n", line);
	}
	task_unlock(task);
}
''', '''		printf("%s\\n", line);

		/* lavender: where a waiting thread is in the kernel (xnu/src/mk_ksample.py) */
		int st = thread->state;
		vm_offset_t ks = thread->kernel_stack;
		if ((st & TH_RUN) == 0 && ks != 0) {
			struct arm_kernel_saved_state *kss = &((thread_kernel_state_t)thread->machine.kstackptr)->machine.ss;
			uint64_t kfp = kss->fp;
			n = snprintf(line, sizeof(line), "SMK %s t%d st 0x%x hint %d ev 0x%llx k 0x%llx", name, tn - 1, st,
			    (int)thread->block_hint, (uint64_t)VM_KERNEL_ADDRHIDE(thread->wait_event),
			    (uint64_t)VM_KERNEL_ADDRHIDE(kss->lr));
			for (int i = 0; i < 20 && n < (int)sizeof(line) - 20; i++) {
				if (kfp < ks || kfp + 16 > ks + kernel_stack_size || (kfp & 7) != 0) {
					break;
				}
				uint64_t next = ((uint64_t *)kfp)[0], lr = ((uint64_t *)kfp)[1];
				if (lr == 0) {
					break;
				}
				n += snprintf(line + n, sizeof(line) - n, " 0x%llx", (uint64_t)VM_KERNEL_ADDRHIDE(lr));
				if (next <= kfp) {
					break;
				}
				kfp = next;
			}
			printf("%s\\n", line);
		}
	}
	task_unlock(task);
}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
