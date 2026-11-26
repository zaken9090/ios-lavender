"""lavender: the QMUX bridge logs QMI messages with their first bytes (patch 1071), telephony T5.

Run e71: QMI flows (CommCenter read the modem's firmware version, MPSS.AT.3.1-00777-SDM660...)
and it now reports the operating mode "shutdown" and no SIM information. To see what the modem
answers, every bridged message outside CTL is logged with its service, message id and the first
40 bytes after the QMI header - up to qmux_log=N messages (default 1500); CTL lines stay as they
were, within the same budget.

usage: python mk_qmuxlog.py XNU_TREE   (after mk_qmux.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static unsigned qmux_head, qmux_tail, qmux_logged;
''', '''static unsigned qmux_head, qmux_tail, qmux_logged;
static uint32_t qmux_log_max = 1500;

/* one bridged message: direction, service, client, message id, the bytes after the QMI header */
static void
qmux_log(const char *dir, unsigned chan, uint8_t svc, uint8_t cid, const uint8_t *sdu, uint32_t len)
{
	static bool parsed;
	char hex[3 * 40 + 1];
	uint32_t hdr = svc == 0 ? 6 : 7, n = 0;
	uint16_t msg = 0;

	if (!parsed) {
		parsed = true;
		(void)PE_parse_boot_argn("qmux_log", &qmux_log_max, sizeof(qmux_log_max));
	}
	if (qmux_logged++ >= qmux_log_max || len < 5) {
		return;
	}
	memcpy(&msg, sdu + (svc == 0 ? 2 : 3), 2);
	hex[0] = 0;
	for (uint32_t i = hdr; i < len && n < 40; i++, n++) {
		snprintf(hex + 3 * n, 4, "%02x ", sdu[i]);
	}
	LOG("qmux%u %s svc %#x %s client %u msg %#x%s, %u bytes: %s", chan + 1, dir, svc, svc_name(svc), cid, msg,
	    (sdu[0] & (svc == 0 ? 2 : 4)) ? " IND" : (sdu[0] & (svc == 0 ? 1 : 2)) ? " rsp" : "", len, hex);
}
''')
sub('''	if (qmux_logged++ < 120) {
		uint16_t msg = 0;
		memcpy(&msg, sdu + (svc == 0 ? 2 : 3), len >= 5 ? 2 : 0);
		LOG("qmux%u <- svc %#x client %u msg %#x, %u bytes%s", chan + 1, svc, cid, msg, len,
		    len > 0 && (sdu[0] & (svc == 0 ? 2 : 4)) ? " (indication)" : "");
	}
''', '''	qmux_log("<-", chan, svc, cid, sdu, len);
''')
sub('''			if (qmux_logged++ < 120) {
				uint16_t msg = 0;
				if (slen >= 5) {
					memcpy(&msg, sdu + (svc == 0 ? 2 : 3), 2);
				}
				LOG("qmux%u -> svc %#x client %u msg %#x, %u bytes", chan + 1, svc, cid, msg, slen);
			}
''', '''			qmux_log("->", chan, svc, cid, sdu, slen);
''')
open(path, 'w', newline='\n').write(s)
print('ok')
