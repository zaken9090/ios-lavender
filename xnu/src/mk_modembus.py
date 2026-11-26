"""lavender: the modem's Q6 also gets its BIMC bus clock (patch 1045).

First start (kernel CI 45732753731): clocks on, both regions assigned, the Q6 power-up sequence ran
(PWR_CTL 0x30c0000, RESET 0x4), yet the boot ROM never reported (PBL status 0). 1044 enabled
gcc_mss_q6_bimc_axi_clk (0x8a040) as "bus"; the stock DT's bus_clk is another clock id than the
snoc/mnoc ones, and the Q6 reads its image through the BIMC port, whose clock is
gcc_bimc_mss_q6_axi_clk (GCC 0x4401c). Both are on now. The gpll0 vote is read back into the log,
and a failed start dumps the registers that tell where it stopped.

usage: python mk_modembus.py XNU_TREE   (after mk_modemmba.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	mss_clk("mss_q6_bimc_axi (bus)", 0x8a040, 1, 0x8a040);
''', '''	mss_clk("mss_q6_bimc_axi", 0x8a040, 1, 0x8a040);
	mss_clk("bimc_mss_q6_axi (bus)", 0x4401c, 1, 0x4401c);
''')
sub('''	mss_clk("mss_snoc_axi", 0x8a03c, 1, 0x8a03c);
''', '''	LOG("gpll0 to the MSS: vote %#x", mss_rd(mss_gcc, 0x5200c));
	mss_clk("mss_snoc_axi", 0x8a03c, 1, 0x8a03c);
''')
sub('''	if (pbl != 1) {
		return false;
	}
''', '''	if (pbl != 1) {
		LOG("no boot ROM status: Q6 GFMUX %#x MEM_PWR %#x BHS %#x STRAP %#x; RMB image %#x pbl %#x cmd %#x mba %#x; halt q6 %#x/%#x/%#x",
		    mss_rd(mss_q6, 0x20), mss_rd(mss_q6, 0x34), mss_rd(mss_q6, 0xc4), mss_rd(mss_q6, 0x110), mss_rd(mss_rmb, 0x00),
		    mss_rd(mss_rmb, 0x04), mss_rd(mss_rmb, 0x08), mss_rd(mss_rmb, 0x0c), mss_rd(mss_halt, 0), mss_rd(mss_halt, 4), mss_rd(mss_halt, 8));
		return false;
	}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
