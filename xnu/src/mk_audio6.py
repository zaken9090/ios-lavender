"""lavender: audio A4a - amplifier set-up, MI2S pins, AFE PRIMARY_MI2S_RX started and stopped (patch 1124).

Recipe: docs/APR-PLAYBACK.md (msm-4.4 sdm660 + mainline max98927). Step A4a, checked by the log:
1. APR commands with the msm-4.4 header: hdr_field 0x0250 (seq cmd, 20-byte header, v0) - 1122
   sent 0x0140 (16-byte header claimed), harmless only for payload-less commands.
   apr_call(): send, then poll GLINK until the answer with our token (APR_BASIC_RSP 0x000110E8
   {opcode, status} or the command's own response) or 2 s.
2. MAX98927 (LavenderAudio.cpp, I2C 0x3A, 16-bit register addresses): reset GPIO 77 released,
   6 ms, REV_ID 0x01FF (0x40 expected), soft reset, mainline init table, I2S slave 16 bit 48 kHz,
   not enabled yet.
3. TLMM GPIO 12 (func 2), 13, 14 (func 3) to pri_mi2s, 8 mA.
4. AFE (svc 4): AFE_SVC_CMD_SET_PARAM clock set PRI_MI2S IBIT (0x100) 1.536 MHz enable;
   AFE_PORT_CMD_SET_PARAM_V2 I2S config for port 0x1000 (SD0, stereo, internal WS, 48 kHz, 16 bit);
   AFE_PORT_CMD_DEVICE_START 0x1000. With BCLK/LRCLK running the amplifier's clock monitor and
   interrupt registers are read (0x0011, 0x0001-0x0006), the amp is NOT enabled (no sound).
5. After 2 s: DEVICE_STOP, clock disable - the clean stop order of the recipe.
Boot-arg audio_step=1 (with audio=1 adsp=1); 0 = only A1-A3 as before.

usage: python mk_audio6.py XNU_TREE   (after mk_audio5.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


la = f'{tree}/iokit/Kernel/arm/LavenderAudio.cpp'
patch(la, '''static void
census_i2c(int rst)''', r'''/* register write: address (2 bytes), value */
static int
i2c_write16(uint8_t addr, uint16_t reg, uint8_t val)
{
	if (!i2c_start()) {
		return -2;
	}
	bool ok = i2c_wb((uint8_t)(addr << 1)) && i2c_wb((uint8_t)(reg >> 8)) && i2c_wb((uint8_t)reg) && i2c_wb(val);
	i2c_stop();
	return ok ? 0 : -1;
}

#define MAX_ADDR 0x3a

extern "C" int
lv_amp_read(uint16_t reg)
{
	uint8_t b = 0;
	if (pin_sda == NULL) {
		return -1;
	}
	int r = i2c_read(MAX_ADDR, reg, 2, &b, 1);
	return r == 0 ? b : r;
}

extern "C" int
lv_amp_write(uint16_t reg, uint8_t val)
{
	return pin_sda == NULL ? -1 : i2c_write16(MAX_ADDR, reg, val);
}

/* MAX98927 out of reset and set up for I2S slave 16 bit 48 kHz stereo -> mono, not enabled (APR-PLAYBACK.md 6) */
extern "C" bool
lv_amp_setup(void)
{
	static const uint16_t init[][2] = {
		{ 0x0100, 0x01 },                       /* soft reset */
		{ 0x001C, 0xFF }, { 0x001D, 0xFF },     /* IV slots Hi-Z */
		{ 0x0025, 0x80 }, { 0x0026, 0x01 },     /* mono mix (L+R)/2 */
		{ 0x0036, 0x38 },                       /* amp volume */
		{ 0x003C, 0x05 },                       /* speaker gain */
		{ 0x0037, 0x03 }, { 0x003F, 0xF7 },     /* DC blockers */
		{ 0x0040, 0x1C }, { 0x0042, 0x3E },     /* boost */
		{ 0x0043, 0x04 }, { 0x0044, 0x00 }, { 0x0045, 0x24 },
		{ 0x007F, 0x06 },                       /* brownout */
		{ 0x0082, 0x08 }, { 0x0086, 0x01 }, { 0x0087, 0x10 },
		{ 0x0021, 0x00 },                       /* slave */
		{ 0x0020, 0x40 },                       /* I2S, 16-bit channels */
		{ 0x0018, 0x03 },                       /* RX channels 0 and 1 */
		{ 0x003B, 0x00 }, { 0x0035, 0x00 },     /* PCM source, no PDM */
		{ 0x0022, 0x22 },                       /* 32 BCLK per frame */
		{ 0x0023, 0x08 }, { 0x0024, 0x88 },     /* 48 kHz, IV ADC 48 kHz */
	};
	if (pin_sda == NULL) {
		return false;
	}
	pin_rst[1] = 0;                                 /* reset (active low) */
	pin_cfg(pin_rst, CFG_OE);
	IOSleep(2);
	pin_rst[1] = 2;                                 /* release */
	IOSleep(6);
	int rev = lv_amp_read(0x01FF);
	LOG("max98927: revision %#x (0x40 expected)", rev);
	if (rev < 0) {
		return false;
	}
	int bad = 0;
	for (unsigned i = 0; i < sizeof(init) / sizeof(init[0]); i++) {
		if (lv_amp_write(init[i][0], (uint8_t)init[i][1]) != 0) {
			bad++;
		}
		if (i == 0) {
			IOSleep(2);                     /* after the soft reset */
		}
	}
	LOG("max98927: init table written, %d NAKs; 0x0020=%#x 0x0023=%#x 0x0036=%#x", bad, lv_amp_read(0x0020), lv_amp_read(0x0023),
	    lv_amp_read(0x0036));
	return bad == 0;
}

/* TLMM GPIO 12 (func 2), 13, 14 (func 3): Primary MI2S SCK, WS, SD0; 8 mA, no pull */
extern "C" void
lv_mi2s_pins(bool on)
{
	vm_offset_t n = ml_io_map(TLMM_NORTH_PA + 0x1000 * 12, 0x3000);
	if (n == 0) {
		return;
	}
	volatile uint32_t *g12 = (volatile uint32_t *)n, *g13 = (volatile uint32_t *)(n + 0x1000), *g14 = (volatile uint32_t *)(n + 0x2000);
	pin_cfg(g12, on ? 0x0C8u : 0x001u);
	pin_cfg(g13, on ? 0x0CCu : 0x001u);
	pin_cfg(g14, on ? 0x0CCu : 0x001u);
	LOG("pri_mi2s pins %s: %#x %#x %#x", on ? "on" : "off", g12[0], g13[0], g14[0]);
}

static void
census_i2c(int rst)''')

ta = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
patch(ta, '''#define APR_HDR_FIELD_CMD   0x0140                      /* seq cmd, 16-byte header, version 0 */''',
      '''#define APR_HDR_FIELD_CMD   0x0250                      /* seq cmd, 20-byte header, v0 (msm-4.4; mk_audio6.py) */''')
patch(ta, '''static uint32_t apr_token = 1, apr_core_state = 0xFFFFFFFFu, apr_asks, apr_rxn;''',
      '''static uint32_t apr_token = 1, apr_core_state = 0xFFFFFFFFu, apr_asks, apr_rxn;
/* the answer apr_call() waits for (mk_audio6.py) */
static volatile uint32_t apr_wait_token, apr_got, apr_got_opcode, apr_got_n;
static uint32_t apr_got_p[8];''')
# apr_send: ports; keep the old signature as a wrapper
patch(ta, '''static void
apr_send(uint8_t svc, uint32_t opcode, const void *payload, uint32_t len)
{
	uint8_t buf[sizeof(struct apr_hdr) + 64];
	struct apr_hdr *h = (struct apr_hdr *)buf;
	if (len > 64) {
		return;
	}''', '''static uint32_t
apr_send_p(uint8_t svc, uint16_t src_port, uint16_t dest_port, uint32_t opcode, const void *payload, uint32_t len)
{
	uint8_t buf[sizeof(struct apr_hdr) + 96];
	struct apr_hdr *h = (struct apr_hdr *)buf;
	if (len > 96) {
		return 0;
	}''')
patch(ta, '''	h->dest_domain = APR_DOMAIN_ADSP;
	h->token = apr_token++;
	h->opcode = opcode;
	if (len != 0) {
		memcpy(buf + sizeof(*h), payload, len);
	}
	glink_send(ACHAN, buf, (uint32_t)sizeof(*h) + len);
}''', '''	h->dest_domain = APR_DOMAIN_ADSP;
	h->src_port = src_port;
	h->dest_port = dest_port;
	h->token = apr_token++;
	h->opcode = opcode;
	if (len != 0) {
		memcpy(buf + sizeof(*h), payload, len);
	}
	glink_send(ACHAN, buf, (uint32_t)sizeof(*h) + len);
	return h->token;
}

static void
apr_send(uint8_t svc, uint32_t opcode, const void *payload, uint32_t len)
{
	(void)apr_send_p(svc, 0, 0, opcode, payload, len);
}''')
# capture answers for apr_call
patch(ta, '''	apr_rxn++;
	if (apr_rxn <= 3) {''', '''	apr_rxn++;
	if (apr_wait_token != 0 && h->token == apr_wait_token) {
		apr_got_opcode = h->opcode;
		apr_got_n = n < 8 ? n : 8;
		for (uint32_t i = 0; i < apr_got_n; i++) {
			apr_got_p[i] = p[i];
		}
		apr_got = 1;
	}
	if (apr_rxn <= 3) {''')
# apr_call + the A4a sequence, after apr_poll
patch(ta, '''	if (!apr_versions_asked) {
		apr_versions_asked = true;
		apr_send(APR_SVC_CORE, AVCS_GET_VERSIONS, NULL, 0);
	}
}''', '''	if (!apr_versions_asked) {
		apr_versions_asked = true;
		apr_send(APR_SVC_CORE, AVCS_GET_VERSIONS, NULL, 0);
	}
}

static bool glink_poll(void);
static void qrtr_poll(void);

/* one APR command and its answer (same token): BASIC_RSP status, or the opcode's own response */
static bool
apr_call(const char *what, uint8_t svc, uint16_t sport, uint16_t dport, uint32_t opcode, const void *payload, uint32_t len,
    uint32_t *status)
{
	apr_got = 0;
	apr_wait_token = apr_token;                     /* the token apr_send_p will use */
	(void)apr_send_p(svc, sport, dport, opcode, payload, len);
	unsigned t0 = ms();
	while (!apr_got && ms() - t0 < 2000) {
		if (!glink_poll()) {
			IODelay(200);
		}
		qrtr_poll();
	}
	apr_wait_token = 0;
	if (!apr_got) {
		LOG("APR %s (%#x): no answer in 2 s", what, opcode);
		return false;
	}
	uint32_t st = apr_got_opcode == APR_BASIC_RSP && apr_got_n >= 2 ? apr_got_p[1] : (apr_got_n >= 1 ? apr_got_p[0] : 0);
	LOG("APR %s (%#x): answer %#x, status %u%s", what, opcode, apr_got_opcode, st, st == 0 ? "" : " FAILED");
	if (status != NULL) {
		*status = st;
	}
	return st == 0;
}

extern "C" bool lv_amp_setup(void);
extern "C" int lv_amp_read(uint16_t reg);
extern "C" int lv_amp_write(uint16_t reg, uint8_t val);
extern "C" void lv_mi2s_pins(bool on);

/* AFE_SVC_CMD_SET_PARAM: clock set PRI_MI2S IBIT 1.536 MHz */
static bool
afe_clock(bool on)
{
	uint32_t pl[13];
	bzero(pl, sizeof(pl));
	pl[0] = 12 + 20;                                /* payload_size: param header + struct afe_clk_set (20 bytes) */
	/* pl[1..3] mem map header 0 */
	pl[4] = 0x0001028Fu;                            /* AFE_MODULE_CLOCK_SET */
	pl[5] = 0x00010290u;                            /* AFE_PARAM_ID_CLOCK_SET */
	pl[6] = 20;                                     /* param size (u16) + reserved */
	pl[7] = 1;                                      /* clk_set_minor_version */
	pl[8] = 0x100;                                  /* PRI_MI2S_IBIT */
	pl[9] = 1536000;
	pl[10] = 1;                                     /* clk_attri COUPLE_NO, clk_root DEFAULT 0 */
	pl[11] = on ? 1 : 0;
	return apr_call(on ? "AFE clock on" : "AFE clock off", 4, 0, 0, 0x000100F3u, pl, 48, NULL);
}

/* AFE_PORT_CMD_SET_PARAM_V2: I2S config of PRIMARY_MI2S_RX */
static bool
afe_i2s_config(void)
{
	uint8_t pl[4 + 12 + 12 + 20];
	bzero(pl, sizeof(pl));
	*(uint16_t *)(pl + 0) = 0x1000;                 /* port */
	*(uint16_t *)(pl + 2) = 12 + 20;                /* payload size */
	*(uint32_t *)(pl + 16) = 0x0001020Cu;           /* AFE_MODULE_AUDIO_DEV_INTERFACE */
	*(uint32_t *)(pl + 20) = 0x0001020Du;           /* AFE_PARAM_ID_I2S_CONFIG */
	*(uint16_t *)(pl + 24) = 20;
	*(uint32_t *)(pl + 28) = 1;                     /* minor version */
	*(uint16_t *)(pl + 32) = 16;                    /* bit width */
	*(uint16_t *)(pl + 34) = 1;                     /* SD0 */
	*(uint16_t *)(pl + 36) = 1;                     /* stereo */
	*(uint16_t *)(pl + 38) = 1;                     /* WS internal */
	*(uint32_t *)(pl + 40) = 48000;
	*(uint16_t *)(pl + 44) = 0;                     /* linear PCM */
	return apr_call("AFE I2S config", 4, 0, 0, 0x000100EFu, pl, sizeof(pl), NULL);
}

static bool
afe_port(bool start)
{
	uint16_t pl[2] = { 0x1000, 0 };
	return apr_call(start ? "AFE start" : "AFE stop", 4, 0, 0, start ? 0x000100E5u : 0x000100E6u, pl, 4, NULL);
}

static void
amp_status(const char *when)
{
	LOG("max98927 %s: clk_mon 0x0011=%#x int_raw %#x %#x %#x int_state %#x %#x %#x", when, lv_amp_read(0x0011), lv_amp_read(0x0001),
	    lv_amp_read(0x0002), lv_amp_read(0x0003), lv_amp_read(0x0004), lv_amp_read(0x0005), lv_amp_read(0x0006));
}

/* A4a: amplifier set up, MI2S clocks through the AFE port, read the amplifier while they run, stop */
static void
a4a_test(void)
{
	bool amp = lv_amp_setup();
	lv_mi2s_pins(true);
	amp_status("before clocks");
	if (afe_clock(true)) {
		if (afe_i2s_config() && afe_port(true)) {
			IOSleep(50);
			amp_status("with clocks");
			IOSleep(2000);
			amp_status("after 2 s");
			afe_port(false);
		}
		afe_clock(false);
	}
	lv_mi2s_pins(false);
	LOG("A4a done (amp %s)", amp ? "set up" : "NOT set up");
}''')
patch(ta, '''		gpr_poll();
		apr_poll();
''', '''		gpr_poll();
		apr_poll();
		{
			static bool a4a_done;
			uint32_t step = 0;
			if (!a4a_done && apr_versions_asked && apr_core_state == 1 &&
			    PE_parse_boot_argn("audio_step", &step, sizeof(step)) && step >= 1) {
				a4a_done = true;
				IOSleep(200);                   /* the versions answer first */
				a4a_test();
			}
		}
''')
print('ok')
