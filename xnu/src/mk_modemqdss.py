"""lavender: the RPM's QDSS clock is voted on before the modem's Q6 starts (patch 1046).

Second start (kernel CI 45733753598, BIMC clock on): the kernel panicked within the second after
the Q6 was released - "Unhandled implementation specific error" (an SError) on another CPU, the
last modem line being "assign MBA ... ret=0". The first start, where the Q6 could not fetch its
image, did not. So the boot ROM / MBA ran and something it touched answered with a bus error.
Linux holds three "proxy" clocks while the MBA boots an SDM660 modem: xo, qdss, mem
(qcom_q6v5_mss.c, sdm660_mss). xo and mem were on; qdss (the trace block the MBA writes to) is an
RPM clock nobody had asked for: resource "clk0" (0x306b6c63) id 1, key "STAT" (0x54415453)
(clk-smd-rpm.c, DEFINE_CLK_SMD_RPM_QDSS). It is voted on (value 1, active set) before the MSS is
touched; the answer of the RPM goes to the log. Two more log lines bracket the release of the core.

usage: python mk_modemqdss.py XNU_TREE   (after mk_modembus.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static bool
mss_mba_start(void)
{
''', '''extern "C" bool topaz_rpm_write(uint32_t set, uint32_t type, uint32_t id, uint32_t key, uint32_t value);

static bool
mss_mba_start(void)
{
	/* Linux's proxy clock "qdss": RPM resource clk0 id 1, key STAT */
	bool qdss = topaz_rpm_write(0, 0x306b6c63u, 1, 0x54415453u, 1);
	LOG("RPM qdss clock on: %s", qdss ? "acked" : "FAILED");
	if (!qdss) {
		return false;
	}
	IOSleep(20);
''')
sub('''	mss_wr(mss_q6, 0x14, mss_rd(mss_q6, 0x14) & ~1u);               /* run */
''', '''	LOG("Q6 powered (PWR_CTL %#x RESET %#x), releasing the core", mss_rd(mss_q6, 0x30), mss_rd(mss_q6, 0x14));
	IOSleep(50);                                                    /* the line reaches the PC first */
	mss_wr(mss_q6, 0x14, mss_rd(mss_q6, 0x14) & ~1u);               /* run */
''')
open(path, 'w', newline='\n').write(s)
print('ok')
