"""lavender: audio A3 - APR client on the ADSP's "apr_audio_svc" channel (patch 1122).

Run e133 (xnu 1119): the ADSP boots (PAS ret 0, slave-kernel READY in 30 ms), GLINK comes up and
the ADSP opens "glink_ssr", "apr_audio_svc", "apr_apps2", "fastrpcglink-apps-dsp",
"LOOPBACK_CTL_LPASS" and "IPCRTR" (QRTR: services 0x42, 0x2b, 0xf, 0x33, 0x18 on node 5).
This firmware (ADSP.VT.4.0, Elite) speaks APR, not GPR.

Now TopazAudio registers "apr_audio_svc" (GLINK open + intents as for its other channels) with
an APR client (Linux msm-4.4 apr.h layout): header {hdr_field 0x0140 = seq cmd, 16-byte header,
v0; pkt_size; src svc/domain/port; dest svc/domain/port; token; opcode}, domains apps 5 / ADSP 4.
Once the channel is up it asks the core service (svc 3) AVCS_CMD_ADSP_EVENT_GET_STATE
(0x0001290C) every second until the answer (0x0001290D) says 1 (ready), then
AVCS_GET_VERSIONS (0x00012905, answer 0x00012906: build/service list) once. Every APR packet in
is logged (first 24 of them fully, then only those not already seen).

usage: python mk_audio4.py XNU_TREE   (after mk_thermal2.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#define GCHAN               "adsp_apps"''', '''#define GCHAN               "adsp_apps"

/* ---- lavender (mk_audio4.py): APR (ADSP.VT.4.0, Elite) on "apr_audio_svc" */
#define ACHAN               "apr_audio_svc"
#define APR_DOMAIN_APPS     5
#define APR_DOMAIN_ADSP     4
#define APR_SVC_CORE        3
#define APR_HDR_FIELD_CMD   0x0140                      /* seq cmd, 16-byte header, version 0 */
#define AVCS_GET_STATE      0x0001290Cu
#define AVCS_GET_STATE_RSP  0x0001290Du
#define AVCS_GET_VERSIONS   0x00012905u
#define AVCS_GET_VERSIONS_RSP 0x00012906u
#define APR_BASIC_RSP       0x000110E8u
struct apr_hdr {
	uint16_t hdr_field, pkt_size;
	uint8_t src_svc, src_domain;
	uint16_t src_port;
	uint8_t dest_svc, dest_domain;
	uint16_t dest_port;
	uint32_t token, opcode;
} __attribute__((packed));
static uint32_t apr_token = 1, apr_core_state = 0xFFFFFFFFu, apr_asks, apr_rxn;
static unsigned apr_last_ask;
static bool apr_versions_asked;

static bool glink_send(const char *name, const void *data, uint32_t len);
static bool glink_chan_up(const char *name);

static void
apr_send(uint8_t svc, uint32_t opcode, const void *payload, uint32_t len)
{
	uint8_t buf[sizeof(struct apr_hdr) + 64];
	struct apr_hdr *h = (struct apr_hdr *)buf;
	if (len > 64) {
		return;
	}
	bzero(buf, sizeof(buf));
	h->hdr_field = APR_HDR_FIELD_CMD;
	h->pkt_size = (uint16_t)(sizeof(*h) + len);
	h->src_svc = svc;
	h->src_domain = APR_DOMAIN_APPS;
	h->dest_svc = svc;
	h->dest_domain = APR_DOMAIN_ADSP;
	h->token = apr_token++;
	h->opcode = opcode;
	if (len != 0) {
		memcpy(buf + sizeof(*h), payload, len);
	}
	glink_send(ACHAN, buf, (uint32_t)sizeof(*h) + len);
}

static void
apr_rx(const uint8_t *data, uint32_t len)
{
	const struct apr_hdr *h = (const struct apr_hdr *)data;
	if (len < sizeof(*h)) {
		LOG("APR: short packet (%u bytes)", len);
		return;
	}
	const uint32_t *p = (const uint32_t *)(data + sizeof(*h));
	uint32_t n = (len - (uint32_t)sizeof(*h)) / 4;
	apr_rxn++;
	if (h->opcode == AVCS_GET_STATE_RSP && n >= 1) {
		if (p[0] != apr_core_state) {
			LOG("APR: ADSP core state %u%s (after %u asks)", p[0], p[0] == 1 ? " READY" : "", apr_asks);
		}
		apr_core_state = p[0];
		return;
	}
	if (h->opcode == AVCS_GET_VERSIONS_RSP && n >= 2) {
		LOG("APR: versions: build %#x, %u services", p[0], p[1]);
		for (uint32_t i = 0; i < p[1] && 2 + 2 * i + 1 < n; i++) {
			LOG("APR:   service %#x version %#x", p[2 + 2 * i], p[2 + 2 * i + 1]);
		}
		return;
	}
	if (apr_rxn <= 24) {
		LOG("APR: in %u bytes: svc %u/%u port %u -> svc %u/%u port %u token %u opcode %#x: %08x %08x %08x", len, h->src_svc,
		    h->src_domain, h->src_port, h->dest_svc, h->dest_domain, h->dest_port, h->token, h->opcode, n > 0 ? p[0] : 0,
		    n > 1 ? p[1] : 0, n > 2 ? p[2] : 0);
	}
}

static void
apr_poll(void)
{
	if (!glink_chan_up(ACHAN)) {
		return;
	}
	if (apr_core_state != 1) {
		if (apr_asks < 60 && (apr_asks == 0 || ms() - apr_last_ask >= 1000)) {
			apr_last_ask = ms();
			apr_asks++;
			apr_send(APR_SVC_CORE, AVCS_GET_STATE, NULL, 0);
		}
		return;
	}
	if (!apr_versions_asked) {
		apr_versions_asked = true;
		apr_send(APR_SVC_CORE, AVCS_GET_VERSIONS, NULL, 0);
	}
}''')
sub('''	glink_register(GCHAN, gpr_rx);
''', '''	glink_register(GCHAN, gpr_rx);
	glink_register(ACHAN, apr_rx);                  /* lavender: APR (mk_audio4.py) */
''')
sub('''		gpr_poll();
''', '''		gpr_poll();
		apr_poll();
''')
open(path, 'w', newline='\n').write(s)
print('ok')
