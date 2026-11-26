"""lavender: the WLFW handshake can be stopped after any step (patch 1053).

Run e52: with the Wi-Fi chip's supplies and clock voted on (all acked) the modem still dies of
"Task starvation: diag" 13.3 s after its start, and still does not with modem_wlfw=0. To find the
message after which the WLAN firmware hangs, modem_wlfw=N stops the handshake:
  0 nothing sent      1 after ind_register     2 after host_cap     3 after msa_info + assign
  4 after msa_ready   5 and more: everything (default)
modem_wlhost=0 leaves host_cap out (Android's icnss does not send it; the firmware rejects ours).

usage: python mk_wlfwsteps.py XNU_TREE   (after mk_wlanpower.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	uint32_t wl = 1;
	(void)PE_parse_boot_argn("modem_wlfw", &wl, sizeof(wl));
	if (wl == 0) {''', '''	uint32_t wl = 9;
	(void)PE_parse_boot_argn("modem_wlfw", &wl, sizeof(wl));
	w_stop = wl;
	(void)PE_parse_boot_argn("modem_wlhost", &w_hostcap, sizeof(w_hostcap));
	if (wl == 0) {''')
sub('''static unsigned w_arrivals, w_cap_tries, w_cap_retry_ms;
''', '''static unsigned w_arrivals, w_cap_tries, w_cap_retry_ms;
static uint32_t w_stop = 9, w_hostcap = 1;      /* modem_wlfw=, modem_wlhost= */

static bool
w_stop_at(uint32_t step, const char *what)
{
	if (w_stop <= step) {
		LOG("wlfw: stopped after %s (modem_wlfw=%u)", what, w_stop);
		return true;
	}
	return false;
}
''')
sub('''		LOG("t=%u ms: wlfw: ind_register %s err %u, fw_status %llx", g_ms, ok ? "ok" : "FAILED", err, st);
		if (wm_new(&m, WLFW_HOST_CAP)) {''', '''		LOG("t=%u ms: wlfw: ind_register %s err %u, fw_status %llx", g_ms, ok ? "ok" : "FAILED", err, st);
		if (w_stop_at(1, "ind_register")) {
			break;
		}
		if (!w_hostcap) {
			if (wm_new(&m, WLFW_MSA_INFO)) {
				uint64_t a = WLFW_MSA_BASE;
				wm_tlv(&m, 0x01, &a, 8);
				wm_u32(&m, 0x02, WLFW_MSA_SIZE);
				wm_send(&m);
				w_step = "msa_info sent (no host_cap)";
			}
			break;
		}
		if (wm_new(&m, WLFW_HOST_CAP)) {''')
sub('''		LOG("wlfw: host_cap %s err %u", ok ? "ok" : "rejected (not fatal)", err);
		if (wm_new(&m, WLFW_MSA_INFO)) {''', '''		LOG("wlfw: host_cap %s err %u", ok ? "ok" : "rejected (not fatal)", err);
		if (w_stop_at(2, "host_cap")) {
			break;
		}
		if (wm_new(&m, WLFW_MSA_INFO)) {''')
sub('''			w_on_msa_info(d, len);
			w_simple(WLFW_MSA_READY, "msa_ready sent");
''', '''			w_on_msa_info(d, len);
			if (w_stop_at(3, "msa_info and the assign")) {
				break;
			}
			w_simple(WLFW_MSA_READY, "msa_ready sent");
''')
sub('''		LOG("wlfw: msa_ready %s err %u", ok ? "ok" : "FAILED", err);
		w_simple(WLFW_CAP, "cap sent");
''', '''		LOG("wlfw: msa_ready %s err %u", ok ? "ok" : "FAILED", err);
		if (w_stop_at(4, "msa_ready")) {
			break;
		}
		w_simple(WLFW_CAP, "cap sent");
''')
open(path, 'w', newline='\n').write(s)
print('ok')
