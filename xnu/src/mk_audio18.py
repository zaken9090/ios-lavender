"""lavender: audio A10 - iOS's volume reaches the speaker: a volume control on "Speaker" (patch 1136).

docs/IOAUDIO2-ABI.md: a level control dict {control ID, class 'vlme', base class 'levl', scope
'outp', element 0, value, read only, name, minimum value, maximum value, range map [{start int
value, integer steps, start db value, db per step}] (dB Fixed64)}; the HAL sets it with selector 2
(scalars: control ID, value; out: the value applied).

Now "Speaker" publishes control 1: integer 0..100, -64 dB .. 0 dB in 0.64 dB steps. The value the
HAL sets is applied by the kernel to the samples (0 = mute; else 0.64 dB per step: Q15 factor
30440/32768 per step down from 0 dB). Until iOS sets it, the kernel keeps audio_vol (default 0:
silent at start, user request). Every change is logged.

usage: python mk_audio18.py XNU_TREE   (after mk_audio17.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


io = f'{tree}/iokit/Kernel/arm/LavenderIOAudio2.cpp'
patch(io, '''extern "C" void lv_ioaudio2_publish(void);''', '''extern "C" void lv_ioaudio2_publish(void);
extern "C" void lv_snd_volume(uint32_t value);                         /* TopazAudio.cpp: 0..100 */''')
patch(io, '''	OSArray *c = OSArray::withCapacity(1);
	if (c != NULL) {
		e->setProperty("controls", c);
		c->release();
	}''', '''	OSArray *c = OSArray::withCapacity(1);
	if (c != NULL) {
		if (!isInput) {
			/* control 1: output volume, 0..100 = -64 dB .. 0 dB (mk_audio18.py) */
			OSDictionary *v = OSDictionary::withCapacity(16), *m = OSDictionary::withCapacity(4);
			OSArray *map = OSArray::withCapacity(1);
			if (v != NULL && m != NULL && map != NULL) {
				a2num(v, "control ID", 1);
				a2num(v, "class", 0x766c6d65);              /* 'vlme' */
				a2num(v, "base class", 0x6c65766c);         /* 'levl' */
				a2num(v, "scope", 0x6f757470);              /* 'outp' */
				a2num(v, "element", 0);
				a2num(v, "value", volume);
				v->setObject("read only", kOSBooleanFalse);
				OSString *nm = OSString::withCString("Speaker Volume");
				if (nm != NULL) {
					v->setObject("name", nm);
					nm->release();
				}
				a2num(v, "minimum value", 0);
				a2num(v, "maximum value", 100);
				a2num(m, "start int value", 0);
				a2num(m, "integer steps", 100);
				a2num(m, "start db value", (uint64_t)(-(int64_t)64 << 32), 64);
				a2num(m, "db per step", (uint64_t)((int64_t)64 << 32) / 100, 64);
				map->setObject(m);
				v->setObject("range map", map);
				c->setObject(v);
			}
			OSSafeReleaseNULL(v);
			OSSafeReleaseNULL(m);
			OSSafeReleaseNULL(map);
		}
		e->setProperty("controls", c);
		c->release();
	}''')
patch(io, '''	int32_t hog;
''', '''	int32_t hog;
	uint32_t volume;
''')
patch(io, '''	case 2:
		return kIOReturnBadArgument;            /* no controls */''', '''	case 2:                                         /* SetControlValue: control ID, value */
		if (a->scalarInputCount >= 2 && a->scalarInput[0] == 1 && !dev->isInput) {
			uint32_t v = a->scalarInput[1] > 100 ? 100 : (uint32_t)a->scalarInput[1];
			dev->volume = v;
			lv_snd_volume(v);
			LOG("%s: volume control set to %u", dev->uid, v);
			if (a->scalarOutputCount >= 1) {
				a->scalarOutput[0] = v;
				a->scalarOutputCount = 1;
			}
			return kIOReturnSuccess;
		}
		return kIOReturnBadArgument;''')

ta = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
patch(ta, '''static int32_t snd_vol = -1;                    /* percent, from audio_vol (default 0: silent at start) */''',
      '''static int32_t snd_vol = -1;                    /* percent, from audio_vol (default 0: silent at start) */
static int32_t snd_q15 = -1;                    /* the iOS volume control as a Q15 factor (mk_audio18.py); -1: not set yet */

extern "C" void
lv_snd_volume(uint32_t value)
{
	int32_t g = 0;
	if (value > 0) {
		g = 32768;
		for (uint32_t i = value; i < 100; i++) {
			g = g * 30440 / 32768;          /* -0.64 dB a step */
		}
	}
	snd_q15 = g;
}''')
patch(ta, '''		snd_fifo[2 * at] = (int16_t)(frames[2 * i] * snd_vol / 100);
		snd_fifo[2 * at + 1] = (int16_t)(frames[2 * i + 1] * snd_vol / 100);''', '''		if (snd_q15 >= 0) {
			snd_fifo[2 * at] = (int16_t)((frames[2 * i] * snd_q15) >> 15);
			snd_fifo[2 * at + 1] = (int16_t)((frames[2 * i + 1] * snd_q15) >> 15);
		} else {
			snd_fifo[2 * at] = (int16_t)(frames[2 * i] * snd_vol / 100);
			snd_fifo[2 * at + 1] = (int16_t)(frames[2 * i + 1] * snd_vol / 100);
		}''')
print('ok')
