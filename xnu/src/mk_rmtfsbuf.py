"""lavender: the rmtfs buffer is the phone's own shared-memory region (patch 1049).

Run e47: GLINK, QRTR and the host services answer; the modem opens its four EFS partitions, asks
for the rmtfs buffer, gets an address in our work pool (0xe100a000) and reports FATAL 15 ms later.
On lavender the buffer is a fixed region of the stock device tree, qcom,rmtfs_sharedmem@85e00000,
2 MB, client 1, shared between HLOS and the modem (Linux sharedmem-uio: HLOS + MSS_MSA); topaz's
code took 3 MB from the pool and added the NAV domain. The fixed region is used now.

usage: python mk_rmtfsbuf.py XNU_TREE   (after mk_smemcached.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#define RMTFS_BUF_SIZE      0x300000            /* qcom,rmtfs_sharedmem size */
''', '''#define RMTFS_BUF_SIZE      0x200000            /* lavender: qcom,rmtfs_sharedmem@85e00000 */
#define RMTFS_BUF_PA        0x85E00000ull
''')
sub('''			rmtfs_va = (uint8_t *)pool_alloc(RMTFS_BUF_SIZE, &rmtfs_pa);   /* the modem owns it from now on */
			if (rmtfs_va == NULL) {
				rmtfs_pa = 0;
			} else {
				static const uint32_t v[] = { VMID_HLOS, VMID_MSS_MSA, VMID_NAV };
				(void)scm_assign(rmtfs_pa, RMTFS_BUF_SIZE, v, 3);
			}
''', '''			IOMemoryMap *rm = map_phys(RMTFS_BUF_PA, RMTFS_BUF_SIZE, true);    /* kept for the session */
			rmtfs_va = rm != NULL ? (uint8_t *)rm->getVirtualAddress() : NULL;
			if (rmtfs_va == NULL) {
				rmtfs_pa = 0;
			} else {
				static const uint32_t v[] = { VMID_HLOS, VMID_MSS_MSA };
				rmtfs_pa = RMTFS_BUF_PA;
				bzero(rmtfs_va, RMTFS_BUF_SIZE);
				mb();
				LOG("rmtfs: %llx+%x shared with the modem: %d", rmtfs_pa, RMTFS_BUF_SIZE,
				    (int)scm_assign(rmtfs_pa, RMTFS_BUF_SIZE, v, 2));
			}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
