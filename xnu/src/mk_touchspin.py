"""lavender: touch's bit-banged I2C waits by spinning, not by sleeping (patch 1153).

The touch trace (1152, sweettouch_trace=1, run tt1) showed one 65-byte report read taking ~53 ms (median,
max 76 ms): with a finger down the chip was read ~17 times a second, so iOS moved Settings' rows ~17 times
a second while the display drew ~50 frames - the judder the user saw with a real finger (injected drags go
around the chip every 8 ms). The bit-banged bus waits half an SCL period with delay(2), and xnu's
delay_for_interval() blocks the thread for intervals like that (SMT stacks: delay_for_interval ->
thread_block): each 2 us wait came back after tens of microseconds. Now the waits spin on the timebase
(mach_absolute_time), as short bus timing needs: ~2 ms a report at ~150 kHz.

usage: python mk_touchspin.py XNU_TREE
"""
import re
import sys

tree = sys.argv[1]
path = f'{tree}/bsd/dev/sweet_touch.c'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''static inline uint32_t
pin_rd(vm_offset_t pin, uint32_t off)''', '''/* lavender: bus waits spin on the timebase; delay() of a few us blocked for tens (xnu/src/mk_touchspin.py) */
static inline void
lv_spin_us(uint32_t us)
{
	static uint64_t per_us;
	if (per_us == 0) {
		nanoseconds_to_absolutetime(1000, &per_us);
		if (per_us == 0) {
			per_us = 1;
		}
	}
	uint64_t end = mach_absolute_time() + per_us * us;
	while (mach_absolute_time() < end) {
	}
}

static inline uint32_t
pin_rd(vm_offset_t pin, uint32_t off)''')
n = len(re.findall(r'\bdelay\((HALF_US|1)\);', s))
assert n == 11, n
s = re.sub(r'\bdelay\((HALF_US|1)\);', r'lv_spin_us(\1);', s)
open(path, 'w', newline='\n').write(s)
print('ok', n)
