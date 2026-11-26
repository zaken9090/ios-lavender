"""lavender: the Sahara endpoint asks for images the way a loader does (patch 1067), telephony T3.

Run e67: the updater took our HELLO, answered HELLO_RESP - and failed "BBUpdater error 12 - failed
handling sahara mode operation" on our END_IMAGE_TX. Its image engine (BBUEUR10Programmer) waits
for the device to pull every image of the phase: READ_DATA {image id, offset, length}, it writes
the bytes, END_IMAGE_TX {image id, status 0}; when all its items are served it sends DONE and takes
DONE_RESP. A second Sahara session follows for the firmware images. The image ids are the
updater's own item ids and are not known up front (candidates: Qualcomm's Sahara ids it lists).

The stand-in now learns them: per session it requests 16 bytes of the next candidate id that has
not failed; data back means the id exists (END_IMAGE_TX, then the next id unless DONE comes within
250 ms); a close without data marks the id bad for that session. The updater retries about once a
second after a failure, so the right set is found in a few of its attempts and kept until reboot.

- a HELLO is queued whenever "sahara" is opened (each session starts with one)
- after the first DONE the mission interfaces are published next to the boot ones (the updater
  opens what it needs: the next Sahara session, then "diag")

usage: python mk_abp5.py XNU_TREE   (after mk_abp4.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


def cut(start, end, new):
    global s
    assert s.count(start) == 1 and s.count(end) == 1, (start[:50], s.count(start), end[:50], s.count(end))
    a, b = s.index(start), s.index(end)
    assert a < b
    s = s[:a] + new + s[b:]


sub('''#include <IOKit/IOLocks.h>
''', '''#include <IOKit/IOLocks.h>
#include <kern/thread_call.h>
#include <kern/clock.h>
''')
sub('''	uint32_t want = stage == LV_ABP_ROM || stage == LV_ABP_SAHARA ? 3u : stage == LV_ABP_MISSION ? lv_abp_ifs : 0;
''', '''	uint32_t want = stage == LV_ABP_ROM || stage == LV_ABP_SAHARA ? 3u : stage == LV_ABP_MISSION ? (lv_abp_ifs | 3u) : 0;
''')
sub('''	if ((stage == LV_ABP_ROM || stage == LV_ABP_SAHARA) && lv_abp_if[1] != NULL && !had_sahara) {''',
    '''	if (false && had_sahara) {                      /* the HELLO is queued when "sahara" is opened (mk_abp5.py) */''')
sub('''		lv_abp_set_stage(LV_ABP_ROM);
	}
}
''', '''		lv_sah_attempt();
		lv_abp_set_stage(LV_ABP_ROM);
	}
}
''')
sub('''/* AppleBaseband: ResetModem (0), PowerOnModem (1, arg 1 = on), PowercycleModem (6) */
''', '''static void lv_sah_attempt(void);

/* AppleBaseband: ResetModem (0), PowerOnModem (1, arg 1 = on), PowercycleModem (6) */
''')
sub('''		case 0: what = "open"; break;
		case 1: what = "close"; fItf->dropRead(); break;
''', '''		case 0:
			what = "open";
			if (fItf->fIndex == 1) {
				lv_sah_open(fItf);
			}
			break;
		case 1:
			what = "close";
			fItf->dropRead();
			if (fItf->fIndex == 1) {
				lv_sah_close();
			}
			break;
''')

cut('''/* what the "modem" does with data the client wrote */
''', '''IOReturn
SweetABPUserClient::externalMethod(''', r'''/*
 * The Sahara device side (xnu/src/mk_abp5.py): sessions of one boot attempt, the image ids tried.
 */
#define LV_SAH_NCAND    20
#define LV_SAH_LEN      16u
static const uint32_t lv_sah_cand[LV_SAH_NCAND] = {
	0x15, 0x06, 0x1c, 0x08, 0x17, 0x19, 0x1f, 0x1d, 0x4700, 0x05, 0x1e, 0x21, 0x22, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2a, 0x30,
};
static uint32_t lv_sah_bad[2], lv_sah_good[2];         /* per session: candidate bits known bad / known good */
static uint32_t lv_sah_served;                         /* candidate bits served in this session */
static int lv_sah_session = -1, lv_sah_pending = -1;   /* session of this attempt; candidate asked, no data yet */
static bool lv_sah_done;
static thread_call_t lv_sah_timer;
static AppleBasebandPCIInterface *lv_sah_itf;

static void
lv_sah_attempt(void)
{
	lv_sah_session = -1;
	lv_sah_pending = -1;
	lv_sah_done = false;
}

/* ask for the next image of this session; false when no candidate is left */
static bool
lv_sah_request(void)
{
	int sn = lv_sah_session > 1 ? 1 : lv_sah_session < 0 ? 0 : lv_sah_session;
	AppleBasebandPCIInterface *itf = lv_sah_itf;
	if (itf == NULL || lv_sah_done) {
		return false;
	}
	for (int pass = 0; pass < 2; pass++) {                  /* ids known good first, then untried ones */
		for (int i = 0; i < LV_SAH_NCAND; i++) {
			uint32_t bit = 1u << i;
			if ((lv_sah_served & bit) || (lv_sah_bad[sn] & bit) || (pass == 0 && !(lv_sah_good[sn] & bit))) {
				continue;
			}
			uint32_t rd[5] = { 3, 20, lv_sah_cand[i], 0, LV_SAH_LEN };
			lv_sah_pending = i;
			IOLog("LV ABP sahara: session %d: READ_DATA image %#x, %u bytes\n", lv_sah_session, lv_sah_cand[i], LV_SAH_LEN);
			itf->rx(rd, sizeof(rd));
			return true;
		}
	}
	IOLog("LV ABP sahara: session %d: no image id left to ask for\n", lv_sah_session);
	return false;
}

static void
lv_sah_tick(__unused thread_call_param_t p0, __unused thread_call_param_t p1)
{
	if (!lv_sah_done && lv_sah_pending < 0 && lv_sah_itf != NULL) {
		(void)lv_sah_request();                         /* no DONE came: the updater has more items */
	}
}

static void
lv_sah_open(AppleBasebandPCIInterface *itf)
{
	uint32_t hello[12] = { 1, 0x30, 2, 1, 0x400, 0, 0, 0, 0, 0, 0, 0 };
	if (lv_sah_timer == NULL) {
		lv_sah_timer = thread_call_allocate(lv_sah_tick, NULL);
	}
	lv_sah_session++;
	lv_sah_served = 0;
	lv_sah_pending = -1;
	lv_sah_done = false;
	lv_sah_itf = itf;
	IOLog("LV ABP sahara: session %d opens (good %#x/%#x, bad %#x/%#x): HELLO\n", lv_sah_session, lv_sah_good[0], lv_sah_good[1],
	    lv_sah_bad[0], lv_sah_bad[1]);
	itf->rx(hello, sizeof(hello));
}

static void
lv_sah_close(void)
{
	int sn = lv_sah_session > 1 ? 1 : lv_sah_session < 0 ? 0 : lv_sah_session;
	if (lv_sah_timer != NULL) {
		(void)thread_call_cancel(lv_sah_timer);
	}
	if (lv_sah_pending >= 0 && !lv_sah_done) {
		lv_sah_bad[sn] |= 1u << lv_sah_pending;
		IOLog("LV ABP sahara: session %d closed on image %#x: that id is not one of its items\n", lv_sah_session,
		    lv_sah_cand[lv_sah_pending]);
	}
	lv_sah_pending = -1;
	lv_sah_itf = NULL;
}

/* what the "modem" does with data the client wrote */
void
SweetABPUserClient::modemSide(const uint8_t *data, uint32_t len)
{
	if (fItf != NULL && (fItf->fIndex == 4 || fItf->fIndex == 5)) {
		if (!lv_qmux_tx(fItf->fIndex - 4, data, len)) {
			IOLog("LV ABP %s: QMUX frame of %u bytes not taken by the modem bridge\n", fWho, len);
		}
		return;
	}
	if (fItf != NULL && fItf->fIndex == 2) {
		diagSide(data, len);
		return;
	}
	if (fItf == NULL || fItf->fIndex != 1) {
		return;
	}
	int sn = lv_sah_session > 1 ? 1 : lv_sah_session < 0 ? 0 : lv_sah_session;
	uint32_t cmd = 0, plen = 0, w[4] = { 0, 0, 0, 0 };
	if (len >= 8) {
		memcpy(&cmd, data, 4);
		memcpy(&plen, data + 4, 4);
	}
	if (lv_sah_pending >= 0 && !(cmd == 5 && plen == 8 && len == 8)) {
		/* the bytes of the image we asked for: the id is one of the updater's items */
		int i = lv_sah_pending;
		lv_sah_pending = -1;
		lv_sah_good[sn] |= 1u << i;
		lv_sah_served |= 1u << i;
		IOLog("LV ABP sahara: session %d: image %#x served (%u bytes) -> END_IMAGE_TX\n", lv_sah_session, lv_sah_cand[i], len);
		w[0] = 4; w[1] = 16; w[2] = lv_sah_cand[i]; w[3] = 0;
		fItf->rx(w, 16);
		if (lv_sah_timer != NULL) {
			uint64_t deadline;
			clock_interval_to_deadline(250, kMillisecondScale, &deadline);
			(void)thread_call_enter_delayed(lv_sah_timer, deadline);
		}
		return;
	}
	switch (cmd) {
	case 2:                                         /* HELLO_RESP: start pulling images */
		IOLog("LV ABP sahara: session %d: HELLO_RESP\n", lv_sah_session);
		(void)lv_sah_request();
		break;
	case 5:                                         /* DONE -> DONE_RESP: the updater has served all its items */
		if (lv_sah_timer != NULL) {
			(void)thread_call_cancel(lv_sah_timer);
		}
		lv_sah_done = true;
		lv_sah_pending = -1;
		IOLog("LV ABP sahara: session %d: DONE after images %#x -> DONE_RESP\n", lv_sah_session, lv_sah_served);
		w[0] = 6; w[1] = 12; w[2] = 0;
		fItf->rx(w, 12);
		if (lv_abp_stage != LV_ABP_MISSION && lv_abp_hold == 0) {
			lv_abp_set_stage(LV_ABP_MISSION);
		}
		break;
	default:
		IOLog("LV ABP sahara: session %d: command %u (%u bytes) not answered\n", lv_sah_session, cmd, len);
		break;
	}
}

''')
sub('''static void
lv_abp_publish(unsigned i)
{
''', '''static void lv_sah_open(AppleBasebandPCIInterface *itf);
static void lv_sah_close(void);

static void
lv_abp_publish(unsigned i)
{
''')
open(path, 'w', newline='\n').write(s)
print('ok')
