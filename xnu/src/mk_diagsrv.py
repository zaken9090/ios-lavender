"""lavender: the host serves the modem's DIAG sockets (patch 1075).

Run e76 (no Wi-Fi firmware started): 75 s after its start the modem died of its watchdog,
"dog_hb.c:266:Task starvation: diag" - the crash seen before with the WLAN firmware running
(13 s, much more diag traffic). The modem's DIAG task sends its logs to the apps processor over
IPC-router sockets: on Android the apps side serves service 0x1001 with instances 0 (CNTL),
2 (DATA) and 4 (DCI) for the modem (msm-4.4 drivers/char/diag/diagfwd_socket.c); the modem looks
them up and writes there. Nobody served them here, so the task waits until the watchdog bites.

Now the three servers are announced with the other host services; what arrives is counted and
dropped (the first messages of each are logged), flow control is answered as for any data.
modem_diag=0 leaves them out.

usage: python mk_diagsrv.py XNU_TREE   (after mk_qmuxlog2.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	for (unsigned i = 0; i < 3; i++) {
		struct qrtr_ctrl c = { QRTR_TYPE_NEW_SERVER, svc[i][0], svc[i][1], QRTR_NODE_APPS, svc[i][2] };
		qrtr_send(QRTR_TYPE_NEW_SERVER, QRTR_PORT_CTRL, q_modem_node, QRTR_PORT_CTRL, &c, sizeof(c));
	}
	LOG("t=%u ms: announced pd-mapper 0x40, tftp 0x1000, rmtfs 0x0e", g_ms);
''', '''	for (unsigned i = 0; i < 3; i++) {
		struct qrtr_ctrl c = { QRTR_TYPE_NEW_SERVER, svc[i][0], svc[i][1], QRTR_NODE_APPS, svc[i][2] };
		qrtr_send(QRTR_TYPE_NEW_SERVER, QRTR_PORT_CTRL, q_modem_node, QRTR_PORT_CTRL, &c, sizeof(c));
	}
	LOG("t=%u ms: announced pd-mapper 0x40, tftp 0x1000, rmtfs 0x0e", g_ms);
	uint32_t diag = 1;
	(void)PE_parse_boot_argn("modem_diag", &diag, sizeof(diag));
	if (diag != 0) {
		/* DIAG sockets of the modem: service 0x1001, instances 0 CNTL, 2 DATA, 4 DCI (mk_diagsrv.py) */
		for (unsigned i = 0; i < 3; i++) {
			struct qrtr_ctrl c = { QRTR_TYPE_NEW_SERVER, 0x1001, 2 * i, QRTR_NODE_APPS, PORT_DIAG + i };
			qrtr_send(QRTR_TYPE_NEW_SERVER, QRTR_PORT_CTRL, q_modem_node, QRTR_PORT_CTRL, &c, sizeof(c));
		}
		LOG("t=%u ms: announced DIAG 0x1001 instances 0, 2, 4 (ports %#x..)", g_ms, PORT_DIAG);
	}
''')
sub('''#define PORT_DMSC           0x4005              /* our QMI client port towards DMS (mk_modemmode.py) */
''', '''#define PORT_DMSC           0x4005              /* our QMI client port towards DMS (mk_modemmode.py) */
#define PORT_DIAG           0x4010              /* DIAG CNTL, DATA, DCI servers (mk_diagsrv.py) */
static uint32_t diag_msgs[3], diag_bytes[3];
''')
sub('''	if (dst_port == PORT_DMSC) {''', '''	if (dst_port >= PORT_DIAG && dst_port < PORT_DIAG + 3) {
		unsigned k = dst_port - PORT_DIAG;
		diag_msgs[k]++;
		diag_bytes[k] += len;
		if (diag_msgs[k] <= 4 || (diag_msgs[k] & (diag_msgs[k] - 1)) == 0) {
			LOG("t=%u ms: DIAG %s from %u:%x: message %u (%u bytes so far): %02x %02x %02x %02x %02x %02x %02x %02x", g_ms,
			    k == 0 ? "CNTL" : k == 1 ? "DATA" : "DCI", src_node, src_port, diag_msgs[k], diag_bytes[k],
			    len > 0 ? data[0] : 0, len > 1 ? data[1] : 0, len > 2 ? data[2] : 0, len > 3 ? data[3] : 0,
			    len > 4 ? data[4] : 0, len > 5 ? data[5] : 0, len > 6 ? data[6] : 0, len > 7 ? data[7] : 0);
		}
		return true;
	}
	if (dst_port == PORT_DMSC) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
