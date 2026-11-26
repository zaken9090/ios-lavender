"""lavender: audio A1 - SPMI codec read only with audio_spmi=1 (patch 1117).

Run e131 (xnu 1116): after "PM660L L6 1.8 V: ok/ok" the system stopped (19 more log lines, then
nothing): the observer read of SID 3 0xF000 (PM660L analog codec) hung the bus - that APID
belongs to another execution environment or needs the owner's channel (sweet_usb.c reads its
PMIC blocks through owned channels). The codec revision can wait for the ADSP steps; the I2C
amplifier census runs without it. sweet_spmi_peek stays, used only with audio_spmi=1.

usage: python mk_audio2.py XNU_TREE   (after mk_audio1.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderAudio.cpp'
s = open(path, newline='').read()
old = '''	for (unsigned base = 0xF000; base <= 0xF100; base += 0x100) {'''
assert s.count(old) == 1
s = s.replace(old, '''	uint32_t spmi = 0;
	PE_parse_boot_argn("audio_spmi", &spmi, sizeof(spmi));
	for (unsigned base = 0xF000; spmi != 0 && base <= 0xF100; base += 0x100) {''')
open(path, 'w', newline='\n').write(s)
print('ok')
