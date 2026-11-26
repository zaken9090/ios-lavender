"""lavender: the stderr tap also sees the log library's own descriptor (patch 1060).

Run e60: with OS_ACTIVITY_DT_MODE=YES no line of CommCenter came through descriptor 2. The log
library writes through its own copy of stderr, so the tap now takes write/writev on any
descriptor of the named process when the text starts with a date ("20YY-MM-DD ..."), which is
how those lines start; descriptor 2 is still taken whole.

usage: python mk_stderr2.py XNU_TREE   (after mk_stderr.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/kern/sys_generic.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static void
sweet_stderr_tap(struct proc *p, user_addr_t buf, user_size_t len)
{
	char line[481];
	size_t n = len < sizeof(line) - 1 ? (size_t)len : sizeof(line) - 1;

	if (n == 0 || copyin(buf, line, n) != 0) {
		return;
	}
''', '''static int
sweet_stderr_tap(struct proc *p, user_addr_t buf, user_size_t len, int whole)
{
	char line[481];
	size_t n = len < sizeof(line) - 1 ? (size_t)len : sizeof(line) - 1;

	if (n == 0 || copyin(buf, line, n) != 0) {
		return 0;
	}
	/* not stderr: only text that starts with a date, as the log library's lines do */
	if (!whole && !(n > 10 && line[0] == '2' && line[1] == '0' && line[4] == '-' && line[7] == '-')) {
		return 0;
	}
''')
sub('''	printf("|%s| %s\\n", p->p_comm, line);
}
''', '''	printf("|%s| %s\\n", p->p_comm, line);
	return 1;
}
''')
sub('''	if (uap->fd == 2 && sweet_stderr_wanted(p)) {
		sweet_stderr_tap(p, uap->cbuf, uap->nbyte);
	}
''', '''	if (sweet_stderr_wanted(p)) {
		(void)sweet_stderr_tap(p, uap->cbuf, uap->nbyte, uap->fd == 2);
	}
''')
sub('''	if (uap->fd == 2 && uap->iovcnt > 0 && sweet_stderr_wanted(p)) {''', '''	if (uap->iovcnt > 0 && sweet_stderr_wanted(p)) {''')
sub('''			for (int i = 0; i < cnt; i++) {
				sweet_stderr_tap(p, v[i].iov_base, v[i].iov_len);
			}
''', '''			int take = sweet_stderr_tap(p, v[0].iov_base, v[0].iov_len, uap->fd == 2);
			for (int i = 1; i < cnt && (take || uap->fd == 2); i++) {
				(void)sweet_stderr_tap(p, v[i].iov_base, v[i].iov_len, 1);
			}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
