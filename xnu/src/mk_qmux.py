"""lavender: QMUX <-> QRTR bridge between the baseband PCI pipes and the modem (patch 1064), telephony T4.

CommCenter's baseband manager speaks QMI with QMUX framing on the pipes "qmux1"/"qmux2" and asks
the modem's CTL service for client ids. This phone's modem speaks the same QMI messages over QRTR
(IPC router), where a client is a port and there is no CTL service. The bridge, in TopazModem.cpp
(all of it on the modem's poll thread; frames from the user client cross through a locked ring):

- CTL (service 0), answered here: GET_VERSION_INFO 0x0021 (from the modem's service list),
  GET_CLIENT_ID 0x0022 (a client id per service, bound to one of our QRTR ports 0x6000+n; error
  0x1F when the modem has no such service), RELEASE_CLIENT_ID 0x0023, SET_INSTANCE_ID 0x0020,
  SET_DATA_FORMAT 0x0026, SYNC 0x0027; any other CTL request gets "success".
- Any other service: the QMI message is sent to the modem's service from the client's port; what
  comes back to that port (responses and indications) is wrapped in QMUX for the pipe it came on.

SweetWatchdog.cpp: writes on qmux1/qmux2 go to lv_qmux_tx(); lv_qmux_set_rx() delivers frames to
the interface's receive queue. The first 60 messages each way are logged ("qmux ...").

usage: python mk_qmux.py XNU_TREE   (after mk_abp2.py and the TopazModem generators)
"""
import sys

tree = sys.argv[1]


def patch(rel, pairs):
    path = f'{tree}/{rel}'
    s = open(path, newline='').read()
    for old, new in pairs:
        assert s.count(old) == 1, (rel, old[:70], s.count(old))
        s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


patch('iokit/Kernel/arm/TopazModem.cpp', [(r'''static bool
svc_rx(uint32_t src_node, uint32_t src_port, uint32_t dst_port, const uint8_t *data, uint32_t len)
{
''', r'''/* ---------------------------------------------------------------- QMUX bridge (xnu/src/mk_qmux.py) */
#define PORT_QMUX           0x6000
#define QMUX_CLIENTS        96
#define QMUX_RING           64

static struct { bool used; uint8_t chan, svc, cid; uint32_t node, port; } qmux_cl[QMUX_CLIENTS];
static struct { uint8_t *data; uint32_t len; uint8_t chan; } qmux_ring[QMUX_RING];
static unsigned qmux_head, qmux_tail, qmux_logged;
static IOLock *qmux_lock;
static void (*qmux_rx_fn)(unsigned chan, const uint8_t *frame, uint32_t len);

extern "C" void
lv_qmux_set_rx(void (*fn)(unsigned chan, const uint8_t *frame, uint32_t len))
{
	qmux_rx_fn = fn;
}

/* a QMUX frame written by the client of pipe chan (0 = qmux1, 1 = qmux2); any thread */
extern "C" bool
lv_qmux_tx(unsigned chan, const uint8_t *frame, uint32_t len)
{
	bool ok = false;
	if (qmux_lock == NULL || len == 0 || len > 0x4000) {
		return false;
	}
	uint8_t *copy = (uint8_t *)IOMallocData(len);
	if (copy == NULL) {
		return false;
	}
	memcpy(copy, frame, len);
	IOLockLock(qmux_lock);
	if (qmux_tail - qmux_head < QMUX_RING) {
		qmux_ring[qmux_tail % QMUX_RING].data = copy;
		qmux_ring[qmux_tail % QMUX_RING].len = len;
		qmux_ring[qmux_tail % QMUX_RING].chan = (uint8_t)chan;
		qmux_tail++;
		ok = true;
	}
	IOLockUnlock(qmux_lock);
	if (!ok) {
		IOFreeData(copy, len);
	}
	return ok;
}

static void
qmux_deliver(unsigned chan, uint8_t svc, uint8_t cid, const uint8_t *sdu, uint32_t len)
{
	uint8_t *f = (uint8_t *)IOMallocData(6 + len);
	if (f == NULL) {
		return;
	}
	uint16_t flen = (uint16_t)(5 + len);
	f[0] = 1;
	memcpy(f + 1, &flen, 2);
	f[3] = 0x80;                                    /* from the service */
	f[4] = svc;
	f[5] = cid;
	memcpy(f + 6, sdu, len);
	if (qmux_logged++ < 120) {
		uint16_t msg = 0;
		memcpy(&msg, sdu + (svc == 0 ? 2 : 3), len >= 5 ? 2 : 0);
		LOG("qmux%u <- svc %#x client %u msg %#x, %u bytes%s", chan + 1, svc, cid, msg, len,
		    len > 0 && (sdu[0] & (svc == 0 ? 2 : 4)) ? " (indication)" : "");
	}
	if (qmux_rx_fn != NULL) {
		qmux_rx_fn(chan, f, 6 + len);
	}
	IOFreeData(f, 6 + len);
}

/* a CTL response: result TLV 2, then one optional TLV */
static void
qmux_ctl_reply(unsigned chan, uint8_t txn, uint16_t msg, uint16_t err, uint8_t tlv, const void *val, uint16_t vlen)
{
	uint8_t s[6 + 7 + 3 + 600];
	uint16_t n = 0, body = (uint16_t)(7 + (tlv != 0 ? 3 + vlen : 0));
	if (vlen > 600) {
		return;
	}
	s[n++] = 1;                                     /* response */
	s[n++] = txn;
	memcpy(s + n, &msg, 2); n += 2;
	memcpy(s + n, &body, 2); n += 2;
	s[n++] = 2; s[n++] = 4; s[n++] = 0;             /* result: {u16 result, u16 error} */
	uint16_t res = err != 0 ? 1 : 0;
	memcpy(s + n, &res, 2); n += 2;
	memcpy(s + n, &err, 2); n += 2;
	if (tlv != 0) {
		s[n++] = tlv;
		memcpy(s + n, &vlen, 2); n += 2;
		memcpy(s + n, val, vlen); n += vlen;
	}
	qmux_deliver(chan, 0, 0, s, n);
}

static void
qmux_ctl(unsigned chan, const uint8_t *sdu, uint32_t len)
{
	if (len < 6) {
		return;
	}
	uint8_t txn = sdu[1];
	uint16_t msg, l = 0;
	memcpy(&msg, sdu + 2, 2);
	const uint8_t *t1 = NULL;
	for (uint32_t at = 6; at + 3 <= len;) {             /* TLV 1 of the request */
		uint16_t tl;
		memcpy(&tl, sdu + at + 1, 2);
		if (sdu[at] == 1 && at + 3 + tl <= len) {
			t1 = sdu + at + 3;
			l = tl;
		}
		at += 3u + tl;
	}
	switch (msg) {
	case 0x0021: {                                  /* GET_VERSION_INFO: {count, {svc, major, minor} ...} */
		uint8_t v[1 + 5 * 64];
		uint8_t count = 0;
		for (unsigned i = 0; i < q_srv_count && count < 64; i++) {
			bool dup = false;
			if (q_srv[i].svc == 0 || q_srv[i].svc > 0xff) {
				continue;
			}
			for (unsigned j = 0; j < count; j++) {
				dup |= v[1 + 5 * j] == (uint8_t)q_srv[i].svc;
			}
			if (dup) {
				continue;
			}
			uint16_t major = (uint16_t)(q_srv[i].inst & 0xff), minor = 0;
			v[1 + 5 * count] = (uint8_t)q_srv[i].svc;
			memcpy(v + 2 + 5 * count, &major, 2);
			memcpy(v + 4 + 5 * count, &minor, 2);
			count++;
		}
		v[0] = count;
		qmux_ctl_reply(chan, txn, msg, 0, 1, v, (uint16_t)(1 + 5 * count));
		break;
	}
	case 0x0022: {                                  /* GET_CLIENT_ID: service type -> {service, client id} */
		uint8_t svc = t1 != NULL && l >= 1 ? t1[0] : 0, out[2];
		int slot = -1, srv = -1;
		uint8_t cid = 1;
		for (unsigned i = 0; i < q_srv_count; i++) {
			if (q_srv[i].svc == svc) {
				srv = (int)i;
				break;
			}
		}
		for (unsigned i = 0; i < QMUX_CLIENTS; i++) {
			if (qmux_cl[i].used && qmux_cl[i].svc == svc && qmux_cl[i].chan == chan && qmux_cl[i].cid >= cid) {
				cid = (uint8_t)(qmux_cl[i].cid + 1);
			}
			if (!qmux_cl[i].used && slot < 0) {
				slot = (int)i;
			}
		}
		if (srv < 0 || slot < 0 || svc == 0) {
			LOG("qmux%u: client id for service %#x refused (%s)", chan + 1, svc, srv < 0 ? "the modem has no such service" : "table full");
			qmux_ctl_reply(chan, txn, msg, srv < 0 ? 0x1F : 0x05, 0, NULL, 0);
			break;
		}
		qmux_cl[slot].used = true;
		qmux_cl[slot].chan = (uint8_t)chan;
		qmux_cl[slot].svc = svc;
		qmux_cl[slot].cid = cid;
		qmux_cl[slot].node = q_srv[srv].node;
		qmux_cl[slot].port = q_srv[srv].port;
		out[0] = svc;
		out[1] = cid;
		LOG("qmux%u: service %#x %s client %u = our port %#x -> modem %u:%#x", chan + 1, svc, svc_name(svc), cid, PORT_QMUX + slot,
		    q_srv[srv].node, q_srv[srv].port);
		qmux_ctl_reply(chan, txn, msg, 0, 1, out, 2);
		break;
	}
	case 0x0023:                                    /* RELEASE_CLIENT_ID */
		for (unsigned i = 0; i < QMUX_CLIENTS && t1 != NULL && l >= 2; i++) {
			if (qmux_cl[i].used && qmux_cl[i].chan == chan && qmux_cl[i].svc == t1[0] && qmux_cl[i].cid == t1[1]) {
				struct qrtr_ctrl c = { QRTR_TYPE_DEL_CLIENT, QRTR_NODE_APPS, PORT_QMUX + i, 0, 0 };
				qrtr_send(QRTR_TYPE_DEL_CLIENT, QRTR_PORT_CTRL, q_modem_node, QRTR_PORT_CTRL, &c, sizeof(c));
				qmux_cl[i].used = false;
			}
		}
		qmux_ctl_reply(chan, txn, msg, 0, 1, t1 != NULL ? t1 : (const uint8_t *)"\0\0", 2);
		break;
	case 0x0020: {                                  /* SET_INSTANCE_ID -> link id */
		uint16_t link = 0;
		qmux_ctl_reply(chan, txn, msg, 0, 1, &link, 2);
		break;
	}
	default:                                        /* SET_DATA_FORMAT, SYNC, power save, ...: accepted */
		qmux_ctl_reply(chan, txn, msg, 0, 0, NULL, 0);
		break;
	}
}

/* frames from the pipes, on the modem thread */
static void
qmux_pump(void)
{
	for (int n = 0; n < 32; n++) {
		uint8_t *f = NULL;
		uint32_t len = 0;
		unsigned chan = 0;
		IOLockLock(qmux_lock);
		if (qmux_head != qmux_tail) {
			f = qmux_ring[qmux_head % QMUX_RING].data;
			len = qmux_ring[qmux_head % QMUX_RING].len;
			chan = qmux_ring[qmux_head % QMUX_RING].chan;
			qmux_head++;
		}
		IOLockUnlock(qmux_lock);
		if (f == NULL) {
			return;
		}
		for (uint32_t at = 0; at + 6 <= len;) {         /* one or more QMUX frames */
			uint16_t flen;
			memcpy(&flen, f + at + 1, 2);
			if (f[at] != 1 || flen < 5 || at + 1 + flen > len) {
				LOG("qmux%u: not a QMUX frame at %u of %u bytes: %02x %02x %02x %02x %02x %02x", chan + 1, at, len, f[at], f[at + 1],
				    f[at + 2], f[at + 3], f[at + 4], f[at + 5]);
				break;
			}
			uint8_t svc = f[at + 4], cid = f[at + 5];
			const uint8_t *sdu = f + at + 6;
			uint32_t slen = flen - 5u;
			if (qmux_logged++ < 120) {
				uint16_t msg = 0;
				if (slen >= 5) {
					memcpy(&msg, sdu + (svc == 0 ? 2 : 3), 2);
				}
				LOG("qmux%u -> svc %#x client %u msg %#x, %u bytes", chan + 1, svc, cid, msg, slen);
			}
			if (svc == 0) {
				qmux_ctl(chan, sdu, slen);
			} else {
				bool sent = false;
				for (unsigned i = 0; i < QMUX_CLIENTS; i++) {
					if (qmux_cl[i].used && qmux_cl[i].chan == chan && qmux_cl[i].svc == svc && qmux_cl[i].cid == cid) {
						qrtr_send(QRTR_TYPE_DATA, PORT_QMUX + i, qmux_cl[i].node, qmux_cl[i].port, sdu, slen);
						sent = true;
						break;
					}
				}
				if (!sent) {
					LOG("qmux%u: no client %u of service %#x", chan + 1, cid, svc);
				}
			}
			at += 1u + flen;
		}
		IOFreeData(f, len);
	}
}

static bool
svc_rx(uint32_t src_node, uint32_t src_port, uint32_t dst_port, const uint8_t *data, uint32_t len)
{
	if (dst_port >= PORT_QMUX && dst_port < PORT_QMUX + QMUX_CLIENTS) {
		unsigned i = dst_port - PORT_QMUX;
		if (qmux_cl[i].used) {
			qmux_deliver(qmux_cl[i].chan, qmux_cl[i].svc, qmux_cl[i].cid, data, len);
		}
		return true;
	}
'''), ('''	soc_lock = IOLockAlloc();
''', '''	soc_lock = IOLockAlloc();
	qmux_lock = IOLockAlloc();
''')])

# the pump runs with the other per-millisecond work; find the call of txq_pump() inside glink_poll()
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()
a = s.index('\nglink_poll(struct smem_part_hdr *part, unsigned ms)\n')
b = s.index('\ttxq_pump();\n', a)
s = s[:b] + '\ttxq_pump();\n\tif (chan_up()) {\n\t\tqmux_pump();\n\t}\n' + s[b + len('\ttxq_pump();\n'):]
# qmux_pump() is defined after glink_poll(): declare it
c = s.index('/* one pass, every millisecond from the watch loop */')
s = s[:c] + 'static void qmux_pump(void);\n\n' + s[c:]
open(path, 'w', newline='\n').write(s)

patch('iokit/Kernel/arm/SweetWatchdog.cpp', [('''	uint8_t buf[512];
''', '''	const uint32_t bufsz = 0x4000;                 /* a whole QMUX frame for the bridge */
	uint8_t *buf = selector == 2 ? (uint8_t *)IOMallocData(bufsz) : NULL;
'''), ('''				got = lv_abp_fetch(hex, sizeof(hex), in[0], in[1], NULL, buf, sizeof(buf));
''', '''				got = buf != NULL ? lv_abp_fetch(hex, sizeof(hex), in[0], in[1], NULL, buf, bufsz) : 0;
'''), ('''			} else if (args->structureInput != NULL) {
				got = lv_abp_fetch(hex, sizeof(hex), 0, args->structureInputSize, args->structureInput, buf, sizeof(buf));
			} else if (args->structureInputDescriptor != NULL) {
				got = (uint32_t)args->structureInputDescriptor->readBytes(0, buf, MIN(sizeof(buf),
				    (size_t)args->structureInputDescriptor->getLength()));
''', '''			} else if (args->structureInput != NULL && buf != NULL) {
				got = lv_abp_fetch(hex, sizeof(hex), 0, args->structureInputSize, args->structureInput, buf, bufsz);
			} else if (args->structureInputDescriptor != NULL && buf != NULL) {
				got = (uint32_t)args->structureInputDescriptor->readBytes(0, buf, MIN((size_t)bufsz,
				    (size_t)args->structureInputDescriptor->getLength()));
'''), ('''	if (selector == 2 && got != 0) {
		modemSide(buf, got);
	}
''', '''	if (selector == 2 && got != 0) {
		modemSide(buf, got);
	}
	if (buf != NULL) {
		IOFreeData(buf, bufsz);
	}
'''), ('''	if (fItf == NULL || fItf->fIndex != 1 || len < 8) {
		return;                                 /* only the Sahara endpoint answers so far */
	}
''', '''	if (fItf != NULL && (fItf->fIndex == 4 || fItf->fIndex == 5)) {
		if (!lv_qmux_tx(fItf->fIndex - 4, data, len)) {
			IOLog("LV ABP %s: QMUX frame of %u bytes not taken by the modem bridge\\n", fWho, len);
		}
		return;
	}
	if (fItf == NULL || fItf->fIndex != 1 || len < 8) {
		return;                                 /* besides QMUX only the Sahara endpoint answers so far */
	}
'''), ('''static IOLock *lv_abp_lock;
''', '''static IOLock *lv_abp_lock;
extern "C" bool lv_qmux_tx(unsigned chan, const uint8_t *frame, uint32_t len);                 /* TopazModem.cpp */
extern "C" void lv_qmux_set_rx(void (*fn)(unsigned chan, const uint8_t *frame, uint32_t len));
'''), ('''		lv_abp_lock = IOLockAlloc();
''', '''		lv_abp_lock = IOLockAlloc();
		lv_qmux_set_rx(lv_abp_qmux_rx);
'''), ('''static void
lv_abp_publish(unsigned i)
{
''', '''/* a QMUX frame from the modem bridge for pipe chan (0 qmux1, 1 qmux2) */
static void
lv_abp_qmux_rx(unsigned chan, const uint8_t *frame, uint32_t len)
{
	AppleBasebandPCIInterface *itf = chan < 2 ? lv_abp_if[4 + chan] : NULL;
	if (itf != NULL) {
		itf->rx(frame, len);
	}
}

static void
lv_abp_publish(unsigned i)
{
''')])
print('ok')
