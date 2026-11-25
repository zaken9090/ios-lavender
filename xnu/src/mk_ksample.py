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


# memory: the task's resident size and footprint, and the system's page counts (MB)
sub('''#include <vm/vm_shared_region.h>
''', '''#include <vm/vm_shared_region.h>
#include <vm/vm_page.h>
''')
sub('''	printf("SMP %s[%d] slide 0x%llx mh 0x%llx\\n", name, pid, slide, task->mach_header_vm_address);
''', '''	printf("SMP %s[%d] slide 0x%llx mh 0x%llx\\n", name, pid, slide, task->mach_header_vm_address);
	/* lavender: memory (xnu/src/mk_ksample.py), MB */
#define LV_MB(pages) ((unsigned)(((uint64_t)(pages) * PAGE_SIZE) >> 20))
	printf("SMM %s rss %llu foot %llu | free %u spec %u active %u inactive %u wired %u ext %u int %u target %u throttle %u\\n",
	    name, get_task_resident_size(task) >> 20, get_task_phys_footprint(task) >> 20,
	    LV_MB(vm_page_free_count), LV_MB(vm_page_speculative_count), LV_MB(vm_page_active_count),
	    LV_MB(vm_page_inactive_count), LV_MB(vm_page_wire_count), LV_MB(vm_page_pageable_external_count),
	    LV_MB(vm_page_pageable_internal_count), LV_MB(vm_page_free_target), LV_MB(vm_page_throttle_limit));
''')
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
