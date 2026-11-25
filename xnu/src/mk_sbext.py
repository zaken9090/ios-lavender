'''lavender: Sandbox extensions are issued and consumed (patch 1041).

assetsd died at start: NSInternalInconsistencyException "assetsd requires TCCPhotosService access"
(text from sweetscan=assetsd, 2026-11-26). It holds com.apple.private.tcc.allow for
kTCCServicePhotos; tccd answered "error" because granting access includes issuing a sandbox
extension, and our permissive Sandbox policy failed op 5 (issue) and op 6 (consume) with ENOENT.
There is no sandbox to extend here, so issue now returns a token ("lavender;<class>") and consume
returns a handle; nothing is recorded, as every access is allowed anyway.

  op 5 arguments: { class string, type, data, flags, token buffer (0x800 bytes), pid, pid version }
  op 6 arguments: { token string, its length, pointer to the 64-bit handle }

usage: python mk_sbext.py XNU_TREE
'''
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/kern/sweet_amfi.c'
s = open(path, newline='').read()
old = '''	case 5:         /* extension issue */
	case 6:         /* extension consume */
	case 0x43:      /* container expected */
		return ENOENT;
'''
assert s.count(old) == 1
s = s.replace(old, '''	case 5: {       /* extension issue: lavender answers a token (xnu/src/mk_sbext.py) */
		struct {
			user_addr_t cls;
			uint64_t    type;
			user_addr_t data;
			uint64_t    flags;
			user_addr_t token;
			uint64_t    pid;
			uint64_t    pidversion;
		} a;
		char token[160] = "lavender;";
		size_t done = 0;
		int error = copyin(arg, &a, sizeof(a));
		if (error) {
			return error;
		}
		if (a.cls != 0) {
			(void)copyinstr(a.cls, token + 9, sizeof(token) - 9, &done);
			token[sizeof(token) - 1] = 0;
		}
		return a.token != 0 ? copyout(token, a.token, strlen(token) + 1) : EINVAL;
	}
	case 6: {       /* extension consume: a handle, nothing to extend */
		struct {
			user_addr_t token;
			uint64_t    length;
			user_addr_t handle;
		} a;
		static uint64_t handles;
		uint64_t handle = ++handles;
		int error = copyin(arg, &a, sizeof(a));
		if (error) {
			return error;
		}
		return a.handle != 0 ? copyout(&handle, a.handle, sizeof(handle)) : 0;
	}
	case 0x43:      /* container expected */
		return ENOENT;
''')
open(path, 'w', newline='\n').write(s)
print('ok')
