"""lavender: the modem watch loop sleeps longer while glink is quiet (patch 1146).

SMT lines (1144) showed topaz_modem_thread at ~1.4% of a core in idle: it polls SMP2P and the glink
FIFOs every millisecond (1000 wakeups a second, which also keeps cores out of deep idle). Now, after the
first 30 s and 500 ms without a glink message either way, it sleeps modem_idle_ms (default 8) between
passes; any message in or out brings it back to 1 ms at once. The loop's ms counter advances by the
sleep, so the radio timers (all ">=" on g_ms) keep their meaning.

boot-arg modem_idle_ms=0: every millisecond as before.
usage: python mk_modemidle.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	ipa_out = smp2p_add_out(out, "ipa", 0);
	bool glink = false;
	for (unsigned ms = 0; seconds == 0 || ms < seconds * 1000; ms++) {''', '''	ipa_out = smp2p_add_out(out, "ipa", 0);
	bool glink = false;
	/* lavender: longer sleeps while glink is quiet (xnu/src/mk_modemidle.py) */
	uint32_t idle_ms = 8, last_act = ~0u, quiet = 0, step = 1;
	(void)PE_parse_boot_argn("modem_idle_ms", &idle_ms, sizeof(idle_ms));
	if (idle_ms > 50) {
		idle_ms = 50;
	}
	for (unsigned ms = 0; seconds == 0 || ms < seconds * 1000; ms += step) {''')
sub('''			ipa_last = v;
		}
		IOSleep(1);
	}''', '''			ipa_last = v;
		}
		uint32_t act = g_rx_msgs + g_tx_msgs + (g_txq_tail - g_txq_head);
		if (act != last_act) {
			last_act = act;
			quiet = 0;
		} else {
			quiet += step;
		}
		step = (idle_ms > 1 && glink && ms >= 30000 && quiet >= 500) ? idle_ms : 1;
		IOSleep(step);
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
