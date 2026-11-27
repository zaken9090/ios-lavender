"""lavender: names for our kernel threads, right stacks in SMT lines (patch 1144).

1142's SMT lines showed one unnamed kernel thread at ~15% of a core, but our driver threads have no
names, and a thread entered the top list kept the previous entry's stack when it had none of its own
(running): the stacks were someone else's. Now every driver thread started with kernel_thread_start
is named after its function, the stack slots are cleared, and a running thread says "run".

usage: python mk_kthreadnames.py XNU_TREE
"""
import re
import sys

tree = sys.argv[1]

FILES = [
    'bsd/dev/redwood_net.c', 'bsd/dev/sweet_sample.c', 'bsd/dev/sweet_touch.c', 'bsd/dev/sweet_ufs.c',
    'bsd/dev/sweet_usb.c', 'bsd/dev/topaz_sta.c', 'iokit/Kernel/arm/LavenderAudio.cpp',
    'iokit/Kernel/arm/LavenderBT.cpp', 'iokit/Kernel/arm/LavenderIOAudio2.cpp',
    'iokit/Kernel/arm/LavenderThermal.cpp', 'iokit/Kernel/arm/SweetBusy.cpp',
    'iokit/Kernel/arm/SweetFramebuffer.cpp', 'iokit/Kernel/arm/TopazAdreno.cpp',
    'iokit/Kernel/arm/TopazAudio.cpp', 'iokit/Kernel/arm/TopazModem.cpp', 'iokit/Kernel/arm/TopazRpm.cpp',
]
PAT = re.compile(r'(if \(kernel_thread_start\(\s*&?([\w:]+)\s*,\s*[^,]+,\s*&(\w+)\) == KERN_SUCCESS\) \{\n)(\s*)')
total = 0
for f in FILES:
    path = f'{tree}/{f}'
    s = open(path, newline='').read()
    n = 0

    def rep(m):
        global n
        name = m.group(2).split('::')[-1][:31]
        return f'{m.group(1)}{m.group(4)}thread_set_thread_name({m.group(3)}, "{name}");      /* lavender: mk_kthreadnames.py */\n{m.group(4)}'
    s2, n = PAT.subn(rep, s)
    assert n >= 1, f
    decl = ('extern "C" void thread_set_thread_name(struct thread *th, const char *name);   /* lavender: mk_kthreadnames.py */\n'
            if f.endswith('.cpp') else
            'extern void thread_set_thread_name(struct thread *th, const char *name);       /* lavender: mk_kthreadnames.py */\n')
    # declare after the first #include line (struct thread: no header needed)
    last = re.search(r'^#include [^\n]*\n', s2, re.M).end()
    s2 = s2[:last] + decl + s2[last:]
    open(path, 'w', newline='\n').write(s2)
    total += n
    print(f, n)

path = f'{tree}/osfmk/kern/exception.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''				top[i].k = 0;
				if (''', '''				top[i].k = 0;
				bzero(top[i].bt, sizeof(top[i].bt));   /* (mk_kthreadnames.py: not the previous entry's) */
				if (thread->state & TH_RUN) {
					top[i].k = 1;                   /* running: no saved stack */
				}
				if (''')
open(path, 'w', newline='\n').write(s)
print('ok', total)
