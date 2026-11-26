"""lavender: the WLAN firmware's MSA memory is zeroed before it is handed over (patch 1056).

Where the hang at WLFW "cap" stands: the chip's supplies and clock are on (1054), the Wi-Fi
stream has its SMMU bank (1055), the message sequence is Android's icnss sequence (checked against
drivers/soc/qcom/icnss.c of the phone's kernel source) - and the firmware still hangs, and its
MSA_READY indication never comes. What Android has and we do not: a cold start. With fastboot boot
the RAM keeps what the last system left, and 0x85700000 + 1 MB is the WLAN firmware's own state
area (Android dumps it as "wcss_msa0"); a firmware that finds its old state there may take a
restart path. The region is zeroed while it is still ours, just before the assignment
(modem_msa0=0 skips that). ind_register also sets pin_connect_result_enable, as icnss does.

usage: python mk_wlanmsa0.py XNU_TREE   (after mk_wlansmmu.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	IOSleep(20);                                /* ath10k: give the modem time before the XPU update */
''', '''	IOSleep(20);                                /* ath10k: give the modem time before the XPU update */
	static bool msa_cleared;
	uint32_t clear = 1;
	(void)PE_parse_boot_argn("modem_msa0", &clear, sizeof(clear));
	if (!msa_cleared && clear != 0) {
		/* lavender: no stale firmware state from the system that ran before this fastboot boot */
		IOMemoryMap *mm = map_phys(WLFW_MSA_BASE, WLFW_MSA_SIZE, true);
		if (mm != NULL) {
			volatile uint32_t *w = (volatile uint32_t *)mm->getVirtualAddress();
			uint32_t nz = 0;
			for (uint32_t i = 0; i < WLFW_MSA_SIZE / 4; i++) {
				nz += w[i] != 0;
			}
			LOG("wlfw: MSA %x+%x had %u non-zero words (first %08x %08x %08x %08x), zeroed", WLFW_MSA_BASE, WLFW_MSA_SIZE, nz,
			    w[0], w[1], w[2], w[3]);
			bzero((void *)mm->getVirtualAddress(), WLFW_MSA_SIZE);
			mb();
			mm->release();
			msa_cleared = true;
		}
	}
''')
sub('''		wm_u8(&m, 0x13, 1);                     /* msa_ready_enable */
		wm_u32(&m, 0x15, WLFW_CLIENT_ID);       /* client_id */
		wm_send(&m);
		w_step = "ind_register sent";
''', '''		wm_u8(&m, 0x13, 1);                     /* msa_ready_enable */
		wm_u8(&m, 0x14, 1);                     /* pin_connect_result_enable (icnss) */
		wm_u32(&m, 0x15, WLFW_CLIENT_ID);       /* client_id */
		wm_send(&m);
		w_step = "ind_register sent";
''')
open(path, 'w', newline='\n').write(s)
print('ok')
