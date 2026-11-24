"""Turn the base series' bsd/dev/sweet_ufs.c into the lavender eMMC driver (in an extracted xnu tree).

usage: python mk_emmc.py XNU_TREE emmc_transport.c
Everything above the transport (GPT lookup, BSD block/char device, console log ring) stays;
the UFS transport is replaced by SDHCI with one ADMA2 descriptor per command.
"""
import sys

tree, transport = sys.argv[1], open(sys.argv[2]).read()
path = tree + '/bsd/dev/sweet_ufs.c'
s = open(path, newline='').read()


def cut(start, end):
    """Text from the line starting with `start` up to (not including) the line starting with `end`."""
    a = s.index(start)
    b = s.index(end, a)
    return a, b


def replace(start, end, new):
    global s
    a, b = cut(start, end)
    s = s[:a] + new + s[b:]


def sub(old, new, count=1):
    global s
    assert s.count(old) == count, (old, s.count(old))
    s = s.replace(old, new)


sub(""" * SWEET internal UFS root device.
""", """ * SWEET internal UFS root device.
 *
 * lavender (Redmi Note 7): the storage is eMMC 5.1 behind Qualcomm's SDHCI host (sdhci-msm v5),
 * not UFS. Only the transport below differs: polled SDHCI commands, data through one 64-bit
 * ADMA2 descriptor per command (the host has no SDMA, and PIO does not drain its FIFO), card
 * state as ABL left it (transfer state, its bus mode and clock). Block numbers above the
 * transport stay in 4 KiB units; every GPT partition on lavender starts 4 KiB aligned.
""")

# transport: register definitions .. ufs_sync_cache()
replace('#define REG_CAP', 'static int\nufs_find_partition', transport + '\n')

replace('static int\nufs_find_partition', '/*\n * topaz: read-only access', '''static int
ufs_find_partition(const char *want)
{
	const uint8_t *b = (const uint8_t *)(su.dma + DMA_BOUNCE);
	int error = mmc_read_sector(1, 1);
	if (error) {
		return error;
	}
	if (memcmp(b, "EFI PART", 8) != 0) {
		printf("SWEET EMMC: no GPT\\n");
		return ENXIO;
	}
	uint64_t entry_lba;
	uint32_t nent, esz;
	memcpy(&gpt_hcrc, b + 16, 4);
	memcpy(&gpt_alt, b + 32, 8);
	memcpy(&gpt_ecrc, b + 88, 4);
	memcpy(&entry_lba, b + 72, 8);
	memcpy(&nent, b + 80, 4);
	memcpy(&esz, b + 84, 4);
	if (esz != 128 || nent == 0 || nent * esz > BOUNCE_SIZE || gpt_alt >= su.sectors) {
		printf("SWEET EMMC: unsupported GPT: %u entries x %u, backup at 0x%llx\\n", nent, esz, gpt_alt);
		return ENXIO;
	}
	error = mmc_read_sector(entry_lba, (nent * esz + MMC_SECTOR - 1) / MMC_SECTOR);
	if (error) {
		return error;
	}
	for (uint32_t i = 0; i < nent; i++) {
		const uint8_t *e = b + i * esz;
		char name[37];
		unsigned c;
		for (c = 0; c < 36; c++) {
			uint16_t ch = (uint16_t)(e[56 + 2 * c] | e[57 + 2 * c] << 8);
			if (ch == 0 || ch > 0x7f) {
				break;
			}
			name[c] = (char)ch;
		}
		name[c] = 0;
		if (strcmp(name, want) != 0) {
			continue;
		}
		uint64_t first, last;
		memcpy(&first, e + 32, 8);
		memcpy(&last, e + 40, 8);
		if (last < first || (first % SECTORS_PER_BLOCK) || last >= gpt_alt) {
			printf("SWEET EMMC: partition %s at sectors 0x%llx-0x%llx: unusable\\n", want, first, last);
			return ENXIO;
		}
		su.first_block = first / SECTORS_PER_BLOCK;
		su.nblocks = (last - first + 1) / SECTORS_PER_BLOCK;
		if (mmc_read_sector(gpt_alt, 1) == 0 && memcmp(b, "EFI PART", 8) == 0) {
			memcpy(&gpt_bhcrc, b + 16, 4);
		}
		printf("SWEET EMMC: GPT hcrc %#x ecrc %#x, backup at sector %#llx hcrc %#x\\n",
		    gpt_hcrc, gpt_ecrc, gpt_alt, gpt_bhcrc);
		return 0;
	}
	printf("SWEET EMMC: no GPT partition named \\"%s\\"\\n", want);
	return ENOENT;
}

''')

replace('static int\nufs_lookup_part', 'int sweet_ufs_read_part', '''static int
ufs_lookup_part(const char *want, unsigned *slot)
{
	const uint8_t *b = (const uint8_t *)(su.dma + DMA_BOUNCE);

	for (unsigned i = 0; i < part_cached; i++) {
		if (strcmp(part_cache[i].name, want) == 0) {
			*slot = i;
			return 0;
		}
	}
	if (part_cached == sizeof(part_cache) / sizeof(part_cache[0]) || strlen(want) > 36) {
		return ENOSPC;
	}
	if (mmc_read_sector(1, 1) != 0 || memcmp(b, "EFI PART", 8) != 0) {
		return ENOENT;
	}
	uint64_t entry_lba;
	uint32_t nent, esz;
	memcpy(&entry_lba, b + 72, 8);
	memcpy(&nent, b + 80, 4);
	memcpy(&esz, b + 84, 4);
	if (esz != 128 || nent == 0 || nent * esz > BOUNCE_SIZE ||
	    mmc_read_sector(entry_lba, (nent * esz + MMC_SECTOR - 1) / MMC_SECTOR) != 0) {
		return ENOENT;
	}
	for (uint32_t i = 0; i < nent; i++) {
		const uint8_t *e = b + i * esz;
		char name[37];
		unsigned c;
		for (c = 0; c < 36; c++) {
			uint16_t ch = (uint16_t)(e[56 + 2 * c] | e[57 + 2 * c] << 8);
			if (ch == 0 || ch > 0x7f) {
				break;
			}
			name[c] = (char)ch;
		}
		name[c] = 0;
		uint64_t first, last;
		memcpy(&first, e + 32, 8);
		memcpy(&last, e + 40, 8);
		if (strcmp(name, want) != 0 || last < first || (first % SECTORS_PER_BLOCK)) {
			continue;
		}
		unsigned k = part_cached++;
		strlcpy(part_cache[k].name, want, sizeof(part_cache[k].name));
		part_cache[k].lun = 0;
		part_cache[k].first = first / SECTORS_PER_BLOCK;
		part_cache[k].nblocks = (last - first + 1) / SECTORS_PER_BLOCK;
		printf("SWEET EMMC: partition %s: blocks 0x%llx+0x%llx (read-only)\\n",
		    want, part_cache[k].first, part_cache[k].nblocks);
		*slot = k;
		return 0;
	}
	return ENOENT;
}

''')

replace('static int\nufs_take_over_host', 'static int\nsweet_ufs_open', '''/*
 * Take the host as ABL left it: bus width, clock and card mode stay; polled operation,
 * 64-bit ADMA2, maximum data timeout. Command queueing (CQE) must be off.
 */
static int
mmc_take_over_host(vm_offset_t cq)
{
	uint32_t ver = sd_rd(SDHCI_VERSION) >> 16, caps = sd_rd(SDHCI_CAPS);
	uint32_t hc1 = sd_rd(SDHCI_HOST_CTRL1), hc2 = sd_rd(SDHCI_HOST_CTRL2), present = sd_rd(SDHCI_PRESENT);
	uint32_t cqcfg = cq ? *(volatile uint32_t *)(cq + CQ_CFG) : 0;

	printf("SWEET EMMC: host version 0x%x caps 0x%08x hc1 0x%08x hc2 0x%08x present 0x%08x cqcfg 0x%x\\n",
	    ver, caps, hc1, hc2, present, cqcfg);
	if (cqcfg & 1) {
		printf("SWEET EMMC: command queueing is on: not supported\\n");
		return ENXIO;
	}
	if (!(caps & CAPS_ADMA2)) {
		printf("SWEET EMMC: host reports no ADMA2\\n");
		return ENXIO;
	}
	sd_wr(SDHCI_SIGNAL_ENABLE, 0);                  /* polled: nothing to the interrupt controller */
	sd_wr(SDHCI_INT_ENABLE, 0x03ff000b);            /* status for: command/transfer complete, DMA, every error */
	sd_wr(SDHCI_INT_STATUS, 0xffffffff);
	sd_wr(SDHCI_CLOCK_CTRL, (sd_rd(SDHCI_CLOCK_CTRL) & 0x0000ffffu) | (0x0eu << 16));
	if (hc2 & HC2_V4) {
		sd_wr(SDHCI_HOST_CTRL2, hc2 | HC2_64BIT);
		hc1 = (hc1 & ~HC1_DMA_MASK) | HC1_ADMA2;
	} else {
		hc1 = (hc1 & ~HC1_DMA_MASK) | HC1_ADMA2_64;
	}
	sd_wr(SDHCI_HOST_CTRL1, hc1);
	sd_reset_lines();
	return 0;
}

/* Card state: EXT_CSD (size, cache, selected partition); back to the user area if needed. */
static int
mmc_card_init(void)
{
	const uint8_t *ext = (const uint8_t *)(su.dma + DMA_BOUNCE);
	uint32_t r = 0;
	const uint32_t xfer = XFER_DMA | XFER_BLOCK_COUNT | XFER_READ;

	int error = mmc_cmd(8, 0, R1, xfer, 1, 0, NULL);        /* SEND_EXT_CSD */
	for (uint32_t rca = 1; error && rca <= 4; rca++) {
		/* Not in the transfer state: find the card's relative address and select it. */
		if (mmc_cmd(13, rca << 16, R1, 0, 0, 0, &r) == 0) {
			printf("SWEET EMMC: card at RCA %u in state %u: selecting it\\n", rca, (r >> 9) & 0xf);
			(void)mmc_cmd(7, rca << 16, R1B, 0, 0, 0, NULL);
			error = mmc_cmd(8, 0, R1, xfer, 1, 0, NULL);
		}
	}
	if (error) {
		return error;
	}
	su.sectors = (uint64_t)ext[212] | (uint64_t)ext[213] << 8 | (uint64_t)ext[214] << 16 | (uint64_t)ext[215] << 24;
	su.cache_on = (ext[33] & 1) != 0;
	uint8_t part = ext[179];
	printf("SWEET EMMC: %llu MiB, EXT_CSD rev %u, partition config 0x%02x, cache %s (%u KiB), "
	    "bus width %u, timing %u\\n", su.sectors >> 11, ext[192], part, su.cache_on ? "on" : "off",
	    (uint32_t)ext[249] | (uint32_t)ext[250] << 8 | (uint32_t)ext[251] << 16 | (uint32_t)ext[252] << 24,
	    ext[183], ext[185]);
	if (part & 7) {
		/* A boot partition is selected for access: back to the user area. */
		error = mmc_cmd(6, (3u << 24) | (179u << 16) | ((uint32_t)(part & ~7u) << 8), R1B, 0, 0, 0, NULL);
		if (error) {
			return error;
		}
	}
	return su.sectors ? 0 : ENXIO;
}

''')

# sweet_ufs_init: the host has hc_mem and cmdq_mem; no TEST UNIT READY on eMMC
sub('''	su.regs = ml_io_map(reg[0], reg[1]);''', '''	su.regs = ml_io_map(reg[0], reg[1]);
	vm_offset_t cq = size >= 4 * sizeof(uintptr_t) ? ml_io_map(reg[2], reg[3]) : 0;''')
sub('''	error = ufs_take_over_host();
	if (!error) {
		static const uint8_t tur[6] = { 0x00 };
		/* The first command after the bootloader may report a unit attention. */
		for (int i = 0; i < 3 && (error = ufs_scsi(tur, sizeof(tur), 0, false)); i++) {
		}
	}
''', '''	error = mmc_take_over_host(cq);
	if (!error) {
		error = mmc_card_init();
	}
''')
sub('''	int hw = 0;
	(void)PE_parse_boot_argn("sweethw", &hw, sizeof(hw));
	sweet_touch_init();
	sweet_keys_init();
	if (hw == 1) {
		sweet_usb_probe();
	} else {
		printf("SWEET UFS: USB skipped (topaz, sweethw=0)\\n");
	}
''', '''	sweet_touch_init();
	sweet_keys_init();
	sweet_usb_probe();      /* lavender: started earlier by the platform expert; no-op here */
''')

# GPT watchdog: raw sectors
sub('''		ok = ufs_read_blocks(1, 1) == 0 && memcmp(b, "EFI PART", 8) == 0;''',
    '''		ok = mmc_read_sector(1, 1) == 0 && memcmp(b, "EFI PART", 8) == 0;''')
sub('''		if (ok && gpt_bhcrc && ufs_read_blocks(gpt_alt, 1) == 0) {''',
    '''		if (ok && gpt_bhcrc && mmc_read_sector(gpt_alt, 1) == 0) {''')
sub('panic("SWEET UFS: GPT LUN0 CHANGED', 'panic("SWEET EMMC: GPT CHANGED')

open(path, 'w', newline='\n').write(s)
print('sweet_ufs.c:', s.count('\n'), 'lines')
