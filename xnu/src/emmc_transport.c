/*
 * lavender: SDHCI (SD Host Controller spec 3.0/4.x) registers of the eMMC host, "hc_mem".
 * Accessed with 32-bit reads and writes only: Transfer Mode and Command go out in one write,
 * which is what starts the command.
 */
#define SDHCI_BLOCK             0x04            /* [11:0] block size, [14:12] SDMA boundary, [31:16] count */
#define SDHCI_ARGUMENT          0x08
#define SDHCI_XFER_CMD          0x0c            /* [15:0] transfer mode, [31:16] command */
#define SDHCI_RESPONSE          0x10
#define SDHCI_PRESENT           0x24
#define   PRESENT_CMD_INHIBIT   (1u << 0)
#define   PRESENT_DAT_INHIBIT   (1u << 1)
#define   PRESENT_DAT0          (1u << 20)      /* line level: low while the card is busy */
#define SDHCI_HOST_CTRL1        0x28            /* [7:0] host control 1, [15:8] power, ... */
#define   HC1_DMA_MASK          (3u << 3)
#define   HC1_ADMA2_64          (3u << 3)       /* v3: 64-bit ADMA2 */
#define   HC1_ADMA2             (2u << 3)       /* v4: ADMA2, width from HC2 */
#define SDHCI_CLOCK_CTRL        0x2c            /* [15:0] clock, [23:16] timeout, [31:24] reset */
#define   RESET_CMD             (1u << 25)
#define   RESET_DATA            (1u << 26)
#define SDHCI_INT_STATUS        0x30            /* [15:0] normal, [31:16] error; write 1 to clear */
#define   INT_CMD_COMPLETE      (1u << 0)
#define   INT_XFER_COMPLETE     (1u << 1)
#define   INT_ERROR             (1u << 15)
#define SDHCI_INT_ENABLE        0x34
#define SDHCI_SIGNAL_ENABLE     0x38
#define SDHCI_HOST_CTRL2        0x3c            /* [15:0] auto CMD error, [31:16] host control 2 */
#define   HC2_V4                (1u << 28)
#define   HC2_64BIT             (1u << 29)
#define SDHCI_CAPS              0x40
#define   CAPS_ADMA2            (1u << 19)
#define   CAPS_64BIT_V3         (1u << 28)
#define SDHCI_ADMA_ERROR        0x54
#define SDHCI_ADMA_ADDR_LO      0x58
#define SDHCI_ADMA_ADDR_HI      0x5c
#define SDHCI_VERSION           0xfc            /* [31:16] host version */
#define CQ_CFG                  0x08            /* cmdq_mem: bit 0 command queueing on */

/* Command register: index << 8 | flags. Transfer mode bits. */
#define CMD_RESP_48             2u
#define CMD_RESP_48_BUSY        3u
#define CMD_CRC                 (1u << 3)
#define CMD_INDEX               (1u << 4)
#define CMD_DATA                (1u << 5)
#define R1                      (CMD_RESP_48 | CMD_CRC | CMD_INDEX)
#define R1B                     (CMD_RESP_48_BUSY | CMD_CRC | CMD_INDEX)
#define XFER_DMA                (1u << 0)
#define XFER_BLOCK_COUNT        (1u << 1)
#define XFER_AUTO_CMD12         (1u << 2)
#define XFER_READ               (1u << 4)
#define XFER_MULTI              (1u << 5)
#define R1_ERRORS               0xe4380000u     /* out of range, misalign, block length, WP, ECC, CC, error */

/* ADMA2 descriptor: [15:0] attribute, [31:16] length, then the 64-bit address. */
#define ADMA_VALID_END_TRAN     0x23u

#define MMC_SECTOR              512u
#define MMC_MAX_SECTORS         120u            /* per command: one descriptor (16-bit length), 15 x 4 KiB */
#define UFS_BLOCK               4096u           /* the block size everything above works in */
#define SECTORS_PER_BLOCK       (UFS_BLOCK / MMC_SECTOR)
#define BOUNCE_SIZE             (1u << 20)
#define CMD_TIMEOUT_NS          (5ull * NSEC_PER_SEC)

/* Layout of the contiguous DMA allocation. */
#define DMA_DESC                0x0000          /* one ADMA2 descriptor */
#define DMA_BOUNCE              0x4000
#define DMA_SIZE                (DMA_BOUNCE + BOUNCE_SIZE)

static struct {
	vm_offset_t regs;
	vm_offset_t dma;                        /* kernel VA of the DMA allocation */
	uint64_t dma_pa;
	uint8_t lun;                            /* always 0: one eMMC user area */
	uint64_t first_block, nblocks;          /* partition, in 4 KiB blocks */
	uint64_t sectors;                       /* size of the user area, EXT_CSD SEC_COUNT */
	uint32_t secsize;                       /* logical sector size for the BSD layer */
	bool cache_on;                          /* the card's write cache is enabled */
	bool writable;                          /* boot-arg ufsrw=1 */
	bool cache;                             /* (unused on eMMC) */
	bool wait;                              /* boot-arg ufswait=1: sleep while a command runs */
	int bmajor, cmajor;
	dev_t bdev;
	bool ready;
} su;

static LCK_GRP_DECLARE(sweet_ufs_grp, "sweet_ufs");
static LCK_MTX_DECLARE(sweet_ufs_lock, &sweet_ufs_grp);

static inline uint32_t
sd_rd(uint32_t off)
{
	uint32_t v = *(volatile uint32_t *)(su.regs + off);
	__asm__ volatile ("dmb oshld" ::: "memory");
	return v;
}

static inline void
sd_wr(uint32_t off, uint32_t v)
{
	*(volatile uint32_t *)(su.regs + off) = v;
	__asm__ volatile ("dsb sy" ::: "memory");
}

/* The host is not cache coherent: clean and invalidate around every transfer. */
static void
dma_sync(uint32_t off, uint32_t len)
{
	flush_dcache64((addr64_t)(su.dma_pa + off), len, TRUE);
}

/* Wait until (reg & mask) == want, sleeping between polls when allowed. */
static int
sd_wait(uint32_t reg, uint32_t mask, uint32_t want, uint32_t *last)
{
	uint64_t deadline, now;
	nanoseconds_to_absolutetime(CMD_TIMEOUT_NS, &deadline);
	deadline += mach_absolute_time();
	bool sleepable = su.wait && su.ready && ml_get_interrupts_enabled() &&
	    !ml_at_interrupt_context() && get_preemption_level() == 0;
	for (;;) {
		uint32_t v = sd_rd(reg);
		if (last) {
			*last = v;
		}
		if ((v & mask) == want) {
			return 0;
		}
		if (reg == SDHCI_INT_STATUS && (v & INT_ERROR)) {
			return EIO;
		}
		now = mach_absolute_time();
		if (now > deadline) {
			return ETIMEDOUT;
		}
		if (sleepable) {
			uint64_t wake;
			nanoseconds_to_absolutetime(100 * NSEC_PER_USEC, &wake);
			if (assert_wait_deadline((event_t)&su.wait, THREAD_UNINT, now + wake) == THREAD_WAITING) {
				thread_block(THREAD_CONTINUE_NULL);
			}
		} else {
			delay(1);
		}
	}
}

static void
sd_reset_lines(void)
{
	sd_wr(SDHCI_CLOCK_CTRL, sd_rd(SDHCI_CLOCK_CTRL) | RESET_CMD | RESET_DATA);
	(void)sd_wait(SDHCI_CLOCK_CTRL, RESET_CMD | RESET_DATA, 0, NULL);
}

/*
 * One command; with nsect != 0 a data transfer through one ADMA2 descriptor pointing at the
 * bounce buffer (offset buf). Returns 0 or an errno; *resp gets response bits 39:8 (the R1 status).
 */
static int
mmc_cmd(uint32_t index, uint32_t arg, uint32_t flags, uint32_t xfer, uint32_t nsect, uint32_t buf,
    uint32_t *resp)
{
	uint32_t st = 0, r = 0;
	bool busy = (flags & 3) == CMD_RESP_48_BUSY;
	int error = sd_wait(SDHCI_PRESENT,
	    PRESENT_CMD_INHIBIT | ((nsect || busy) ? PRESENT_DAT_INHIBIT : 0), 0, &st);
	if (error) {
		printf("SWEET EMMC: CMD%u: host busy (present 0x%08x)\n", index, st);
		sd_reset_lines();
		return error;
	}
	sd_wr(SDHCI_INT_STATUS, 0xffffffff);
	if (nsect) {
		volatile uint32_t *d = (volatile uint32_t *)(su.dma + DMA_DESC);
		uint64_t pa = su.dma_pa + DMA_BOUNCE + buf;
		d[0] = ADMA_VALID_END_TRAN | (nsect * MMC_SECTOR) << 16;
		d[1] = (uint32_t)pa;
		d[2] = (uint32_t)(pa >> 32);
		d[3] = 0;
		dma_sync(DMA_DESC, 16);
		dma_sync(DMA_BOUNCE + buf, nsect * MMC_SECTOR);
		sd_wr(SDHCI_ADMA_ADDR_LO, (uint32_t)(su.dma_pa + DMA_DESC));
		sd_wr(SDHCI_ADMA_ADDR_HI, (uint32_t)((su.dma_pa + DMA_DESC) >> 32));
		sd_wr(SDHCI_BLOCK, (7u << 12) | MMC_SECTOR | (nsect << 16));
		flags |= CMD_DATA;
	}
	sd_wr(SDHCI_ARGUMENT, arg);
	sd_wr(SDHCI_XFER_CMD, xfer | ((index << 8 | flags) << 16));

	error = sd_wait(SDHCI_INT_STATUS, INT_CMD_COMPLETE, INT_CMD_COMPLETE, &st);
	if (!error) {
		r = sd_rd(SDHCI_RESPONSE);
		sd_wr(SDHCI_INT_STATUS, INT_CMD_COMPLETE);
		if (nsect || busy) {
			error = sd_wait(SDHCI_INT_STATUS, INT_XFER_COMPLETE, INT_XFER_COMPLETE, &st);
		}
	}
	if (!error && (r & R1_ERRORS)) {
		error = EIO;
	}
	if (nsect) {
		dma_sync(DMA_BOUNCE + buf, nsect * MMC_SECTOR);
	}
	if (error) {
		printf("SWEET EMMC: CMD%u arg 0x%x failed (%d): status 0x%08x R1 0x%08x ADMA err 0x%x\n",
		    index, arg, error, st, r, sd_rd(SDHCI_ADMA_ERROR) & 0xff);
		sd_wr(SDHCI_INT_STATUS, 0xffffffff);
		sd_reset_lines();
		return error;
	}
	sd_wr(SDHCI_INT_STATUS, 0xffffffff);
	if (resp) {
		*resp = r;
	}
	return 0;
}

/* Read or write nsect 512-byte sectors at sector, from/to the bounce buffer. */
static int
mmc_rw(bool write, uint64_t sector, uint32_t nsect)
{
	if (nsect == 0 || nsect * MMC_SECTOR > BOUNCE_SIZE || sector + nsect > su.sectors) {
		return EINVAL;
	}
	for (uint32_t done = 0; done < nsect;) {
		uint32_t n = MIN(nsect - done, MMC_MAX_SECTORS);
		uint32_t xfer = XFER_DMA | XFER_BLOCK_COUNT | (write ? 0 : XFER_READ) |
		    (n > 1 ? XFER_MULTI | XFER_AUTO_CMD12 : 0);
		uint32_t index = write ? (n > 1 ? 25 : 24) : (n > 1 ? 18 : 17);
		int error = mmc_cmd(index, (uint32_t)(sector + done), R1, xfer, n, done * MMC_SECTOR, NULL);
		if (!error && write) {
			/* Programming continues after the transfer: wait for DAT0 to go high again. */
			error = sd_wait(SDHCI_PRESENT, PRESENT_DAT0, PRESENT_DAT0, NULL);
		}
		if (error) {
			return error;
		}
		done += n;
	}
	return 0;
}

/* Read count 4 KiB blocks at lba (in 4 KiB units from the start of the user area). */
static int
ufs_read_blocks(uint64_t lba, uint32_t count)
{
	if (count == 0 || count > BOUNCE_SIZE / UFS_BLOCK) {
		return EINVAL;
	}
	return mmc_rw(false, lba * SECTORS_PER_BLOCK, count * SECTORS_PER_BLOCK);
}

/*
 * Both GPT copies are fenced off: no write may touch them (sectors), and a watchdog thread
 * re-reads them and panics the moment they change.
 */
static uint64_t gpt_alt;                /* backup header sector (last sector of the user area) */
static uint32_t gpt_hcrc, gpt_ecrc, gpt_bhcrc;
static int gpt_chan;

/*
 * Write count 4 KiB blocks from the bounce buffer to lba. The range must lie inside the
 * partition: this is the only place data goes out.
 */
static int
ufs_write_blocks(uint64_t lba, uint32_t count)
{
	uint64_t first = lba * SECTORS_PER_BLOCK, last = first + (uint64_t)count * SECTORS_PER_BLOCK - 1;
	if (!su.writable || !su.nblocks || count == 0 || count > BOUNCE_SIZE / UFS_BLOCK ||
	    lba < su.first_block || lba - su.first_block >= su.nblocks ||
	    count > su.nblocks - (lba - su.first_block) ||
	    first < 34 || !gpt_alt || last >= gpt_alt - 33) {
		printf("SWEET EMMC: refusing write of %u blocks at 0x%llx\n", count, lba);
		return EPERM;
	}
	return mmc_rw(true, first, count * SECTORS_PER_BLOCK);
}

/* Make written data durable: flush the card's write cache, if it has one enabled. */
static int
ufs_sync_cache(void)
{
	if (!su.cache_on) {
		return 0;
	}
	/* CMD6 SWITCH, write byte: EXT_CSD[32] FLUSH_CACHE = 1 */
	return mmc_cmd(6, (3u << 24) | (32u << 16) | (1u << 8), R1B, 0, 0, 0, NULL);
}

/* One raw 512-byte sector into the start of the bounce buffer (GPT). */
static int
mmc_read_sector(uint64_t sector, uint32_t count)
{
	return mmc_rw(false, sector, count);
}
