"""lavender: Bluetooth B2 - look at the NVM file's layout (patch 1091).

Run e99: no "nvm tag" line - the tag walk never met tag 17 (HCI: in-band sleep, baud) or 27, so
the NVM went down unedited; the chip may then run at the NVM's own baud rate, which fits its
silence after the firmware. Every try (again, IBS wake, no CTS) got nothing.

Now the NVM's first 32 bytes are logged, and the walk logs each tag (id, length) up to 40 of them.

usage: python mk_bt7.py XNU_TREE   (after mk_bt6.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''		uint32_t len = (data[1] | (data[2] << 8) | ((uint32_t)data[3] << 16));
''', '''		uint32_t len = (data[1] | (data[2] << 8) | ((uint32_t)data[3] << 16));
		for (uint32_t o = 0; o < 32 && o + 8 <= size; o += 8) {
			LOG("nvm +%u: %02x %02x %02x %02x %02x %02x %02x %02x", o, data[o], data[o + 1], data[o + 2], data[o + 3], data[o + 4],
			    data[o + 5], data[o + 6], data[o + 7]);
		}
		LOG("nvm: type %u length %u (file %u)", data[0], len, size);
		unsigned ntag = 0;
''')
sub('''			uint16_t id = (uint16_t)(t[0] | (t[1] << 8)), tl = (uint16_t)(t[2] | (t[3] << 8));
''', '''			uint16_t id = (uint16_t)(t[0] | (t[1] << 8)), tl = (uint16_t)(t[2] | (t[3] << 8));
			if (ntag++ < 40) {
				LOG("nvm tag at %u: id %u len %u", idx, id, tl);
			}
''')
open(path, 'w', newline='\n').write(s)
print('ok')
