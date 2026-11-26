"""lavender: modem_mode=N sets the modem's operating mode once at its start (patch 1072), T5.

QMI trace of run e72: DMS GET_OPERATING_MODE answers 5 ("shutting down"); CommCenter shows it as
kShutdown_Mode and does nothing with it. An Apple baseband comes up in low power and CommCenter
takes it online. modem_mode=N sends DMS SET_OPERATING_MODE (0x002E, TLV 1 = N; 1 = low power,
0 = online) when the modem's DMS service appears, then asks the mode back; both answers are
logged ("dms mode ..."). Without the boot-arg nothing is sent.

usage: python mk_modemmode.py XNU_TREE   (after mk_qmuxlog.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		if (c->a == QMI_SVC_WLFW) {''', '''		if (c->a == 2 && !dms_mode_sent) {              /* DMS: the wanted operating mode, once (mk_modemmode.py) */
			uint32_t mode = 0;
			dms_mode_sent = true;
			if (PE_parse_boot_argn("modem_mode", &mode, sizeof(mode))) {
				uint8_t set[11] = { 0, 1, 0, 0x2e, 0, 4, 0, 1, 1, 0, (uint8_t)mode };
				uint8_t get[7] = { 0, 2, 0, 0x2d, 0, 0, 0 };
				LOG("dms mode: SET_OPERATING_MODE %u to %u:%x", mode, c->c, c->d);
				qrtr_send(QRTR_TYPE_DATA, PORT_DMSC, c->c, c->d, set, sizeof(set));
				qrtr_send(QRTR_TYPE_DATA, PORT_DMSC, c->c, c->d, get, sizeof(get));
			}
		}
		if (c->a == QMI_SVC_WLFW) {''')
sub('''static void
qrtr_rx(const uint8_t *p, uint32_t len)
{
''', '''#define PORT_DMSC           0x4005              /* our QMI client port towards DMS (mk_modemmode.py) */
static bool dms_mode_sent;

static void
qrtr_rx(const uint8_t *p, uint32_t len)
{
''')
sub('''	if (dst_port >= PORT_QMUX && dst_port < PORT_QMUX + QMUX_CLIENTS) {''', '''	if (dst_port == PORT_DMSC) {
		uint16_t msg = 0;
		if (len >= 5) {
			memcpy(&msg, data + 3, 2);
		}
		LOG("dms mode: answer to %#x, %u bytes: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x", msg, len, len > 7 ? data[7] : 0,
		    len > 8 ? data[8] : 0, len > 9 ? data[9] : 0, len > 10 ? data[10] : 0, len > 11 ? data[11] : 0, len > 12 ? data[12] : 0,
		    len > 13 ? data[13] : 0, len > 14 ? data[14] : 0, len > 15 ? data[15] : 0, len > 16 ? data[16] : 0, len > 17 ? data[17] : 0);
		return true;
	}
	if (dst_port >= PORT_QMUX && dst_port < PORT_QMUX + QMUX_CLIENTS) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
