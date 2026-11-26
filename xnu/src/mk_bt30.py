"""lavender: Bluetooth - remove the tries that did not help, diagnostics behind bt_debug=1 (patch 1114).

Run e128 (xnu 1113): the receive fix is the re-arm of DMRX/stale after every batch of words
(1113, as Linux msm_handle_rx_dm), with IPR.RXSTALE_LAST (1112) and the partial word read by
count at the stale event (1108); stale events fire again, the 486-byte debug ACL comes whole.
Taken out again (docs/LEFTOVERS.md):
- 1090: the HCI_Reset retries after the firmware (again / IBS wake 0xFD / CTS flow control off) -
  the reset answers at once since the NVM fix (1092);
- 1089: the 1 s raw dump after the firmware;
- 1106: FORCE_STALE after 5 ms idle (never had an effect) and the register dumps of 1111 at a
  stuck packet; the stuck-packet drop itself stays (one log line) as a resync guard;
- 1109: 20 us busy polling after traffic - back to a 1 ms sleep (idle cost);
- 1110: the stale event log.
Kept: 1107 (IMR RXSTALE, as Linux), 1108, 1112, 1113. The per-packet trace and the vendor-opcode
log now only with boot-arg bt_debug=1.

usage: python mk_bt30.py XNU_TREE   (after mk_bt29.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


def cut(start, end, new):
    """replace from the line holding start up to (not including) the line holding end"""
    global s
    a = s.index(start)
    a = s.rindex('\n', 0, a) + 1
    b = s.index(end, a)
    b = s.rindex('\n', 0, b) + 1
    s = s[:a] + new + s[b:]


# 1089 dump + 1090 tries
cut('		char line[3 * 32 + 1];', '		LOG("local version: status', '''	if (bt_cmd_cc(0x0C03, NULL, 0, ret, &rlen)) {
		LOG("HCI_Reset: status %#x", ret[0]);
	}
	if (bt_cmd_cc(0x1001, NULL, 0, ret, &rlen) && rlen >= 9) {
''')
sub('''	LOG("firmware: %s", ok ? "loaded" : "FAILED");
	{
	if (bt_cmd_cc(0x0C03''', '''	LOG("firmware: %s", ok ? "loaded" : "FAILED");
	if (bt_cmd_cc(0x0C03''')

# 1110 stale log
sub('''		if (stale_log != 0 && stale_n < 60) {
			stale_n++;
			LOG("stale %u: snap %u taken %u left %d words %u last %08x sr %#x->%#x rxfs %#x->%#x", stale_n, snap, rx_taken,
			    left0, words, lastw, sr0, rd(uart, U_SR), fs0, rd(uart, U_RXFS));
		}
''', '')
sub('''		uint32_t sr0 = rd(uart, U_SR), fs0 = rd(uart, U_RXFS), words = 0, lastw = 0;
		int32_t left0 = left;
''', '')
sub('''			words++;
			lastw = w;
''', '')
sub('''static uint32_t stale_log, stale_n;             /* mk_bt26.py: set when the control is up */''', '')
sub('''	stale_log = 1;
''', '')

# 1106/1109/1111 pump
sub('''			/* idle_ms counts 20 us steps for the first 20 ms after traffic (idle_us), then 1 ms sleeps */
			if (idle_us < 20000) {
				IODelay(20);
				idle_us += 20;
				if (idle_us % 1000 != 0) {
					continue;
				}
			} else {
				IOSleep(1);
			}
			idle_ms++;
			if (idle_ms == 5) {
				wr(uart, U_CR, CR_FORCE_STALE);         /* the tail of this transfer out of the FIFO */
			}
''', '''			IOSleep(1);
			idle_ms++;
''')
sub('''				LOG("rx: uart sr %#x isr %#x misr %#x rxfs %#x snap %u taken %u", rd(uart, U_SR), rd(uart, U_ISR), rd(uart, 0x10),
				    rd(uart, U_RXFS), rd(uart, U_SNAP), rx_taken);
				wr(uart, U_CR, CR_FORCE_STALE);
				IOSleep(1);
				LOG("rx: after FORCE_STALE: sr %#x isr %#x misr %#x rxfs %#x snap %u", rd(uart, U_SR), rd(uart, U_ISR),
				    rd(uart, 0x10), rd(uart, U_RXFS), rd(uart, U_SNAP));
''', '')
sub('''		idle_ms = 0;
		idle_us = 0;''', '''		idle_ms = 0;''')
sub('''	uint32_t have = 0, idle_ms = 0, idle_us = 20000, overruns = 0;''', '''	uint32_t have = 0, idle_ms = 0, overruns = 0;''')

# traces behind bt_debug=1
sub('''static uint32_t trace_up, trace_down;''', '''static uint32_t trace_up, trace_down, bt_debug;    /* bt_debug=1: packet trace, vendor opcodes */''')
sub('''	if (!(n >= 7 && p[1] == 0x0e && p[4] == 0x4c && p[5] == 0xfc) && trace_up++ < 200) {''',
    '''	if (bt_debug && !(n >= 7 && p[1] == 0x0e && p[4] == 0x4c && p[5] == 0xfc) && trace_up++ < 200) {''')
sub('''	if (!(n >= 3 && p[0] == 0x01 && p[1] == 0x4c && p[2] == 0xfc) && trace_down++ < 200) {''',
    '''	if (bt_debug && !(n >= 3 && p[0] == 0x01 && p[1] == 0x4c && p[2] == 0xfc) && trace_down++ < 200) {''')
sub('''			if (vendor_logged++ < 64) {''', '''			if (bt_debug && vendor_logged++ < 64) {''')
sub('''	bt_ready = true;
''', '''	PE_parse_boot_argn("bt_debug", &bt_debug, sizeof(bt_debug));
	bt_ready = true;
''')
open(path, 'w', newline='\n').write(s)
print('ok')
