"""lavender: audio A4b-2 - a 1 kHz tone through ASM -> ADM -> AFE -> MAX98927 (patch 1126).

Run e137 (xnu 1125): with PRIMARY_MI2S_RX started, GPIO 12 (SCK) and 13 (WS) read high 10096 and
10011 times of 20000 - the bit clock and word select run. LPASS SMMU (0x05100000): sCR0 00200626
(enabled, unmatched streams fault), 13 SMRs all invalid, S2CR 0x200ff (fault), 14 banks. So the
ADSP's buffer accesses with stream 1 (DT msm-audio-ion iommus <lpass_q6 1>) would fault.

Now with audio_step=2, after A4a (recipe docs/APR-PLAYBACK.md):
1. LPASS SMMU: one free SMR for SID 1 exactly (mask 0), its S2CR = bypass (type 1): the ADSP's
   stream-1 addresses are physical. Logged before each write (plain str, as the other SMMUs).
2. 16 KB from TopazModem's pool (physically contiguous, below 4 GB): four 3840-byte buffers of a
   1 kHz sine at about -12 dBFS, 48 kHz stereo s16 (20 cycles each, loops without clicks).
3. AFE clock / I2S config / DEVICE_START as in A4a; ASM shared memory map (pool 3, address msw 1 =
   stream id as Linux msm_audio_ion adds) -> handle; ASM OPEN_WRITE_V3 (session 1 stream 1,
   ports 0x0101, PCM V2, default POPP); ADM DEVICE_OPEN_V5 on 0x1000 (NULL COPP topology) ->
   copp; ADM matrix map session 1 -> copp; ASM media format (48 kHz, 2 ch, 16 bit); 4 x
   ASM WRITE_V2; ASM RUN_V2; amplifier AMP_EN + GLOBAL_EN; for 3 s every WRITE_DONE
   (0x00010D99) resubmits its buffer; then the clean stop: amplifier off, ASM pause/close/unmap,
   ADM close, AFE stop, clock off, pins off. Every answer and the count of WRITE_DONEs are logged;
   ADSP state (slave-kernel) is checked after.
The user listens once: a 3-second 1 kHz tone from the speaker.

usage: python mk_audio8.py XNU_TREE   (after mk_audio7.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


# apr_call: status only from BASIC_RSP; other answers: status 0, payload in apr_got_p
sub('''	uint32_t st = apr_got_opcode == APR_BASIC_RSP && apr_got_n >= 2 ? apr_got_p[1] : (apr_got_n >= 1 ? apr_got_p[0] : 0);''',
    '''	uint32_t st = apr_got_opcode == APR_BASIC_RSP && apr_got_n >= 2 ? apr_got_p[1] :
	    (apr_got_opcode == 0x00010329u && apr_got_n >= 1 ? apr_got_p[0] : 0);      /* ADM open: status first */''')
# WRITE_DONE handling in apr_rx
sub('''	apr_rxn++;
	if (apr_wait_token != 0 && h->token == apr_wait_token) {''', '''	apr_rxn++;
	if (h->opcode == 0x00010D99u) {                 /* ASM_DATA_EVENT_WRITE_DONE_V2 */
		extern void a4b_write_done(uint32_t addr_lsw, uint32_t status);
		a4b_write_done(n >= 1 ? p[0] : 0, n >= 4 ? p[3] : 0);
		return;
	}
	if (apr_wait_token != 0 && h->token == apr_wait_token) {''')

sub('''/* A4a: amplifier set up, MI2S clocks through the AFE port, read the amplifier while they run, stop */''', r'''/* ---- A4b-2 (mk_audio8.py): tone through ASM -> ADM -> AFE -> MAX98927 */
static void
lpw(uint32_t off, uint32_t v)
{
	volatile uint8_t *a = lp_smmu + off;
	__asm__ volatile ("dsb sy\n\tstr %w0, [%1]\n\tdsb sy" :: "r"(v), "r"(a) : "memory");
}

/* SID 1 -> bypass in a free SMR (lpass_smmu_dump() has mapped the SMMU and voted its clocks) */
static bool
lpass_smmu_sid1(void)
{
	if (lp_smmu == NULL) {
		return false;
	}
	uint32_t nsmr = lpr(0x20) & 0xFF, slot = ~0u;
	for (uint32_t i = 0; i < nsmr && i < 32; i++) {
		uint32_t smr = lpr(0x800 + 4 * i);
		if ((smr >> 31) != 0 && (smr & 0xFFFF) == 1) {
			LOG("LPASS SMMU: SID 1 already in SMR%u (S2CR %08x)", i, lpr(0xC00 + 4 * i));
			return true;
		}
		if ((smr >> 31) == 0 && slot == ~0u) {
			slot = i;
		}
	}
	if (slot == ~0u) {
		LOG("LPASS SMMU: no free SMR");
		return false;
	}
	LOG("LPASS SMMU: S2CR%u = bypass", slot);
	lpw(0xC00 + 4 * slot, 1u << 16);
	LOG("LPASS SMMU: SMR%u = valid, SID 1, mask 0", slot);
	lpw(0x800 + 4 * slot, (1u << 31) | 1);
	lpw(0x70, 0);                                   /* sTLBGSYNC */
	for (uint32_t i = 0; i < 100000 && (lpr(0x74) & 1) != 0; i++) {
		IODelay(1);
	}
	LOG("LPASS SMMU: SMR%u %08x S2CR %08x GFSR %08x", slot, lpr(0x800 + 4 * slot), lpr(0xC00 + 4 * slot), lpr(0x48));
	return true;
}

#define A4_BUF_N        4
#define A4_BUF_BYTES    3840                            /* 20 ms: 960 frames, 20 cycles of 1 kHz */
static uint64_t a4_pa;
static uint8_t *a4_va;
static uint32_t a4_handle, a4_done, a4_bad;
static volatile bool a4_playing;

extern "C" void *topaz_pool_alloc(uint64_t size, uint64_t *pa);

static void
a4_write(unsigned i)
{
	uint32_t w[8] = { (uint32_t)(a4_pa + 4096u * i), 1 /* SID 1 */, a4_handle, A4_BUF_BYTES, i, 0, 0, 0 };
	(void)apr_send_p(7, 0x0101, 0x0101, 0x00010DABu, w, sizeof(w));
}

void
a4b_write_done(uint32_t addr_lsw, uint32_t status)
{
	a4_done++;
	if (status != 0) {
		a4_bad++;
	}
	if (a4_playing && addr_lsw >= (uint32_t)a4_pa && addr_lsw < (uint32_t)a4_pa + A4_BUF_N * 4096u) {
		a4_write((addr_lsw - (uint32_t)a4_pa) / 4096u);
	}
}

static bool
a4b_buffers(void)
{
	a4_va = (uint8_t *)topaz_pool_alloc(A4_BUF_N * 4096, &a4_pa);
	if (a4_va == NULL) {
		LOG("A4b: no pool memory");
		return false;
	}
	/* sin(2 pi k / 48) * 8192, k = 0..47 (about -12 dBFS) */
	static const int16_t sine[48] = {
		0, 1069, 2120, 3135, 4096, 4987, 5793, 6498, 7094, 7568, 7913, 8122, 8192, 8122, 7913, 7568,
		7094, 6498, 5793, 4987, 4096, 3135, 2120, 1069, 0, -1069, -2120, -3135, -4096, -4987, -5793, -6498,
		-7094, -7568, -7913, -8122, -8192, -8122, -7913, -7568, -7094, -6498, -5793, -4987, -4096, -3135, -2120, -1069,
	};
	for (unsigned b = 0; b < A4_BUF_N; b++) {
		int16_t *s16 = (int16_t *)(a4_va + 4096u * b);
		for (unsigned f = 0; f < A4_BUF_BYTES / 4; f++) {
			s16[2 * f] = s16[2 * f + 1] = sine[f % 48];
		}
	}
	__asm__ volatile ("dsb sy" ::: "memory");
	LOG("A4b: 4 tone buffers at %#llx", a4_pa);
	return true;
}

static void
a4b_play(void)
{
	uint32_t st;
	uint16_t copp = 0xFFFF;
	bool mapped = false, asm_open = false, adm_open = false;
	if (!lpass_smmu_sid1() || !a4b_buffers()) {
		return;
	}
	lv_mi2s_pins(true);
	if (!afe_clock(true)) {
		goto pins;
	}
	if (!afe_i2s_config() || !afe_port(true)) {
		goto clock;
	}
	{
		uint32_t m[6] = { 3 | (1u << 16), 0, (uint32_t)a4_pa, 1, A4_BUF_N * 4096u, 0 };   /* pool 3, 1 region, flags 0, lsw, msw, size */
		if (!apr_call("ASM map", 7, 0, 0, 0x00010D92u, m, 20, &st) || apr_got_opcode != 0x00010D93u || apr_got_n < 1) {
			goto afe;
		}
		a4_handle = apr_got_p[0];
		mapped = true;
		LOG("A4b: memory map handle %#x", a4_handle);
	}
	{
		uint32_t o[4] = { 0, 16u << 16, 0x00010BE4u, 0x00010DA5u };     /* mode, sink 0 + 16 bit, DEFAULT_POPP, PCM V2 */
		if (!apr_call("ASM open write", 7, 0x0101, 0x0101, 0x00010DB3u, o, sizeof(o), &st)) {
			goto unmap;
		}
		asm_open = true;
	}
	{
		uint8_t a[28];
		bzero(a, sizeof(a));
		*(uint16_t *)(a + 0) = 0;                       /* legacy */
		*(uint16_t *)(a + 2) = 1;                       /* RX path */
		*(uint16_t *)(a + 4) = 0x1000;
		*(uint16_t *)(a + 6) = 0xFFFF;
		*(uint32_t *)(a + 8) = 0x00010312u;             /* NULL COPP */
		*(uint16_t *)(a + 12) = 2;
		*(uint16_t *)(a + 14) = 16;
		*(uint32_t *)(a + 16) = 48000;
		a[20] = 1;
		a[21] = 2;
		if (!apr_call("ADM open", 8, 0x1000, 0x1000, 0x00010326u, a, sizeof(a), &st) || apr_got_n < 2) {
			goto close_asm;
		}
		copp = (uint16_t)apr_got_p[1];
		adm_open = true;
		LOG("A4b: copp %#x", copp);
	}
	{
		uint32_t mm[4] = { 0, 1, 1u | (1u << 16), copp };
		if (!apr_call("ADM matrix map", 8, 0, 0, 0x00010325u, mm, sizeof(mm), &st)) {
			goto close_adm;
		}
	}
	{
		uint8_t f[24];
		bzero(f, sizeof(f));
		*(uint32_t *)(f + 0) = 20;
		*(uint16_t *)(f + 4) = 2;
		*(uint16_t *)(f + 6) = 16;
		*(uint32_t *)(f + 8) = 48000;
		*(uint16_t *)(f + 12) = 1;
		f[16] = 1;
		f[17] = 2;
		if (!apr_call("ASM media format", 7, 0x0101, 0x0101, 0x00010D98u, f, sizeof(f), &st)) {
			goto close_adm;
		}
	}
	a4_playing = true;
	a4_done = a4_bad = 0;
	for (unsigned i = 0; i < A4_BUF_N; i++) {
		a4_write(i);
	}
	{
		uint32_t r[3] = { 0, 0, 0 };
		if (apr_call("ASM run", 7, 0x0101, 0x0101, 0x00010DAAu, r, sizeof(r), &st)) {
			LOG("A4b: amp on: AMP_EN %d GLOBAL_EN %d", lv_amp_write(0x003A, 0x01), lv_amp_write(0x00FF, 0x01));
			unsigned t0 = ms();
			while (ms() - t0 < 3000) {
				if (!glink_poll()) {
					IODelay(200);
				}
				qrtr_poll();
			}
			amp_status("playing");
			LOG("A4b: amp off: GLOBAL_EN %d AMP_EN %d", lv_amp_write(0x00FF, 0x00), lv_amp_write(0x003A, 0x00));
		}
	}
	a4_playing = false;
	LOG("A4b: %u WRITE_DONE in 3 s (%u with an error status), 150 expected", a4_done, a4_bad);
	(void)apr_call("ASM pause", 7, 0x0101, 0x0101, 0x00010BD3u, NULL, 0, &st);
close_adm:
	if (adm_open) {
		(void)apr_call("ADM close", 8, 0x1000, copp, 0x00010327u, NULL, 0, &st);
	}
close_asm:
	if (asm_open) {
		(void)apr_call("ASM close", 7, 0x0101, 0x0101, 0x00010BCDu, NULL, 0, &st);
	}
unmap:
	if (mapped) {
		(void)apr_call("ASM unmap", 7, 0, 0, 0x00010D94u, &a4_handle, 4, &st);
	}
afe:
	(void)afe_port(false);
clock:
	(void)afe_clock(false);
pins:
	lv_mi2s_pins(false);
	LOG("A4b done; slave-kernel %08x", *adsp_state);
}

/* A4a: amplifier set up, MI2S clocks through the AFE port, read the amplifier while they run, stop */''')
sub('''	lv_mi2s_pins(false);
	LOG("A4a done (amp %s)", amp ? "set up" : "NOT set up");
	lpass_smmu_dump();''', '''	lv_mi2s_pins(false);
	LOG("A4a done (amp %s)", amp ? "set up" : "NOT set up");
	lpass_smmu_dump();
	uint32_t step = 0;
	if (amp && PE_parse_boot_argn("audio_step", &step, sizeof(step)) && step >= 2) {
		a4b_play();
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
