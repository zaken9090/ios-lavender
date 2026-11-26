"""lavender: audio A4b - tone length from boot-arg audio_secs (patch 1128).

Run t2 (xnu 1127): the whole path runs - SMMU SID 1 through bank 0, all ASM/ADM/AFE commands 0,
151 WRITE_DONE in 3 s (150 expected), amplifier enable/disable acked, clean stop, ADSP alive.
The user was not sure the short sound heard came from the phone. Now audio_secs=N plays N
seconds (default 3, at most 30), and the amplifier's status is read once a second while it plays.

usage: python mk_audio10.py XNU_TREE   (after mk_audio9.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()
old = '''			unsigned t0 = ms();
			while (ms() - t0 < 3000) {
				if (!glink_poll()) {
					IODelay(200);
				}
				qrtr_poll();
			}
			amp_status("playing");'''
assert s.count(old) == 1
s = s.replace(old, '''			uint32_t secs = 3;
			(void)PE_parse_boot_argn("audio_secs", &secs, sizeof(secs));
			secs = secs == 0 ? 3 : (secs > 30 ? 30 : secs);
			unsigned t0 = ms(), last = t0;
			while (ms() - t0 < secs * 1000u) {
				if (!glink_poll()) {
					IODelay(200);
				}
				qrtr_poll();
				if (ms() - last >= 1000) {
					last = ms();
					amp_status("playing");
				}
			}''')
s = s.replace('''	LOG("A4b: %u WRITE_DONE in 3 s (%u with an error status), 150 expected", a4_done, a4_bad);''',
              '''	LOG("A4b: %u WRITE_DONE (%u with an error status), 50 a second expected", a4_done, a4_bad);''')
open(path, 'w', newline='\n').write(s)
print('ok')
