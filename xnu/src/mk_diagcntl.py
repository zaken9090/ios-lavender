"""lavender: the DIAG control handshake before asking NV 4678 (patch 1084).

Run e89: the NV_READ_F for the Wi-Fi MAC (item 4678) went to the modem's DIAG command service
before anything else and got no answer. Android's diag driver (msm-4.4 diag_masks.c
diag_send_feature_mask_update) answers the peripheral's feature mask on the control channel with
its own - DIAG_CTRL_MSG_FEATURE (8) {id, data_len, mask_len 2, 2 bytes} - and only then talks
to it; with F_DIAG_REQ_RSP_SUPPORT the peripheral sends command responses back on the command
connection.

Now: when the modem's first control message (its feature mask) arrives on our CNTL server, the
kernel answers with a feature mask (feature-mask support, separate command/response, sockets)
to that sender, and then sends the NV read (item 4678, and 447 - the Bluetooth address on
Qualcomm phones) from its own port. Read only, as before; answers are logged masked.

usage: python mk_diagcntl.py XNU_TREE   (after mk_wlanmacnv.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


# do not ask at once: remember where the modem's command service is
sub('''			if (on != 0) {
				uint8_t req[133];
				bzero(req, sizeof(req));
				req[0] = 0x26;
				req[1] = 4678 & 0xff;
				req[2] = 4678 >> 8;
				qrtr_send(QRTR_TYPE_DATA, PORT_DIAGC, c->c, c->d, req, sizeof(req));
				LOG("wlan mac: NV 4678 asked from the modem's DIAG (%u:%x)", c->c, c->d);
			}''', '''			if (on != 0) {
				diag_cmd_node = c->c;                   /* asked after the control handshake (mk_diagcntl.py) */
				diag_cmd_port = c->d;
				diag_cmd_known = true;
				diag_nv_maybe_ask();
			}''')
sub('''static bool nv_mac_asked, nv_mac_done, persist_mac_done;
''', '''static bool nv_mac_asked, nv_mac_done, persist_mac_done;
static bool diag_cmd_known, diag_cntl_done, diag_nv_sent;
static uint32_t diag_cmd_node, diag_cmd_port;

static void
diag_nv_read(uint16_t item)
{
	uint8_t req[133];
	bzero(req, sizeof(req));
	req[0] = 0x26;                                  /* NV_READ_F */
	req[1] = (uint8_t)item;
	req[2] = (uint8_t)(item >> 8);
	qrtr_send(QRTR_TYPE_DATA, PORT_DIAGC, diag_cmd_node, diag_cmd_port, req, sizeof(req));
}

/* the NV reads, once the modem's command service is known and the control handshake is done */
static void
diag_nv_maybe_ask(void)
{
	if (!diag_nv_sent && diag_cmd_known && diag_cntl_done) {
		diag_nv_sent = true;
		diag_nv_read(4678);                     /* WLAN MAC */
		diag_nv_read(447);                      /* Bluetooth address */
		LOG("wlan mac: NV 4678 and 447 asked from the modem's DIAG (%u:%x)", diag_cmd_node, diag_cmd_port);
	}
}
''')
# answer the modem's feature mask on the control channel
sub('''	if (dst_port >= PORT_DIAG && dst_port < PORT_DIAG + 3 && !nv_mac_done) {
		(void)nv_mac_rx(data, len);
	}''', '''	if (dst_port == PORT_DIAG && !diag_cntl_done && len >= 8 && data[0] == 8 && data[1] == 0 && data[2] == 0 && data[3] == 0) {
		/* DIAG_CTRL_MSG_FEATURE {id 8, data_len 6, mask_len 2, mask}: mask support, separate cmd/rsp, sockets */
		uint8_t fm[14] = { 8, 0, 0, 0, 6, 0, 0, 0, 2, 0, 0, 0, 0x11, 0x20 };
		qrtr_send(QRTR_TYPE_DATA, PORT_DIAG, src_node, src_port, fm, sizeof(fm));
		diag_cntl_done = true;
		LOG("t=%u ms: DIAG: feature mask answered to %u:%x", g_ms, src_node, src_port);
		diag_nv_maybe_ask();
	}
	if (dst_port >= PORT_DIAG && dst_port < PORT_DIAG + 3 && !nv_mac_done) {
		(void)nv_mac_rx(data, len);
	}''')
sub('''	if (dst_port == PORT_DIAGC) {
		if (!nv_mac_rx(data, len)) {''', '''	if (dst_port == PORT_DIAGC && len >= 3 + 6 && data[0] == 0x26 && data[1] == (447 & 0xff) && data[2] == (447 >> 8)) {
		uint16_t st = len >= 133 ? (uint16_t)(data[131] | (data[132] << 8)) : 0;
		memcpy(bt_addr_nv, data + 3, 6);
		LOG("bt addr: NV 447 status %u: as stored %02x:%02x:%02x:**:**:**, reversed %02x:%02x:%02x:**:**:**", st, data[3], data[4],
		    data[5], data[8], data[7], data[6]);
		return true;
	}
	if (dst_port == PORT_DIAGC) {
		if (!nv_mac_rx(data, len)) {''')
sub('''static uint32_t diag_cmd_node, diag_cmd_port;
''', '''static uint32_t diag_cmd_node, diag_cmd_port;
static uint8_t bt_addr_nv[6];                           /* for the Bluetooth driver later */
''')
open(path, 'w', newline='\n').write(s)
print('ok')
