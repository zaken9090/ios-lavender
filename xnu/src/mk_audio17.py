"""lavender: audio - speaker volume 0 at start (boot-arg audio_vol, default 0) (patch 1135).

Run ia1 (xnu 1134): iOS plays its system sounds through Speaker -> ADSP -> MAX98937 and the user
hears them. The user asked for the sound to be at 0 when the phone starts. iOS's volume does not
reach our path yet (no volume control on the Speaker device - step A10), so the kernel scales
the samples it takes from iOS: audio_vol=0..100 percent, default 0 (silent); logged once.

usage: python mk_audio17.py XNU_TREE   (after mk_audio16.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()
old = '''extern "C" void
lv_snd_play(const int16_t *frames, uint32_t count)
{
	if (snd_lock == NULL || !snd_on) {
		return;
	}'''
assert s.count(old) == 1
s = s.replace(old, '''static int32_t snd_vol = -1;                    /* percent, from audio_vol (default 0: silent at start) */

extern "C" void
lv_snd_play(const int16_t *frames, uint32_t count)
{
	if (snd_lock == NULL || !snd_on) {
		return;
	}
	if (snd_vol < 0) {
		uint32_t v = 0;
		(void)PE_parse_boot_argn("audio_vol", &v, sizeof(v));
		snd_vol = v > 100 ? 100 : (int32_t)v;
		LOG("A9: speaker volume %d%% (audio_vol)", snd_vol);
	}''')
old2 = '''		uint32_t at = snd_tail++ % SND_FIFO;
		snd_fifo[2 * at] = frames[2 * i];
		snd_fifo[2 * at + 1] = frames[2 * i + 1];'''
assert s.count(old2) == 1
s = s.replace(old2, '''		uint32_t at = snd_tail++ % SND_FIFO;
		snd_fifo[2 * at] = (int16_t)(frames[2 * i] * snd_vol / 100);
		snd_fifo[2 * at + 1] = (int16_t)(frames[2 * i + 1] * snd_vol / 100);''')
open(path, 'w', newline='\n').write(s)
print('ok')
