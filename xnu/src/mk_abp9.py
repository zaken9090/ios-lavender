"""lavender: baseband PCI pipes survive a baseband reset; bigger receive queue (patch 1073), T4.

Run e75 (SIM inserted): the first boot reached QMI, then "qmux1: receive queue full" (16 frames;
with a SIM the modem sends many indications) - answers were lost and the manager reset the
baseband. After each reset: "Failed to engage router", in a loop. The manager keeps its qmux
pipes open through a reset (it never closes or reopens them), while the stand-in terminated every
interface when the baseband went "off" and published new ones: the old pipes it still held were
dead.

- the receive queue holds 512 frames (pending reads stay at 16)
- once published, an interface stays: a reset hides nothing; "pbl"/"sahara" are added at the rom
  stage, the mission interfaces at the mission stage
- at a reset the QMUX bridge drops its clients (lv_qmux_reset(): DEL_CLIENT to the modem for each)
  so that client ids start afresh and the table does not fill up

usage: python mk_abp9.py XNU_TREE   (after mk_modemmode.py)
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


patch('iokit/Kernel/arm/SweetWatchdog.cpp', [
    ('''#define LV_ABP_QMAX     16
''', '''#define LV_ABP_QMAX     16              /* pending asynchronous reads */
#define LV_ABP_RXQ      512             /* frames waiting for a read (mk_abp9.py) */
'''),
    ('''	struct { uint8_t *data; uint32_t len; } fQ[LV_ABP_QMAX];
''', '''	struct { uint8_t *data; uint32_t len; } fQ[LV_ABP_RXQ];
'''),
    ('''	if (fQCount < LV_ABP_QMAX) {''', '''	if (fQCount < LV_ABP_RXQ) {'''),
    ('''			unsigned at = (fQHead + fQCount) % LV_ABP_QMAX;''', '''			unsigned at = (fQHead + fQCount) % LV_ABP_RXQ;'''),
    ('''					fItf->fQHead = (fItf->fQHead + 1) % LV_ABP_QMAX;''', '''					fItf->fQHead = (fItf->fQHead + 1) % LV_ABP_RXQ;'''),
    ('''		if (!(want & (1u << i))) {
			lv_abp_unpublish(i);
		}''', '''		if (false && !(want & (1u << i))) {     /* mk_abp9.py: the manager keeps its pipes through a reset */
			lv_abp_unpublish(i);
		}'''),
    ('''	if (stage == LV_ABP_MISSION && lv_abp_bb != NULL) {''', '''	if (stage == LV_ABP_OFF) {
		lv_qmux_reset();
	}
	if (stage == LV_ABP_MISSION && lv_abp_bb != NULL) {'''),
    ('''extern "C" void lv_qmux_set_rx(void (*fn)(unsigned chan, const uint8_t *frame, uint32_t len));
''', '''extern "C" void lv_qmux_set_rx(void (*fn)(unsigned chan, const uint8_t *frame, uint32_t len));
extern "C" void lv_qmux_reset(void);
'''),
])

patch('iokit/Kernel/arm/TopazModem.cpp', [
    ('''extern "C" void
lv_qmux_set_rx(void (*fn)(unsigned chan, const uint8_t *frame, uint32_t len))
{''', '''static volatile bool qmux_reset_wanted;

/* the baseband was reset by its manager: forget the bridge's clients (done on the modem thread) */
extern "C" void
lv_qmux_reset(void)
{
	qmux_reset_wanted = true;
}

static void
qmux_reset_now(void)
{
	unsigned n = 0;
	qmux_reset_wanted = false;
	for (unsigned i = 0; i < QMUX_CLIENTS; i++) {
		if (qmux_cl[i].used) {
			struct qrtr_ctrl c = { QRTR_TYPE_DEL_CLIENT, QRTR_NODE_APPS, PORT_QMUX + i, 0, 0 };
			qrtr_send(QRTR_TYPE_DEL_CLIENT, QRTR_PORT_CTRL, q_modem_node, QRTR_PORT_CTRL, &c, sizeof(c));
			qmux_cl[i].used = false;
			n++;
		}
	}
	LOG("qmux: baseband reset by its manager, %u clients dropped", n);
}

extern "C" void
lv_qmux_set_rx(void (*fn)(unsigned chan, const uint8_t *frame, uint32_t len))
{'''),
    ('''static void
qmux_pump(void)
{
''', '''static void
qmux_pump(void)
{
	if (qmux_reset_wanted) {
		qmux_reset_now();
	}
'''),
])
print('ok')
