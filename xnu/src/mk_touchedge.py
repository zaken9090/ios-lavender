"""lavender: touch reads a report only after the event line's rising edge (patch 1144 SMT: 1145).

SMT lines showed touch_thread at ~11% of a core in idle and ~26% while touched. The NT36672A's event
line rests LOW and pulses high for a report (stock/mainline DT: GPIO 67 IRQ_TYPE_EDGE_RISING), so
"line low = report waiting" was true all the time: 65 bytes over bit-banged I2C every 12 ms, forever.

Now TLMM latches the rising edge in GPIO 67's INTR_STATUS (INTR_CFG: raw status on, rising edge,
target KPSS; INTR_ENABLE stays 0, so nothing goes to the GIC). The thread looks at that bit every
12 ms (8 ms with a finger down, reading every time as before) and reads only when it is set. As a
safety net it also reads every 250 ms. Values: pinctrl-sdm660 (intr_detection_bit 2 width 2,
polarity bit 1, raw status bit 4, target bit 5, KPSS 3).

boot-arg sweettouch_edge=0: old way (default 1).
usage: python mk_touchedge.py XNU_TREE
"""
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_touch.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''	bool any_down = false;
	for (;;) {
		/* A report waits while the line is low; after the last finger lifts, read once more. */
		if (!line_high(lt.irq) || any_down) {
			if (i2c_read(NVT_ADDR, 0x00, r, NVT_REPORT_LEN) == 0) {''', '''	bool any_down = false;
	/* lavender: the report comes with a rising edge, latched by TLMM (xnu/src/mk_touchedge.py) */
	int edge = 1;
	unsigned quiet = 0, edges = 0;
	PE_parse_boot_argn("sweettouch_edge", &edge, sizeof(edge));
	if (edge) {
		pin_wr(lt.irq, 8, (3u << 5) | (1u << 4) | (1u << 2) | (1u << 1));     /* KPSS, raw status, rising edge */
		pin_wr(lt.irq, 0xc, 0);
		printf("SWEET TOUCH: reports on the event line's rising edge (intr cfg 0x%x)\\n", pin_rd(lt.irq, 8));
	}
	for (;;) {
		bool due;
		if (edge) {
			bool latched = (pin_rd(lt.irq, 0xc) & 1) != 0;
			if (latched) {
				pin_wr(lt.irq, 0xc, 0);         /* (before the read: an edge during it is kept) */
				if (++edges == 1) {
					printf("SWEET TOUCH: first edge latched\\n");
				}
			}
			due = latched || any_down || ++quiet >= 20;
		} else {
			/* A report waits while the line is low; after the last finger lifts, read once more. */
			due = !line_high(lt.irq) || any_down;
		}
		if (due) {
			quiet = 0;
			if (i2c_read(NVT_ADDR, 0x00, r, NVT_REPORT_LEN) == 0) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
