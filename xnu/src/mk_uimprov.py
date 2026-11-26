"""lavender: the SIM application is made the modem's GW provisioning session (patch 1076), T6.

Run e77 (SIM in slot 1, the modem no longer crashes): UIM GET_CARD_STATUS shows the card present
with one USIM application in state "detected" and no provisioning session ("index_gw_primary"
0xFFFF). CommCenter stays at kSimStateDetected. On Android the RIL activates the session itself
(UIM CHANGE_PROVISIONING_SESSION); an Apple baseband does it on its own, so CommCenter never asks.

When the modem's UIM service appears the kernel asks the card status from a port of its own; if
there is no GW primary session it activates one for the first USIM (or else SIM) application
of the first slot with a card: CHANGE_PROVISIONING_SESSION (0x38), TLV 1 {session 0 = primary GW,
activate 1}, TLV 0x10 {slot, AID}. The modem then moves the application on (PIN, ready) and sends
its status indications to the clients that registered - CommCenter among them. modem_prov=0
leaves it out. Logged as "uim prov ..." (the AID is not personal data; ICCID/IMSI are not read).

usage: python mk_uimprov.py XNU_TREE   (after mk_diagsrv.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#define PORT_DIAG           0x4010              /* DIAG CNTL, DATA, DCI servers (mk_diagsrv.py) */
''', '''#define PORT_DIAG           0x4010              /* DIAG CNTL, DATA, DCI servers (mk_diagsrv.py) */
#define PORT_UIMC           0x4006              /* our QMI client port towards UIM (mk_uimprov.py) */
static bool uim_prov_asked;
static uint32_t uim_node, uim_port;
''')
sub('''		if (c->a == QMI_SVC_WLFW) {''', '''		if (c->a == 0x0b && !uim_prov_asked) {         /* UIM: activate the GW session if nobody did (mk_uimprov.py) */
			uint32_t prov = 1;
			uim_prov_asked = true;
			(void)PE_parse_boot_argn("modem_prov", &prov, sizeof(prov));
			if (prov != 0) {
				uint8_t get[11] = { 0, 3, 0, 0x2f, 0, 4, 0, 0x10, 1, 0, 0 };
				uim_node = c->c;
				uim_port = c->d;
				qrtr_send(QRTR_TYPE_DATA, PORT_UIMC, c->c, c->d, get, sizeof(get));
			}
		}
		if (c->a == QMI_SVC_WLFW) {''')
sub('''	if (dst_port == PORT_DMSC) {''', '''	if (dst_port == PORT_UIMC) {
		uim_prov_rx(data, len);
		return true;
	}
	if (dst_port == PORT_DMSC) {''')
sub('''static bool
svc_rx(uint32_t src_node, uint32_t src_port, uint32_t dst_port, const uint8_t *data, uint32_t len)
{''', '''/* UIM answers to our own port: card status -> activate the GW provisioning session */
static void
uim_prov_rx(const uint8_t *d, uint32_t len)
{
	uint16_t msg = 0, l = 0;
	if (len < 7) {
		return;
	}
	memcpy(&msg, d + 3, 2);
	if (msg == 0x38) {
		uint16_t res = 0, err = 0;
		if (len >= 14) {
			memcpy(&res, d + 10, 2);
			memcpy(&err, d + 12, 2);
		}
		LOG("uim prov: CHANGE_PROVISIONING_SESSION -> result %u error %#x", res, err);
		return;
	}
	if (msg != 0x2f) {
		return;
	}
	const uint8_t *v = qm_find(d, len, 0x10, &l);
	if (v == NULL || l < 9) {
		LOG("uim prov: card status without the status TLV (%u bytes)", len);
		return;
	}
	uint16_t gw;
	memcpy(&gw, v, 2);
	uint32_t at = 9, nslots = v[8];
	int best_slot = -1, best_type = 0;
	uint8_t aid[32], aid_len = 0;
	for (uint32_t sl = 0; sl < nslots && at + 6 <= l; sl++) {
		uint8_t card = v[at], napp = v[at + 5];
		at += 6;
		for (uint32_t a = 0; a < napp && at + 7 <= l; a++) {
			uint8_t type = v[at], state = v[at + 1], alen = v[at + 6];
			if (at + 7 + alen + 7 > l) {
				at = l;
				break;
			}
			LOG("uim prov: slot %u card %u app %u type %u state %u", sl + 1, card, a, type, state);
			if (card == 1 && (type == 2 || (type == 1 && best_type != 2)) && best_slot < 0 && alen <= sizeof(aid)) {
				best_slot = (int)sl + 1;
				best_type = type;
				aid_len = alen;
				memcpy(aid, v + at + 7, alen);
			}
			at += 7u + alen + 7u;
		}
	}
	if (gw != 0xffff) {
		LOG("uim prov: GW primary session already on application %#x", gw);
		return;
	}
	if (best_slot < 0) {
		LOG("uim prov: no SIM/USIM application on a present card");
		return;
	}
	uint8_t req[7 + 5 + 3 + 2 + 32];
	uint16_t n = 7;
	req[n++] = 0x01; req[n++] = 2; req[n++] = 0; req[n++] = 0; req[n++] = 1;     /* session 0 (GW primary), activate */
	req[n++] = 0x10; req[n++] = (uint8_t)(2 + aid_len); req[n++] = 0;
	req[n++] = (uint8_t)best_slot;
	req[n++] = aid_len;
	memcpy(req + n, aid, aid_len);
	n += aid_len;
	uint16_t body = (uint16_t)(n - 7), id = 0x38;
	req[0] = 0; req[1] = 4; req[2] = 0;
	memcpy(req + 3, &id, 2);
	memcpy(req + 5, &body, 2);
	LOG("uim prov: activating the %s application of slot %d as GW primary", best_type == 2 ? "USIM" : "SIM", best_slot);
	qrtr_send(QRTR_TYPE_DATA, PORT_UIMC, uim_node, uim_port, req, n);
}

static bool
svc_rx(uint32_t src_node, uint32_t src_port, uint32_t dst_port, const uint8_t *data, uint32_t len)
{''')
open(path, 'w', newline='\n').write(s)
print('ok')
