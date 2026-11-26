"""lavender: sweetstderr=NAME copies what a process writes to stderr into the kernel log (patch 1058).

A daemon's stderr is /dev/null, and the unified log does not reach the USB log. With the
environment variable OS_ACTIVITY_DT_MODE=YES a process mirrors its os_log lines to stderr; this
tap prints them (write and writev to descriptor 2, the first 480 bytes of each call) as
"|NAME| text" for processes whose name starts with NAME. Used to read CommCenter's and the
baseband manager's own account of what they wait for (telephony, docs/MODEM-PLAN.md).

- bsd/kern/sys_generic.c: sweet_stderr_tap() called from write_nocancel() and writev_nocancel()

usage: python mk_stderr.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/kern/sys_generic.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''int
write_nocancel(struct proc *p, struct write_nocancel_args *uap, user_ssize_t *retval)
{
''', '''/* lavender (xnu/src/mk_stderr.py): sweetstderr=NAME prints that process's stderr writes */
extern boolean_t PE_parse_boot_argn(const char *arg_string, void *arg_ptr, int max_arg);
static char sweet_stderr_name[32];
static int sweet_stderr_on = -1;

static int
sweet_stderr_wanted(struct proc *p)
{
	if (sweet_stderr_on < 0) {
		sweet_stderr_on = PE_parse_boot_argn("sweetstderr", sweet_stderr_name, sizeof(sweet_stderr_name)) &&
		    sweet_stderr_name[0] != 0;
	}
	return sweet_stderr_on > 0 && strncmp(p->p_comm, sweet_stderr_name, strlen(sweet_stderr_name)) == 0;
}

static void
sweet_stderr_tap(struct proc *p, user_addr_t buf, user_size_t len)
{
	char line[481];
	size_t n = len < sizeof(line) - 1 ? (size_t)len : sizeof(line) - 1;

	if (n == 0 || copyin(buf, line, n) != 0) {
		return;
	}
	while (n > 0 && (line[n - 1] == '\\n' || line[n - 1] == '\\r')) {
		n--;
	}
	line[n] = 0;
	for (size_t i = 0; i < n; i++) {
		if (line[i] == '\\n' || line[i] == '\\r' || line[i] == '\\t') {
			line[i] = ' ';
		} else if ((unsigned char)line[i] < 0x20) {
			line[i] = '.';
		}
	}
	printf("|%s| %s\\n", p->p_comm, line);
}

int
write_nocancel(struct proc *p, struct write_nocancel_args *uap, user_ssize_t *retval)
{
	if (uap->fd == 2 && sweet_stderr_wanted(p)) {
		sweet_stderr_tap(p, uap->cbuf, uap->nbyte);
	}
''')
sub('''int
writev_nocancel(struct proc *p, struct writev_nocancel_args *uap, user_ssize_t *retval)
{
''', '''int
writev_nocancel(struct proc *p, struct writev_nocancel_args *uap, user_ssize_t *retval)
{
	if (uap->fd == 2 && uap->iovcnt > 0 && sweet_stderr_wanted(p)) {
		struct user64_iovec v[8];
		int cnt = uap->iovcnt < 8 ? uap->iovcnt : 8;
		if (copyin(uap->iovp, v, sizeof(v[0]) * (size_t)cnt) == 0) {
			for (int i = 0; i < cnt; i++) {
				sweet_stderr_tap(p, v[i].iov_base, v[i].iov_len);
			}
		}
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
