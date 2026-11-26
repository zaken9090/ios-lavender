"""lavender: modem, looking for what starves its diag task (patch 1050).

Run e48: the modem is fully up (41 QMI services, WLFW reports the Wi-Fi firmware version) and dies
13 s later of its own watchdog: "dog_hb.c:266:Task starvation: diag". Two SErrors still arrive at
its start. What differs from Linux, each now closed or made visible:

- modem_qdss=N: the value of the RPM QDSS vote (default 1; 0 = no vote; Linux upstream sends a
  rate in kHz, 2147484).
- every channel the modem opens over GLINK is acknowledged (Linux qcom_glink_rx_open does; only
  IPCRTR was).
- QRTR packets nobody handles are logged (control types other than the known ones, data to a
  port we do not serve), the first 24.
- the firmware volume is read 8 directories deep (was 4: image/modem_pr/mcfg/configs/mcfg_hw/...
  was left out, 316 of the volume's files seen).
- TrustZone's log tail is printed once in the summary when an SError was recorded.

usage: python mk_modemdiag.py XNU_TREE   (after mk_rmtfsbuf.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	bool qdss = topaz_rpm_write(0, 0x306b6c63u, 1, 0x54415453u, 1);
	LOG("RPM qdss clock on: %s", qdss ? "acked" : "FAILED");
''', '''	uint32_t qdss_val = 1;
	(void)PE_parse_boot_argn("modem_qdss", &qdss_val, sizeof(qdss_val));
	bool qdss = qdss_val == 0 || topaz_rpm_write(0, 0x306b6c63u, 1, 0x54415453u, qdss_val);
	LOG("RPM qdss clock, value %u: %s", qdss_val, qdss_val == 0 ? "not voted" : qdss ? "acked" : "FAILED");
''')
sub('''			if (!g_open_sent) {
				send_open();
			}
		}
		break;
''', '''			if (!g_open_sent) {
				send_open();
			}
		} else {
			send_cmd(CMD_OPEN_ACK, (uint16_t)m.p1, 0);     /* lavender: as Linux, every remote open is acked */
		}
		break;
''')
sub('''		if (hlen + size <= len) {
			(void)svc_rx(src_node, src_port, dst_port, p + hlen, size);
		}
		break;
''', '''		if (hlen + size <= len) {
			if (!svc_rx(src_node, src_port, dst_port, p + hlen, size) && q_odd++ < 24) {
				const uint8_t *d = p + hlen;
				LOG("t=%u ms: qrtr data nobody serves: %u:%x -> port %x, %u bytes: %02x %02x %02x %02x %02x %02x %02x %02x", g_ms,
				    src_node, src_port, dst_port, size, size > 0 ? d[0] : 0, size > 1 ? d[1] : 0, size > 2 ? d[2] : 0,
				    size > 3 ? d[3] : 0, size > 4 ? d[4] : 0, size > 5 ? d[5] : 0, size > 6 ? d[6] : 0, size > 7 ? d[7] : 0);
			}
		}
		break;
''')
sub('''	case QRTR_TYPE_RESUME_TX:
		q_resumes++;
		break;
	default:
		break;
	}
}
''', '''	case QRTR_TYPE_RESUME_TX:
		q_resumes++;
		break;
	default:
		if (q_odd++ < 24) {
			LOG("t=%u ms: qrtr control type %u from %u:%x to port %x: %x %x %x %x", g_ms, type, src_node, src_port, dst_port,
			    c->a, c->b, c->c, c->d);
		}
		break;
	}
}
''')
sub('''static void
qrtr_rx(const uint8_t *p, uint32_t len)
{
''', '''static unsigned q_odd;

static void
qrtr_rx(const uint8_t *p, uint32_t len)
{
''')
sub('''			if (depth < 4) {''', '''			if (depth < 8) {''')
sub('''	lv_serror_report("summary");
''', '''	lv_serror_report("summary");
	static bool tz_once;
	if (lv_serror_count != 0 && !tz_once) {
		tz_once = true;
		tz_log_tail();
	}
''')
sub('''static void smem_list(struct smem_part_hdr *p);
static void lv_serror_report(const char *when);
''', '''static void smem_list(struct smem_part_hdr *p);
static void lv_serror_report(const char *when);
static void tz_log_tail(void);
extern "C" volatile uint32_t lv_serror_count;
''')
open(path, 'w', newline='\n').write(s)
print('ok')
