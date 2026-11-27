"""lavender: boot-arg lv_kmsg_sig=0 - Mach messages are not SHA-256 signed and checked (patch 1147).

Without PAC (Cortex-A73) xnu signs every kernel message with a SHA-256 over header, trailer and
descriptors and checks it again on receive; the user's first lavender project measured ~4% of
backboardd in it (its 1035 stubbed it at build time). Here it is a run-time switch, default ON (signed,
as stock); lv_kmsg_sig=0 skips both the signing and the check. Integrity hardening only: messages are
delivered the same either way.

The file is xnu-8796.141.3's osfmk/ipc/ipc_kmsg.c; the tree gets it as an unchanged base commit first.
usage: python mk_kmsgsig.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/osfmk/ipc/ipc_kmsg.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static void
ikm_sign(ipc_kmsg_t kmsg)
{
	ikm_sig_scratch_t scratch;
	uintptr_t sig;

	zone_require(ipc_kmsg_zone, kmsg);
''', '''/* lavender: lv_kmsg_sig=0 - no signature made or checked (xnu/src/mk_kmsgsig.py) */
static TUNABLE(bool, lv_kmsg_sig, "lv_kmsg_sig", true);

static void
ikm_sign(ipc_kmsg_t kmsg)
{
	ikm_sig_scratch_t scratch;
	uintptr_t sig;

	zone_require(ipc_kmsg_zone, kmsg);
	if (!lv_kmsg_sig) {
		return;
	}
''')
sub('''	ikm_sig_scratch_t scratch;
	uintptr_t expected;
	uintptr_t sig;
	char *str;

	zone_require(ipc_kmsg_zone, kmsg);
''', '''	ikm_sig_scratch_t scratch;
	uintptr_t expected;
	uintptr_t sig;
	char *str;

	zone_require(ipc_kmsg_zone, kmsg);
	if (!lv_kmsg_sig) {
		return;
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
