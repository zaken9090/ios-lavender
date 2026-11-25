"""lavender GPU step 3: the zap shader through TrustZone (PAS 13), boot-arg lv_gpu=8.

The firmware is proprietary and stays out of the repo and the CI kernel: tools/mkpayload.py --fw
packs a512_zap.mdt/.bNN (and the a530 PM4/PFP microcode for later) into the payload's ramdisk slot,
which the shim copies into the kernel's static memory, and adds lv_fwpa=<pa> (layout: fw_archive in
mkpayload.py). The archive also carries a zeroed 64 KB zone: the memory handed to TrustZone with
mem_setup, since lavender's DT has no fixed zap region (pil-tz-generic). That zone proved wrong
(inside iOS memory: the UI hung); the kernel now uses low RAM at lv_zapzone (default 0x95000000).

Sequence after the base TopazAdreno.cpp zap_load / Linux qcom_mdt_load + qcom_scm_pas_*:
  PIL_SHUTDOWN (ignore result), PIL_INIT_IMAGE(13, metadata pa), PIL_MEM_SETUP(13, zone, span),
  copy every loadable non-hash segment (file .bNN) to zone + (paddr - min_paddr), PIL_AUTH_RESET(13).
a512_zap: one loadable segment (b02, paddr 0x5000, 0x1334 bytes, relocatable), span 0x2000.
SMC convention: SMCCC fast SiP 0x42000000 | svc << 8 | cmd (svc 2 = PIL), x1 = arginfo.
Runs after power-up (lv_gpu >= 7 stages); logs every result.

usage: python mk_gpu2.py XNU_TREE
"""
import sys

tree = sys.argv[1]
p = f'{tree}/iokit/Kernel/arm/TopazRpm.cpp'
s = open(p, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:60], s.count(old))
    s = s.replace(old, new)


ZAP = r'''
/* lavender GPU step 3 (lv_gpu=8): zap shader via PAS 13. See xnu/src/mk_gpu2.py. */
/* write-combined (Normal non-cacheable): the ELF fields are read with plain, possibly unaligned loads */
extern "C" vm_offset_t ml_io_map_wcomb(vm_offset_t phys_addr, vm_size_t size);
static uint64_t
lv_smc(uint64_t a[8])
{
	register uint64_t x0 __asm__("x0") = a[0], x1 __asm__("x1") = a[1], x2 __asm__("x2") = a[2],
	    x3 __asm__("x3") = a[3], x4 __asm__("x4") = a[4], x5 __asm__("x5") = a[5], x6 __asm__("x6") = a[6],
	    x7 __asm__("x7") = a[7];
	__asm__ volatile ("smc #0"
	    : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
	    :
	    : "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
	a[0] = x0; a[1] = x1; a[2] = x2; a[3] = x3; a[4] = x4; a[5] = x5; a[6] = x6; a[7] = x7;
	return x0;
}

static uint64_t
lv_scm(uint32_t cmd, uint64_t arginfo, uint64_t a, uint64_t b, uint64_t c, uint64_t *res1)
{
	uint32_t fn = 0x42000000u | (0x02u << 8) | cmd;        /* SiP, 64-bit, svc PIL */
	uint64_t args[8] = { fn, arginfo, a, b, c, 0, 0, 0 };
	lv_smc(args);
	for (int n = 0; args[0] == 1 && n < 100000; n++) {     /* interrupted: resume with the session in x6 */
		uint64_t again[8] = { 1, arginfo, a, b, c, 0, args[6], 0 };
		memcpy(args, again, sizeof(args));
		lv_smc(args);
	}
	*res1 = args[1];
	return args[0];
}

struct lv_fw_ent { char name[24]; uint32_t off, size; };

static const uint8_t *
lv_fw_find(const volatile uint8_t *ar, const char *name, uint32_t *size)
{
	uint32_t count = *(const volatile uint32_t *)(ar + 8);
	for (uint32_t i = 0; i < count && i < 32; i++) {
		const volatile struct lv_fw_ent *e = (const volatile struct lv_fw_ent *)(ar + 0x18 + 32 * i);
		if (strncmp((const char *)e->name, name, 24) == 0) {
			*size = e->size;
			return (const uint8_t *)(ar + e->off);
		}
	}
	return NULL;
}

static void
lavender_gpu_zap(void)
{
	uint64_t fwpa = 0;
	if (!PE_parse_boot_argn("lv_fwpa", &fwpa, sizeof(fwpa)) || fwpa == 0) {
		LOG("LVZAP no firmware (lv_fwpa missing: mkpayload --fw)");
		return;
	}
	const volatile uint8_t *ar = (const volatile uint8_t *)ml_io_map_wcomb(fwpa, 0x4000);
	if (ar == NULL || memcmp((const void *)ar, "LVFW0001", 8) != 0) {
		LOG("LVZAP bad archive at %#llx", fwpa);
		return;
	}
	uint32_t zone_off = *(const volatile uint32_t *)(ar + 12), zone_size = *(const volatile uint32_t *)(ar + 16);
	uint32_t total = zone_off + zone_size;
	ar = (const volatile uint8_t *)ml_io_map_wcomb(fwpa, (total + 0x3fff) & ~0x3fffu);
	if (ar == NULL) {
		LOG("LVZAP map failed");
		return;
	}
	uint32_t mdt_size = 0;
	const uint8_t *mdt = lv_fw_find(ar, "a512_zap.mdt", &mdt_size);
	if (mdt == NULL || mdt_size < 52) {
		LOG("LVZAP a512_zap.mdt missing");
		return;
	}
	uint32_t phoff = *(const uint32_t *)(mdt + 28), phnum = *(const uint16_t *)(mdt + 44);
	uint32_t min_a = 0xffffffffu, max_a = 0;
	for (uint32_t i = 0; i < phnum && phoff + 32 * (i + 1) <= mdt_size; i++) {
		const uint8_t *ph = mdt + phoff + 32 * i;
		uint32_t paddr = *(const uint32_t *)(ph + 12), memsz = *(const uint32_t *)(ph + 20);
		uint32_t flags = *(const uint32_t *)(ph + 24);
		if (*(const uint32_t *)ph == 1 && memsz != 0 && ((flags >> 24) & 7) != 2) {
			min_a = paddr < min_a ? paddr : min_a;
			uint32_t end = (paddr + memsz + 0xfff) & ~0xfffu;
			max_a = end > max_a ? end : max_a;
		}
	}
	if (max_a <= min_a || max_a - min_a > zone_size) {
		LOG("LVZAP layout unexpected: %#x..%#x, zone %#x", min_a, max_a, zone_size);
		return;
	}
	/*
	 * TrustZone gets memory outside everything iOS maps: Android allocates PIL memory below 4 GiB
	 * with no kernel mapping (speculative CPU reads of XPU-locked memory are violations). With the
	 * zone inside the kernel's static memory (0x1025e8000) the zap loaded but backboardd hung, no
	 * frames at all (2026-11-25). Default 0x95000000: free low RAM right after cdsp_fw_region
	 * (DT reserved-memory), not given to XNU. Metadata at +0, the image region at +1 MB.
	 */
	uint64_t low = 0x95000000ull;
	PE_parse_boot_argn("lv_zapzone", &low, sizeof(low));
	volatile uint8_t *lowva = (volatile uint8_t *)ml_io_map(low, 0x200000);
	if (lowva == NULL) {
		LOG("LVZAP map of %#llx failed", low);
		return;
	}
	for (uint32_t i = 0; i < 0x200000; i += 4) {
		*(volatile uint32_t *)(lowva + i) = 0;
	}
	for (uint32_t i = 0; i < mdt_size; i++) {
		lowva[i] = mdt[i];
	}
	__asm__ volatile ("dsb sy" ::: "memory");
	uint64_t mdt_pa = low, zone_pa = low + 0x100000;
	uint64_t res = 0, st;
	LOG("LVZAP archive %#llx: mdt %u bytes at %#llx, zone %#llx (+%#x), span %#x", fwpa, mdt_size, mdt_pa,
	    zone_pa, zone_size, max_a - min_a);

	st = lv_scm(0x06, 1, 13, 0, 0, &res);                   /* PIL_SHUTDOWN: harmless if not loaded */
	LOG("LVZAP shutdown: %#llx/%#llx", st, res);
	st = lv_scm(0x01, 2 | (2u << 6), 13, mdt_pa, 0, &res);   /* PIL_INIT_IMAGE (x3 = buffer, RW) */
	LOG("LVZAP init_image: %#llx/%#llx", st, res);
	if (st != 0 || res != 0) {
		return;
	}
	st = lv_scm(0x02, 3, 13, zone_pa, max_a - min_a, &res);  /* PIL_MEM_SETUP */
	LOG("LVZAP mem_setup: %#llx/%#llx", st, res);
	if (st != 0 || res != 0) {
		return;
	}
	volatile uint8_t *zone = lowva + 0x100000;
	for (uint32_t i = 0; i < phnum && phoff + 32 * (i + 1) <= mdt_size; i++) {
		const uint8_t *ph = mdt + phoff + 32 * i;
		uint32_t paddr = *(const uint32_t *)(ph + 12), filesz = *(const uint32_t *)(ph + 16);
		uint32_t memsz = *(const uint32_t *)(ph + 20), flags = *(const uint32_t *)(ph + 24);
		if (*(const uint32_t *)ph != 1 || memsz == 0 || ((flags >> 24) & 7) == 2) {
			continue;
		}
		char name[24];
		snprintf(name, sizeof(name), "a512_zap.b%02u", i);
		uint32_t seg_size = 0;
		const uint8_t *seg = lv_fw_find(ar, name, &seg_size);
		if (seg == NULL || seg_size < filesz) {
			LOG("LVZAP %s missing (%u < %u)", name, seg_size, filesz);
			return;
		}
		uint32_t at = paddr - min_a;
		for (uint32_t j = 0; j < filesz; j++) {
			zone[at + j] = seg[j];
		}
		LOG("LVZAP %s: %u bytes at zone + %#x", name, filesz, at);
	}
	__asm__ volatile ("dsb sy" ::: "memory");
	st = lv_scm(0x05, 1, 13, 0, 0, &res);                   /* PIL_AUTH_RESET */
	LOG("LVZAP auth_and_reset: %#llx/%#llx -> %s", st, res, (st == 0 && res == 0) ? "ZAP LOADED" : "failed");
}
'''

sub('''static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''', ZAP.lstrip('\n') + '''
static void
lavender_perf_thread(void *arg __unused, wait_result_t wr __unused)
{''')
sub('''		lavender_gpu_probe(gpu);
	}''', '''		lavender_gpu_probe(gpu);
		if (gpu >= 8) {
			lavender_gpu_zap();
		}
	}''')
open(p, 'w', newline='\n').write(s)
print('ok')
