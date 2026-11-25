"""lavender: Sandbox "container path" answers an empty string for a process without a container (patch 1039).

syncdefaultsd died again and again (NSInvalidArgumentException, -[NSURL initFileURLWithPath:
isDirectory:]: nil string parameter; text found with sweetscan=syncdefaultsd, 2026-11-26). It asks
sandbox_container_path_for_audit_token() about each client and takes the buffer as a path when the
call succeeds and the first byte is not zero. Our answer for a process with no CFFIXED_USER_HOME
(any daemon) was success with the buffer untouched: the caller's stack garbage became the path.
Now the buffer is an empty string before anything else, as the real Sandbox leaves it for a
process that has no container.

usage: python mk_nocontainer.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/kern/topaz_sandbox_container.c'
s = open(path, newline='').read()
old = '''	p = proc_find((int)args.pid);
'''
assert s.count(old) == 1
s = s.replace(old, '''	if (args.size != 0) {
		/* lavender: no container = an empty string, never the caller's old bytes (xnu/src/mk_nocontainer.py) */
		const char none = 0;
		error = copyout(&none, args.buffer, 1);
		if (error) {
			return error;
		}
	}
''' + old)
open(path, 'w', newline='\n').write(s)
print('ok')
