"""lavender: SDM660 addresses and the MBA way of starting the modem (patch 1044).

Steps 2 and 3 of docs/MODEM-PLAN.md. TopazModem.cpp started topaz's modem (SM6225) with TrustZone's
PAS calls. lavender's modem (stock DT qcom,pil-q6v55-mss, qcom,pil-self-auth) is started the older
way, as Linux qcom_q6v5_mss.c does for MSS_SDM660: the kernel takes the Q6 out of reset itself
with mba.mbn in place, and the MBA then authenticates modem.mdt and the segments through the RMB
registers. Memory changes hands with SCM assign calls (HLOS <-> MSS_MSA).

- addresses: SMEM 0x86000000, TCSR mutex 0x1F40000, APCS 0x17911000, pool 0xE1000000 (16 MB right
  after the GPU pool), MPSS 0x8AC00000 + 0x7E00000, MBA 0x94800000 + 0x200000, WLAN MSA 0x85700000,
  GLINK doorbell bit 15
- mss_mba_start(): MSS restart released, GCC clocks, mba.mbn, Q6 power-up sequence, PBL and MBA status
- modem_boot(): metadata and segments through the RMB instead of PAS
- cx/mx and the RPM clocks (xo, qdss) are not voted yet: the rails and xo are up for the CPU
- modem=1 goes all the way again (the modem_go stop of 1043 is gone)

usage: python mk_modemmba.py XNU_TREE   (after mk_modemfat.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


# ---- addresses
sub('''#define MODEM_POOL_BASE     0xE0000000ull''', '''#define MODEM_POOL_BASE     0xE1000000ull       /* lavender: right after the GPU pool (0xA1000000 + 1 GB) */''')
sub('''#define SMEM_PA             0x46000000ull''', '''#define SMEM_PA             0x86000000ull       /* lavender (SDM660) */''')
sub('''#define TCSR_MUTEX_PA       0x00340000ull''', '''#define TCSR_MUTEX_PA       0x01F40000ull''')
sub('''#define APCS_PA             0x0F111000ull''', '''#define APCS_PA             0x17911000ull''')
sub('''#define GLINK_IRQ_BIT       12''', '''#define GLINK_IRQ_BIT       15                  /* lavender: glink-smem-native-xprt-modem mask 0x8000 */''')
sub('''#define WLFW_MSA_BASE       0x51900000u''', '''#define WLFW_MSA_BASE       0x85700000u''')

# ---- the stop of 1043 goes
sub('''	uint32_t go = 0;
	(void)PE_parse_boot_argn("modem_go", &go, sizeof(go));
	if (err == 0 && !go) {
		/* lavender: the addresses below are still topaz's (docs/MODEM-PLAN.md step 2) */
		LOG("firmware found; the modem is not started (modem_go=1 would, with another phone's addresses)");
		return false;
	}
''', '')

# ---- the MBA start, before modem_boot()
sub('''static bool
modem_boot(void)
{
''', '''/*
 * lavender: the modem's Q6 started by hand with the MBA (xnu/src/mk_modemmba.py, docs/MODEM-PLAN.md).
 */
#define MSS_GCC_PA          0x00100000ull
#define MSS_Q6_PA           0x04080000ull
#define MSS_RMB_PA          0x04180000ull
#define MSS_HALT_PA         0x01F63000ull       /* q6 +0, nc +0x1000, modem +0x2000: HALTREQ, HALTACK, IDLE */
#define MSS_MBA_PA          0x94800000ull
#define MSS_MBA_SIZE        0x00200000ull
#define MSS_MPSS_PA         0x8AC00000ull
#define MSS_MPSS_SIZE       0x07E00000ull
#define MSS_VMID_HLOS       3
#define MSS_VMID_MSA        15

static volatile uint8_t *mss_gcc, *mss_q6, *mss_rmb, *mss_halt;

static inline uint32_t
mss_rd(volatile uint8_t *b, uint32_t off)
{
	return *(volatile uint32_t *)(b + off);
}

static inline void
mss_wr(volatile uint8_t *b, uint32_t off, uint32_t v)
{
	*(volatile uint32_t *)(b + off) = v;
	mb();
}

/* hyp-assign with the owners named: HLOS has read-write-execute, the modem read-write (Linux q6v5_xfer_mem_ownership) */
static bool
mss_assign(const char *what, uint64_t addr, uint64_t size, bool from_hlos, bool from_msa, bool to_hlos, bool to_msa)
{
	uint64_t pa = 0;
	uint64_t *p = (uint64_t *)pool_alloc(0x1000, &pa);
	unsigned nsrc = 0, ndst = 0;

	if (p == NULL) {
		return false;
	}
	p[0] = addr;
	p[1] = (size + 0xfff) & ~0xfffull;
	uint32_t *src = (uint32_t *)(p + 8);
	if (from_hlos) {
		src[nsrc++] = MSS_VMID_HLOS;
	}
	if (from_msa) {
		src[nsrc++] = MSS_VMID_MSA;
	}
	uint32_t *dst = (uint32_t *)(p + 16);
	if (to_hlos) {
		dst[6 * ndst] = MSS_VMID_HLOS;
		dst[6 * ndst++ + 1] = 7;
	}
	if (to_msa) {
		dst[6 * ndst] = MSS_VMID_MSA;
		dst[6 * ndst++ + 1] = 6;
	}
	p[32] = nsrc * 4;
	p[33] = pa + 0x80;
	p[34] = ndst * 24;
	p[35] = 0;
	mb();
	uint64_t args[8] = { SCM_FN(0x0C, 0x16), 7 | (1 << 4) | (1 << 8) | (1 << 12), pa, 16, pa + 0x40, pa + 0x100, 0, 0 };
	smc(args);
	for (unsigned n = 0; args[0] == 1 && n < 100000; n++) {
		uint64_t again[8] = { 1, 7 | (1 << 4) | (1 << 8) | (1 << 12), pa, 16, pa + 0x40, pa + 0x100, args[6], 0 };
		memcpy(args, again, sizeof(args));
		smc(args);
	}
	LOG("assign %s %llx+%llx %s%s -> %s%s: ret=%llx res=%llx", what, addr, size, from_hlos ? "HLOS " : "", from_msa ? "MSA" : "",
	    to_hlos ? "HLOS " : "", to_msa ? "MSA" : "", args[0], args[1]);
	return args[0] == 0 && args[1] == 0;
}

/* an RMB register until it is not 0 (want 0) or equals want; negative = the MBA's error. The value, 0 on a timeout. */
static int32_t
mss_wait(uint32_t reg, int32_t want, unsigned ms)
{
	for (unsigned i = 0; i < ms; i++) {
		int32_t v = (int32_t)mss_rd(mss_rmb, reg);
		if (v < 0 || (want == 0 && v != 0) || (want != 0 && v == want)) {
			return v;
		}
		IOSleep(1);
	}
	return 0;
}

static void
mss_clk(const char *name, uint32_t reg, uint32_t bit, uint32_t status)
{
	mss_wr(mss_gcc, reg, mss_rd(mss_gcc, reg) | bit);
	uint32_t v = 0;
	for (unsigned i = 0; i < 200; i++) {
		v = mss_rd(mss_gcc, status);
		if (!(v & (1u << 31))) {
			break;
		}
		IODelay(10);
	}
	LOG("clock %s: %#x = %#x%s", name, status, v, (v & (1u << 31)) ? " (still off)" : "");
}

static bool
mss_mba_start(void)
{
	IOMemoryMap *g = map_phys(MSS_GCC_PA, 0x90000, false), *q = map_phys(MSS_Q6_PA, 0x1000, false);
	IOMemoryMap *r = map_phys(MSS_RMB_PA, 0x1000, false), *h = map_phys(MSS_HALT_PA, 0x3000, false);
	if (g == NULL || q == NULL || r == NULL || h == NULL) {
		LOG("MSS registers: mapping failed");
		return false;
	}
	mss_gcc = (volatile uint8_t *)g->getVirtualAddress();
	mss_q6 = (volatile uint8_t *)q->getVirtualAddress();
	mss_rmb = (volatile uint8_t *)r->getVirtualAddress();
	mss_halt = (volatile uint8_t *)h->getVirtualAddress();
	LOG("MSS before: restart %#x, cfg_ahb %#x, vote %#x/%#x", mss_rd(mss_gcc, 0x79000), mss_rd(mss_gcc, 0x8a000),
	    mss_rd(mss_gcc, 0x52004), mss_rd(mss_gcc, 0x5200c));

	mss_wr(mss_gcc, 0x79000, 0);                    /* GCC_MSS_RESTART released */
	IODelay(1000);
	mss_clk("mss_cfg_ahb (iface)", 0x8a000, 1, 0x8a000);
	LOG("Q6 before: RESET %#x PWR_CTL %#x; RMB pbl %#x mba %#x", mss_rd(mss_q6, 0x14), mss_rd(mss_q6, 0x30),
	    mss_rd(mss_rmb, 0x04), mss_rd(mss_rmb, 0x0c));
	mss_clk("mss_q6_bimc_axi (bus)", 0x8a040, 1, 0x8a040);
	mss_clk("boot_rom_ahb (mem)", 0x52004, 1u << 10, 0x38004);
	mss_wr(mss_gcc, 0x5200c, mss_rd(mss_gcc, 0x5200c) | (1u << 2));        /* gpll0 to the MSS (downstream gpll0_out_msscc) */
	mss_clk("mss_snoc_axi", 0x8a03c, 1, 0x8a03c);
	mss_clk("mss_mnoc_bimc_axi", 0x8a004, 1, 0x8a004);
	for (unsigned i = 0; i < 3; i++) {
		mss_wr(mss_halt, 0x1000 * i, 0);        /* no AXI halt requests left over */
	}

	/* mba.mbn as it is, then the region and the modem's own memory go to the modem */
	IOMemoryMap *m = map_phys(MSS_MBA_PA, MSS_MBA_SIZE, true);
	int64_t got = m != NULL ? fw_read("mba.mbn", (void *)m->getVirtualAddress(), MSS_MBA_SIZE) : -1;
	mb();
	OSSafeReleaseNULL(m);
	LOG("mba.mbn: %lld bytes at %llx", got, MSS_MBA_PA);
	if (got <= 0) {
		return false;
	}
	if (!mss_assign("MPSS", MSS_MPSS_PA, MSS_MPSS_SIZE, true, false, false, true) ||
	    !mss_assign("MBA", MSS_MBA_PA, MSS_MBA_SIZE, true, false, false, true)) {
		return false;
	}
	mss_wr(mss_rmb, 0x00, (uint32_t)MSS_MBA_PA);    /* RMB_MBA_IMAGE */

	/* the Q6's reset sequence (Linux q6v5proc_reset(), MSS_SDM660) */
	uint32_t v;
	mss_wr(mss_q6, 0x110, 0x20);                    /* STRAP_ACC */
	mss_wr(mss_q6, 0x14, mss_rd(mss_q6, 0x14) | 7); /* core and bus in reset, core stopped */
	mss_wr(mss_q6, 0x38, mss_rd(mss_q6, 0x38) | 1); /* XO clock */
	for (unsigned i = 0; i < 200 && (mss_rd(mss_q6, 0x38) & (1u << 31)); i++) {
		IODelay(10);
	}
	mss_wr(mss_q6, 0x30, mss_rd(mss_q6, 0x30) | (1u << 24));        /* BHS on */
	(void)mss_rd(mss_q6, 0x30);
	IODelay(1);
	for (unsigned i = 0; i < 200 && !(mss_rd(mss_q6, 0xc4) & 1); i++) {
		IODelay(1);
	}
	bool bhs = (mss_rd(mss_q6, 0xc4) & 1) != 0;
	mss_wr(mss_q6, 0x30, mss_rd(mss_q6, 0x30) | (1u << 25));        /* LDO bypass */
	mss_wr(mss_q6, 0x30, mss_rd(mss_q6, 0x30) & ~(1u << 22));       /* QMC memory clamp off */
	mss_wr(mss_q6, 0x30, mss_rd(mss_q6, 0x30) | (1u << 18) | (1u << 19));
	v = mss_rd(mss_q6, 0x34);
	for (int i = 28; i >= 0; i--) {                 /* memories on, one at a time */
		v |= 1u << i;
		mss_wr(mss_q6, 0x34, v);
		v |= mss_rd(mss_q6, 0x34);
		IODelay(1);
	}
	mss_wr(mss_q6, 0x30, mss_rd(mss_q6, 0x30) & ~(1u << 21));       /* word-line clamp off */
	mss_wr(mss_q6, 0x30, mss_rd(mss_q6, 0x30) & ~(1u << 20));       /* I/O clamp off */
	mss_wr(mss_q6, 0x14, mss_rd(mss_q6, 0x14) & ~2u);               /* core out of reset */
	mss_wr(mss_q6, 0x20, mss_rd(mss_q6, 0x20) | 2);                 /* core clock */
	mss_wr(mss_q6, 0x14, mss_rd(mss_q6, 0x14) & ~1u);               /* run */

	int32_t pbl = mss_wait(0x04, 0, 1000);
	LOG("Q6 started: xo %#x bhs %u PWR_CTL %#x RESET %#x; PBL status %d (1 = success)", mss_rd(mss_q6, 0x38), bhs,
	    mss_rd(mss_q6, 0x30), mss_rd(mss_q6, 0x14), pbl);
	if (pbl != 1) {
		return false;
	}
	int32_t mba = mss_wait(0x0c, 0, 5000);
	LOG("MBA status %d (1 or 2 = running)", mba);
	if (mba != 1 && mba != 2) {
		return false;
	}
	mss_wr(mss_rmb, 0x18, 0);                       /* RMB_PMI_CODE_LENGTH */
	return true;
}

static bool
modem_boot(void)
{
''')

# ---- modem_boot(): PAS -> RMB
sub('''	st = scm(SCM_FN(SCM_SVC_PIL, PIL_IS_SUPPORTED), 1, PAS_ID_MODEM, 0, 0, &res);
	LOG("PAS id %u supported: ret=%llx res=%llx", PAS_ID_MODEM, st, res);
	/* informational only: on topaz TZ answers res=0 here, init_image decides */
''', '''	st = 0;
	(void)st;
	(void)res;
	uint64_t reloc, boot_addr, loaded = 0;
	bool first = true;
	if (!mss_mba_start()) {
		return false;
	}
''')
sub('''		if (hash == ~0u || min_a < 0x4AB00000u || max_a > 0x4AB00000u + 0x6900000u) {
			LOG("unexpected layout (carveout is 0x4ab00000+0x6900000)");
			goto out;
		}
''', '''		if (hash == ~0u || max_a - min_a > MSS_MPSS_SIZE ||
		    (!relocate && (min_a < MSS_MPSS_PA || max_a > MSS_MPSS_PA + MSS_MPSS_SIZE))) {
			LOG("unexpected layout (the modem's memory is %llx+%llx)", MSS_MPSS_PA, MSS_MPSS_SIZE);
			goto out;
		}
		reloc = relocate ? min_a : MSS_MPSS_PA;
		boot_addr = relocate ? MSS_MPSS_PA : min_a;
''')
sub('''		st = scm(SCM_FN(SCM_SVC_PIL, PIL_INIT_IMAGE), 2 | (SCM_ARG_RW << 6), PAS_ID_MODEM, meta_pa, 0, &res);
		LOG("init_image: ret=%llx res=%llx resumes=%u (meta %llu bytes @%llx)", st, res, scm_resumes, meta_size, meta_pa);
		if (st != 0 || res != 0) {
			goto out;
		}
		if (relocate) {
			st = scm(SCM_FN(SCM_SVC_PIL, PIL_MEM_SETUP), 3, PAS_ID_MODEM, min_a,
			    ((uint64_t)(max_a - min_a) + 0xfff) & ~0xfffull, &res);
			LOG("mem_setup: ret=%llx res=%llx", st, res);
			if (st != 0 || res != 0) {
				goto shutdown;
			}
		}
''', '''		/* lavender: the MBA reads the metadata out of memory that is the modem's while it does */
		if (!mss_assign("metadata", meta_pa, meta_size, true, false, false, true)) {
			goto out;
		}
		mss_wr(mss_rmb, 0x10, (uint32_t)meta_pa);       /* RMB_PMI_META_DATA */
		mss_wr(mss_rmb, 0x08, 1);                       /* metadata ready */
		{
			int32_t auth = mss_wait(0x0c, 3, 1000);
			LOG("metadata (%llu bytes @%llx): MBA status %d (3 = authenticated)", meta_size, meta_pa, auth);
			(void)mss_assign("metadata", meta_pa, meta_size, false, true, true, false);
			if (auth != 3) {
				goto shutdown;
			}
		}
		/* the modem's memory shared while the segments are copied in */
		if (!mss_assign("MPSS", MSS_MPSS_PA, MSS_MPSS_SIZE, false, true, true, false) ||
		    !mss_assign("MPSS", MSS_MPSS_PA, MSS_MPSS_SIZE, true, false, true, true)) {
			goto shutdown;
		}
''')
sub('''			uint64_t pa = ph[i].p_paddr & ~0x3fffull, off = ph[i].p_paddr - pa;
''', '''			uint64_t at = MSS_MPSS_PA + (ph[i].p_paddr - reloc);
			uint64_t pa = at & ~0x3fffull, off = at - pa;
''')
sub('''			mb();
			m->release();
		}
		LOG("segments loaded");

		st = scm(SCM_FN(SCM_SVC_PIL, PIL_AUTH_RESET), 1, PAS_ID_MODEM, 0, 0, &res);
		LOG("auth_and_reset: ret=%llx res=%llx resumes=%u", st, res, scm_resumes);
		if (st != 0 || res != 0) {
			goto shutdown;
		}
		ok = true;
		goto out;
''', '''			mb();
			m->release();
			/* lavender: tell the MBA how far the image has got (Linux q6v5_mpss_load()) */
			loaded += ph[i].p_memsz;
			if (first) {
				first = false;
				mss_wr(mss_rmb, 0x14, (uint32_t)boot_addr);     /* RMB_PMI_CODE_START */
				mss_wr(mss_rmb, 0x08, 2);                       /* load ready */
			}
			mss_wr(mss_rmb, 0x18, (uint32_t)loaded);                /* RMB_PMI_CODE_LENGTH */
			int32_t sst = (int32_t)mss_rd(mss_rmb, 0x0c);
			LOG("segment %u: %x+%x at %llx, MBA status %d", i, ph[i].p_paddr, ph[i].p_memsz, at, sst);
			if (sst < 0) {
				goto shutdown;
			}
		}
		LOG("segments loaded: %llu bytes, boot address %llx", loaded, boot_addr);

		if (!mss_assign("MPSS", MSS_MPSS_PA, MSS_MPSS_SIZE, true, true, false, true)) {
			goto shutdown;
		}
		{
			int32_t done = mss_wait(0x0c, 4, 10000);
			LOG("MBA status %d (4 = the modem is authenticated and running)", done);
			if (done != 4) {
				goto shutdown;
			}
		}
		ok = true;
		goto out;
''')
sub('''	st = scm(SCM_FN(SCM_SVC_PIL, PIL_SHUTDOWN), 1, PAS_ID_MODEM, 0, 0, &res);
	LOG("shutdown after failure: ret=%llx res=%llx", st, res);
''', '''	LOG("modem start failed: RMB pbl %d mba %d; the Q6 is put back in reset", (int32_t)mss_rd(mss_rmb, 0x04), (int32_t)mss_rd(mss_rmb, 0x0c));
	mss_wr(mss_q6, 0x14, mss_rd(mss_q6, 0x14) | 7);
	mss_wr(mss_gcc, 0x79000, 1);
''')
open(path, 'w', newline='\n').write(s)
print('ok')
