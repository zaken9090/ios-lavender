"""lavender: the Wi-Fi MAC address from the modem's NV item 4678 (patch 1083).

Run e88: persist has no MAC file (its folders: sensors, audio, camera, ...). Xiaomi phones keep the
WLAN address in the modem's NV memory, item 4678; their nv_mac tool reads it at boot. The kernel
asks the same through the modem's DIAG command service (QRTR 0x1001 instance 1, which the modem
serves): DIAG NV_READ_F (0x26) {item 4678}. Read only - nothing is written to the modem's NV.

The answer may come on the DIAG data channel the host serves (raw or HDLC framed) or back to the
asking port; both are looked at. The address is taken only if no persist file gave one; the log
shows it with the last three bytes masked, in both byte orders (NV keeps it reversed on some
phones; the order is chosen by which one gives a unicast, globally assigned address - else as
stored). modem_macnv=0 skips it.

usage: python mk_wlanmacnv.py XNU_TREE   (after mk_wlanmac2.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''#define PORT_UIMC           0x4006              /* our QMI client port towards UIM (mk_uimprov.py) */
''', '''#define PORT_UIMC           0x4006              /* our QMI client port towards UIM (mk_uimprov.py) */
#define PORT_DIAGC          0x4013              /* our DIAG command client (mk_wlanmacnv.py) */
static bool nv_mac_asked, nv_mac_done, persist_mac_done;
static uint8_t nv_mac[6];

/* a DIAG NV_READ_F answer for item 4678, raw or HDLC framed: true when the address was taken */
static bool
nv_mac_rx(const uint8_t *p, uint32_t len)
{
	uint8_t raw[160];
	uint32_t n = 0;
	if (nv_mac_done || len < 3) {
		return false;
	}
	for (uint32_t i = 0; i < len && n < sizeof(raw); i++) {      /* unescape HDLC; raw bytes pass unchanged */
		if (p[i] == 0x7e) {
			if (n == 0) {
				continue;
			}
			break;
		}
		raw[n++] = (p[i] == 0x7d && i + 1 < len) ? (uint8_t)(p[++i] ^ 0x20) : p[i];
	}
	if (n < 3 + 6 || raw[0] != 0x26 || raw[1] != (4678 & 0xff) || raw[2] != (4678 >> 8)) {
		return false;
	}
	uint16_t status = n >= 3 + 128 + 2 ? (uint16_t)(raw[131] | (raw[132] << 8)) : 0;
	const uint8_t *m = raw + 3;
	LOG("wlan mac: NV 4678 status %u: as stored %02x:%02x:%02x:**:**:**, reversed %02x:%02x:%02x:**:**:**", status, m[0], m[1],
	    m[2], m[5], m[4], m[3]);
	if (status != 0 || (m[0] | m[1] | m[2] | m[3] | m[4] | m[5]) == 0) {
		nv_mac_done = true;
		return false;
	}
	bool stored_ok = !(m[0] & 3), rev_ok = !(m[5] & 3);
	for (int i = 0; i < 6; i++) {
		nv_mac[i] = (!stored_ok && rev_ok) ? m[5 - i] : m[i];
	}
	nv_mac_done = true;
	return true;
}
''')
# ask when the modem's DIAG command service appears
sub('''		if (c->a == 2 && !dms_mode_sent) {''', '''		if (c->a == 0x1001 && c->b == 1 && !nv_mac_asked) {       /* DIAG CMD: NV_READ_F item 4678 (mk_wlanmacnv.py) */
			uint32_t on = 1;
			nv_mac_asked = true;
			(void)PE_parse_boot_argn("modem_macnv", &on, sizeof(on));
			if (on != 0) {
				uint8_t req[133];
				bzero(req, sizeof(req));
				req[0] = 0x26;
				req[1] = 4678 & 0xff;
				req[2] = 4678 >> 8;
				qrtr_send(QRTR_TYPE_DATA, PORT_DIAGC, c->c, c->d, req, sizeof(req));
				LOG("wlan mac: NV 4678 asked from the modem's DIAG (%u:%x)", c->c, c->d);
			}
		}
		if (c->a == 2 && !dms_mode_sent) {''')
# answers: to our client port, or on the DIAG data/cntl channels we serve
sub('''	if (dst_port >= PORT_DIAG && dst_port < PORT_DIAG + 3) {
		unsigned k = dst_port - PORT_DIAG;''', '''	if (dst_port == PORT_DIAGC) {
		if (!nv_mac_rx(data, len)) {
			LOG("t=%u ms: DIAG answer to our command, %u bytes: %02x %02x %02x %02x", g_ms, len, len > 0 ? data[0] : 0,
			    len > 1 ? data[1] : 0, len > 2 ? data[2] : 0, len > 3 ? data[3] : 0);
		}
		return true;
	}
	if (dst_port >= PORT_DIAG && dst_port < PORT_DIAG + 3 && !nv_mac_done) {
		(void)nv_mac_rx(data, len);
	}
	if (dst_port >= PORT_DIAG && dst_port < PORT_DIAG + 3) {
		unsigned k = dst_port - PORT_DIAG;''')
# use it when persist had nothing
sub('''				(void)wlan_mac_from_persist();  /* mk_wlanmac.py */''', '''				persist_mac_done = wlan_mac_from_persist();     /* mk_wlanmac.py */
				if (!persist_mac_done && nv_mac[0] | nv_mac[1] | nv_mac[2] | nv_mac[3] | nv_mac[4] | nv_mac[5]) {
					memcpy(our_mac, nv_mac, 6);         /* mk_wlanmacnv.py */
					LOG("wlan mac: %02x:%02x:%02x:**:**:** from the modem's NV (read only)", our_mac[0], our_mac[1], our_mac[2]);
				}''')
open(path, 'w', newline='\n').write(s)
print('ok')
