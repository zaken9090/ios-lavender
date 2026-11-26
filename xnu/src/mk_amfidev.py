"""lavender: the sweetstderr= process may use the log library's development variables (patch 1061).

Run e62: OS_ACTIVITY_DT_MODE=YES in CommCenter's job produced no line. libsystem_trace honours
that variable only when _os_trace_allow_development_env_vars() says so: it asks AMFI's dyld
policy (__mac_syscall "AMFI", call 0x5a) and wants bit 0x100 of the answer. Our policy answered
0xff. For the process named by sweetstderr= (and only for it) the answer is now 0x1ff.

usage: python mk_amfidev.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/kern/sweet_amfi.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	error = copyin(arg, in_out, sizeof(in_out));
	if (error == 0) {
		error = copyout(&allow, (user_addr_t)in_out[1], sizeof(allow));
''', '''	{
		/* lavender (xnu/src/mk_amfidev.py): bit 0x100 lets the sweetstderr= process mirror its log to stderr */
		extern boolean_t PE_parse_boot_argn(const char *arg_string, void *arg_ptr, int max_arg);
		static char want[32];
		static int on = -1;
		char name[32];
		if (on < 0) {
			on = PE_parse_boot_argn("sweetstderr", want, sizeof(want)) && want[0] != 0;
		}
		if (on > 0) {
			proc_selfname(name, sizeof(name));
			if (strncmp(name, want, strlen(want)) == 0) {
				allow |= 0x100ULL;
			}
		}
	}
	error = copyin(arg, in_out, sizeof(in_out));
	if (error == 0) {
		error = copyout(&allow, (user_addr_t)in_out[1], sizeof(allow));
''')
open(path, 'w', newline='\n').write(s)
print('ok')
