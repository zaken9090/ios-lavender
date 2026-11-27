"""lavender: audio A9 - iOS plays through our speaker path: IOAudio2Device "Speaker" + "Hawking" (patch 1134).

A4 works (xnu 1133): kernel tone -> ASM -> ADM -> AFE PRIMARY_MI2S_RX -> MAX98937 -> speaker.
docs/IOAUDIO2-ABI.md (static reading of the D22 CoreAudio / VirtualAudio, cross-checked with the
public UniXNU-droidvm DroidVMAudio.cpp, BSD-2-Clause-Patent, whose structure this follows): the HAL
(mediaserverd) matches IOServiceMatching("IOAudio2Device"), reads the description from the
registry (keys with spaces), opens IOAudio2DeviceUserClient type 0, maps memory type 0 (engine
status: +0 sample time, +8 host time, +0x10 seed, +0x20 HAL write end) and 0x10000000 + stream ID
(the ring), calls selectors 0/1/10/11 start/stop, 2-6 and 12. VirtualAudio needs "Speaker" and a
silent companion input "Hawking" for the speaker route.

Our kernel has no IOAudio2Family, so the classes carry those names themselves.
New iokit/Kernel/arm/LavenderIOAudio2.cpp:
- "Speaker": output stream 1, 2 ch s16 48 kHz, terminal 'spkr', transport 'bltn', clock domain 1;
  "Hawking": input stream 1, 1 ch, kept silent; both: ring 8192 frames, period 240 frames (5 ms);
- each device's engine thread moves one period per 5 ms and moves the zero time stamp at each
  ring wrap; the speaker's period goes to lv_snd_play() (TopazAudio), then is zeroed;
- once a second while running: the speaker's peak sample is logged ("ioa2: Speaker ..."),
  user-client selectors and maps are logged as they come.
TopazAudio.cpp: a continuous stream for iOS (lv_snd_running/lv_snd_play): a 4800-frame FIFO;
start = the A4b sequence (SMMU SID 1 once, amplifier set-up once, pins, AFE clock/I2S/start, ASM
map/open, ADM open/map, format, 4 silent buffers, RUN, amplifier on); each WRITE_DONE refills its
buffer from the FIFO (silence on underrun), cleans it to DRAM and resubmits; stop = the clean
stop. Driven from the TopazAudio thread (APR lives there).
topaz_fw.c: with audio_ios=1 the root-file installer puts VirtualAudio.plugin back from
/Library/Audio/Plug-Ins/HAL.disabled to .../HAL (it was moved away when there was no audio device;
an original iOS component, rule "keep original functions").
Boot-arg audio_ios=1 (with audio=1 adsp=1) publishes the devices; default off.

usage: python mk_audio16.py XNU_TREE   (after mk_audio15.py)
"""
import sys

tree = sys.argv[1]


def patch(path, old, new):
    s = open(path, newline='').read()
    assert s.count(old) == 1, (path, old[:70], s.count(old))
    s = s.replace(old, new)
    open(path, 'w', newline='\n').write(s)


open(f'{tree}/iokit/Kernel/arm/LavenderIOAudio2.cpp', 'w', newline='\n').write(r'''/*
 * lavender: the built-in audio devices iOS's HAL expects (xnu/src/mk_audio16.py, docs/IOAUDIO2-ABI.md).
 * Structure after the public UniXNU-droidvm DroidVMAudio.cpp (BSD-2-Clause-Patent). This kernel has no
 * IOAudio2Family: the classes carry the family's names, which is what matching and IOObjectConformsTo test.
 */
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSArray.h>
#include <libkern/c++/OSDictionary.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>

#define LOG(fmt, ...)       IOLog("ioa2: " fmt "\n", ##__VA_ARGS__)

extern "C" void lv_snd_play(const int16_t *frames, uint32_t count);     /* TopazAudio.cpp */
extern "C" void lv_snd_running(bool on);
extern "C" void lv_ioaudio2_publish(void);

enum : uint32_t {
	A2Rate = 48000, A2Ring = 8192, A2Period = 240, A2Stream = 1,
	A2Safety = 2 * A2Period, A2Latency = A2Period, A2OutLead = 4800,
	A2Builtin = 0x626c746e, A2LPCM = 0x6c70636d, A2FlagsS16 = 0x4 | 0x8,
	A2Spkr = 0x73706b72, A2Micr = 0x6d696372, A2StreamMem = 0x10000000,
};
struct A2Status { volatile uint64_t sampleTime, hostTime, seed, readEnd, writeEnd; };

static int64_t
a2fixed(uint32_t hz)
{
	return (int64_t)hz << 32;
}

static uint64_t
a2abs(uint64_t frames)
{
	uint64_t t;
	nanoseconds_to_absolutetime(frames * 1000000000ULL / A2Rate, &t);
	return t;
}

static void
a2num(OSDictionary *d, const char *k, uint64_t v, unsigned bits = 32)
{
	OSNumber *n = OSNumber::withNumber(v, bits);
	if (n != NULL) {
		d->setObject(k, n);
		n->release();
	}
}

static void
a2num(IORegistryEntry *e, const char *k, uint64_t v, unsigned bits = 32)
{
	OSNumber *n = OSNumber::withNumber(v, bits);
	if (n != NULL) {
		e->setProperty(k, n);
		n->release();
	}
}

static OSDictionary *
a2format(uint32_t ch)
{
	OSDictionary *f = OSDictionary::withCapacity(8);
	if (f != NULL) {
		a2num(f, "sample rate", (uint64_t)a2fixed(A2Rate), 64);
		a2num(f, "format ID", A2LPCM);
		a2num(f, "format flags", A2FlagsS16);
		a2num(f, "bytes per packet", 2 * ch);
		a2num(f, "frames per packet", 1);
		a2num(f, "bytes per frame", 2 * ch);
		a2num(f, "channels per frame", ch);
		a2num(f, "bits per channel", 16);
	}
	return f;
}

static OSArray *
a2streams(uint32_t ch, uint32_t terminal)
{
	OSDictionary *st = OSDictionary::withCapacity(8), *cur = a2format(ch), *rng = a2format(ch);
	OSArray *av = OSArray::withCapacity(1), *list = OSArray::withCapacity(1);
	if (st != NULL && cur != NULL && rng != NULL && av != NULL && list != NULL) {
		a2num(rng, "min sample rate", (uint64_t)a2fixed(A2Rate), 64);
		a2num(rng, "max sample rate", (uint64_t)a2fixed(A2Rate), 64);
		av->setObject(rng);
		a2num(st, "stream ID", A2Stream);
		a2num(st, "starting channel", 1);
		a2num(st, "latency", 0);
		a2num(st, "terminal type", terminal);
		st->setObject("current format", cur);
		st->setObject("available formats", av);
		list->setObject(st);
	}
	OSSafeReleaseNULL(st);
	OSSafeReleaseNULL(cur);
	OSSafeReleaseNULL(rng);
	OSSafeReleaseNULL(av);
	return list;
}

class IOAudio2Device : public IOService
{
	OSDeclareDefaultStructors(IOAudio2Device);
public:
	bool isInput;
	const char *uid;
	IOBufferMemoryDescriptor *statusMem, *ring;
	IOLock *lock;
	bool running, stopping;
	uint64_t startTime, seed;
	int32_t hog;

	bool initRole(bool input, const char *u);
	uint32_t channels() const { return isInput ? 1 : 2; }
	A2Status *status() { return (A2Status *)statusMem->getBytesNoCopy(); }
	void publish(IORegistryEntry *e);
	IOReturn apply(OSObject *props, IORegistryEntry *client);
	IOReturn setProperties(OSObject *props) APPLE_KEXT_OVERRIDE { return apply(props, NULL); }
	IOReturn startIO();
	IOReturn stopIO();
	static void engineMain(void *arg, wait_result_t w);
	void run();
};
OSDefineMetaClassAndStructors(IOAudio2Device, IOService);

class IOAudio2DeviceUserClient : public IOUserClient
{
	OSDeclareDefaultStructors(IOAudio2DeviceUserClient);
public:
	IOAudio2Device *dev;
	bool started;
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	IOReturn clientClose(void) APPLE_KEXT_OVERRIDE;
	IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args, IOExternalMethodDispatch *dispatch,
	    OSObject *target, void *reference) APPLE_KEXT_OVERRIDE;
	IOReturn clientMemoryForType(UInt32 type, IOOptionBits *options, IOMemoryDescriptor **memory) APPLE_KEXT_OVERRIDE;
	IOReturn registerNotificationPort(mach_port_t port, UInt32 type, io_user_reference_t refCon) APPLE_KEXT_OVERRIDE;
	IOReturn setProperties(OSObject *props) APPLE_KEXT_OVERRIDE { return dev != NULL ? dev->apply(props, this) : kIOReturnNotReady; }
};
OSDefineMetaClassAndStructors(IOAudio2DeviceUserClient, IOUserClient);

bool
IOAudio2Device::initRole(bool input, const char *u)
{
	if (!IOService::init(NULL)) {
		return false;
	}
	isInput = input;
	uid = u;
	hog = -1;
	lock = IOLockAlloc();
	IOOptionBits o = kIODirectionInOut | kIOMemoryKernelUserShared;
	statusMem = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task, o, page_size, page_size);
	ring = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task, o, A2Ring * 2 * channels(), page_size);
	if (lock == NULL || statusMem == NULL || ring == NULL) {
		return false;
	}
	bzero(statusMem->getBytesNoCopy(), page_size);
	bzero(ring->getBytesNoCopy(), ring->getLength());
	return true;
}

void
IOAudio2Device::publish(IORegistryEntry *e)
{
	e->setProperty("device UID", uid);
	e->setProperty("device name", uid);
	e->setProperty("device manufacturer", "Apple Inc.");
	e->setProperty("model UID", uid);
	a2num(e, "transport type", A2Builtin);
	a2num(e, "clock domain", 1);
	a2num(e, "output latency", A2Latency + A2OutLead);
	a2num(e, "input latency", A2Latency);
	a2num(e, "output safety offset", A2Safety);
	a2num(e, "input safety offset", A2Safety);
	a2num(e, "io buffer frame size", A2Ring);
	a2num(e, "sample rate", (uint64_t)a2fixed(A2Rate), 64);
	a2num(e, "exclusive access owner", (uint32_t)hog);
	e->setProperty("is running", running ? kOSBooleanTrue : kOSBooleanFalse);
	e->setProperty("is private", kOSBooleanFalse);
	e->setProperty("supports prewarming", kOSBooleanFalse);
	e->setProperty("supports client description", kOSBooleanFalse);
	e->setProperty("wants output trap", kOSBooleanFalse);
	e->setProperty("wants input trap", kOSBooleanFalse);
	OSArray *a = a2streams(channels(), isInput ? A2Micr : A2Spkr);
	if (a != NULL) {
		e->setProperty(isInput ? "input streams" : "output streams", a);
		a->release();
	}
	OSArray *c = OSArray::withCapacity(1);
	if (c != NULL) {
		e->setProperty("controls", c);
		c->release();
	}
}

/* the HAL's hog-mode owner ("exclusive access owner"); other keys are accepted */
IOReturn
IOAudio2Device::apply(OSObject *props, IORegistryEntry *client)
{
	OSDictionary *d = OSDynamicCast(OSDictionary, props);
	if (d == NULL) {
		return kIOReturnBadArgument;
	}
	OSNumber *o = OSDynamicCast(OSNumber, d->getObject("exclusive access owner"));
	if (o != NULL) {
		hog = (int32_t)o->unsigned32BitValue();
		a2num(this, "exclusive access owner", (uint32_t)hog);
		if (client != NULL) {
			a2num(client, "exclusive access owner", (uint32_t)hog);
		}
		LOG("%s: exclusive access owner %d", uid, hog);
	}
	return kIOReturnSuccess;
}

IOReturn
IOAudio2Device::startIO()
{
	IOLockLock(lock);
	if (!running) {
		while (stopping) {
			IOLockSleep(lock, &stopping, THREAD_UNINT);
		}
		bzero(ring->getBytesNoCopy(), ring->getLength());
		if (!isInput) {
			lv_snd_running(true);
		}
		startTime = mach_absolute_time();
		A2Status *s = status();
		s->sampleTime = 0;
		s->hostTime = startTime;
		s->seed = ++seed;
		s->writeEnd = 0;
		__asm__ volatile ("dmb ish" ::: "memory");
		running = true;
		setProperty("is running", kOSBooleanTrue);
		thread_t t;
		if (kernel_thread_start(engineMain, this, &t) == KERN_SUCCESS) {
			thread_deallocate(t);
		} else {
			running = false;
		}
		LOG("%s: start IO %s", uid, running ? "ok" : "FAILED");
	}
	IOLockUnlock(lock);
	return running ? kIOReturnSuccess : kIOReturnNoResources;
}

IOReturn
IOAudio2Device::stopIO()
{
	IOLockLock(lock);
	if (running) {
		running = false;
		stopping = true;
		while (stopping) {
			IOLockSleep(lock, &stopping, THREAD_UNINT);
		}
		setProperty("is running", kOSBooleanFalse);
		if (!isInput) {
			lv_snd_running(false);
		}
		LOG("%s: stop IO", uid);
	}
	IOLockUnlock(lock);
	return kIOReturnSuccess;
}

void
IOAudio2Device::engineMain(void *arg, wait_result_t w)
{
	(void)w;
	((IOAudio2Device *)arg)->run();
}

void
IOAudio2Device::run()
{
	retain();
	int16_t *buf = (int16_t *)ring->getBytesNoCopy();
	const uint32_t ch = channels();
	uint64_t done = 0, late = 0, lastlog = mach_absolute_time();
	int32_t peak = 0;
	for (;;) {
		IOLockLock(lock);
		bool live = running;
		IOLockUnlock(lock);
		if (!live) {
			break;
		}
		uint64_t deadline = startTime + a2abs(done + A2Period);
		if (mach_absolute_time() > deadline + a2abs(A2Period)) {
			late++;
		} else {
			clock_delay_until(deadline);
		}
		uint32_t head = (uint32_t)(done % A2Ring);
		uint32_t first = A2Period < A2Ring - head ? A2Period : A2Ring - head, rest = A2Period - first;
		int16_t *at = buf + head * ch;
		if (!isInput) {
			int16_t period[A2Period * 2];
			memcpy(period, at, first * 2 * ch);
			if (rest != 0) {
				memcpy(period + first * ch, buf, rest * 2 * ch);
			}
			for (uint32_t i = 0; i < A2Period * ch; i++) {
				int32_t v = period[i] < 0 ? -period[i] : period[i];
				peak = v > peak ? v : peak;
			}
			lv_snd_play(period, A2Period);
			bzero(at, first * 2 * ch);
			if (rest != 0) {
				bzero(buf, rest * 2 * ch);
			}
		}
		done += A2Period;
		if (done % A2Ring < A2Period) {
			uint64_t wrap = done - done % A2Ring;
			A2Status *s = status();
			s->hostTime = startTime + a2abs(wrap);
			__asm__ volatile ("dmb ish" ::: "memory");
			s->sampleTime = wrap;
			__asm__ volatile ("dmb ish" ::: "memory");
		}
		if (!isInput && mach_absolute_time() - lastlog > a2abs(A2Rate)) {
			lastlog = mach_absolute_time();
			LOG("%s: peak %d in the last second, %llu frames, %llu late periods, HAL write end %llu", uid, peak, done, late,
			    status()->writeEnd);
			peak = 0;
		}
	}
	IOLockLock(lock);
	stopping = false;
	IOLockWakeup(lock, &stopping, false);
	IOLockUnlock(lock);
	release();
}

bool
IOAudio2DeviceUserClient::start(IOService *provider)
{
	dev = OSDynamicCast(IOAudio2Device, provider);
	if (dev == NULL || !IOUserClient::start(provider)) {
		return false;
	}
	dev->publish(this);
	LOG("%s: user client opened", dev->uid);
	return true;
}

IOReturn
IOAudio2DeviceUserClient::clientClose(void)
{
	if (started && dev != NULL) {
		dev->stopIO();
	}
	started = false;
	if (!isInactive()) {
		terminate();
	}
	return kIOReturnSuccess;
}

IOReturn
IOAudio2DeviceUserClient::externalMethod(uint32_t sel, IOExternalMethodArguments *a, IOExternalMethodDispatch *, OSObject *, void *)
{
	static uint32_t logged;
	if (logged++ < 64) {
		LOG("%s: selector %u (scalars %u, struct %u)", dev->uid, sel, a->scalarInputCount, a->structureInputSize);
	}
	switch (sel) {
	case 0:
	case 10: {
		IOReturn r = dev->startIO();
		if (r == kIOReturnSuccess) {
			started = true;
		}
		if (sel == 10 && a->scalarOutputCount >= 1) {
			a->scalarOutput[0] = 0;
			a->scalarOutputCount = 1;
		}
		return r;
	}
	case 1:
	case 11:
		started = false;
		return dev->stopIO();
	case 2:
		return kIOReturnBadArgument;            /* no controls */
	case 3:
		return kIOReturnSuccess;
	case 4: {
		int64_t r = 0;
		if (a->structureInputSize == sizeof(r)) {
			memcpy(&r, a->structureInput, sizeof(r));
		}
		return r == a2fixed(A2Rate) ? kIOReturnSuccess : kIOReturnUnsupported;
	}
	case 5:
	case 6:
	case 12:
		return kIOReturnSuccess;
	default:
		return kIOReturnUnsupported;
	}
}

IOReturn
IOAudio2DeviceUserClient::clientMemoryForType(UInt32 type, IOOptionBits *options, IOMemoryDescriptor **memory)
{
	IOMemoryDescriptor *m = dev == NULL ? NULL : type == 0 ? (IOMemoryDescriptor *)dev->statusMem :
	    type == A2StreamMem + A2Stream ? (IOMemoryDescriptor *)dev->ring : NULL;
	LOG("%s: map type %#x -> %s", dev != NULL ? dev->uid : "?", type, m != NULL ? "ok" : "none");
	if (m == NULL) {
		return kIOReturnBadArgument;
	}
	m->retain();
	*memory = m;
	*options = 0;
	return kIOReturnSuccess;
}

IOReturn
IOAudio2DeviceUserClient::registerNotificationPort(mach_port_t, UInt32, io_user_reference_t)
{
	return kIOReturnSuccess;
}

static bool
a2publish(IOService *res, bool input, const char *uid, const char *nubName)
{
	IOService *nub = OSTypeAlloc(IOService);
	if (nub == NULL || !nub->init()) {
		OSSafeReleaseNULL(nub);
		return false;
	}
	nub->setName(nubName);
	nub->setProperty("built-in", kOSBooleanTrue);
	if (!nub->attach(res)) {
		nub->release();
		return false;
	}
	nub->registerService();
	IOAudio2Device *d = OSTypeAlloc(IOAudio2Device);
	if (d == NULL || !d->initRole(input, uid) || !d->attach(nub)) {
		OSSafeReleaseNULL(d);
		return false;
	}
	d->publish(d);
	d->setProperty("IOUserClientClass", "IOAudio2DeviceUserClient");
	if (!d->start(nub)) {
		d->detach(nub);
		d->release();
		return false;
	}
	d->registerService();
	return true;
}

extern "C" void
lv_ioaudio2_publish(void)
{
	IOService *res = IOService::getResourceService();
	bool s = res != NULL && a2publish(res, false, "Speaker", "lavender-audio-out");
	bool h = res != NULL && a2publish(res, true, "Hawking", "lavender-audio-hawking");
	LOG("published Speaker %d, Hawking %d", s, h);
}
''')

patch(f'{tree}/iokit/conf/files.arm64', '''iokit/Kernel/arm/LavenderThermal.cpp                             optional iokitcpp
''', '''iokit/Kernel/arm/LavenderThermal.cpp                             optional iokitcpp
iokit/Kernel/arm/LavenderIOAudio2.cpp                            optional iokitcpp
''')

la = f'{tree}/iokit/Kernel/arm/LavenderAudio.cpp'
patch(la, '''extern "C" void topaz_audio_init(void);''', '''extern "C" void topaz_audio_init(void);
extern "C" void lv_ioaudio2_publish(void);      /* LavenderIOAudio2.cpp (audio_ios=1) */''')
patch(la, '''	LOG("A1 done");
	topaz_audio_init();                             /* A2/A3 with boot-arg adsp=1 */''', '''	LOG("A1 done");
	topaz_audio_init();                             /* A2/A3 with boot-arg adsp=1 */
	{
		uint32_t ios = 0;
		if (PE_parse_boot_argn("audio_ios", &ios, sizeof(ios)) && ios != 0) {
			lv_ioaudio2_publish();          /* A9 (mk_audio16.py) */
		}
	}''')

ta = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
# the iOS stream: FIFO + state, next to the A4b buffers
patch(ta, '''void
a4b_write_done(uint32_t addr_lsw, uint32_t status)
{
	a4_done++;
	if (status != 0) {
		a4_bad++;
	}
	if (a4_playing && addr_lsw >= (uint32_t)a4_pa && addr_lsw < (uint32_t)a4_pa + A4_BUF_N * 4096u) {
		a4_write((addr_lsw - (uint32_t)a4_pa) / 4096u);
	}
}''', '''/* ---- A9 (mk_audio16.py): the stream iOS plays into - a FIFO between the IOAudio2 engine and the ASM buffers */
#define SND_FIFO        4800                            /* frames, 100 ms */
static int16_t snd_fifo[SND_FIFO * 2];
static uint32_t snd_head, snd_tail, snd_under, snd_over, snd_fed;
static IOLock *snd_lock;
static volatile bool snd_want, snd_on;

extern "C" void
lv_snd_running(bool on)
{
	snd_want = on;
}

extern "C" void
lv_snd_play(const int16_t *frames, uint32_t count)
{
	if (snd_lock == NULL || !snd_on) {
		return;
	}
	IOLockLock(snd_lock);
	for (uint32_t i = 0; i < count; i++) {
		if (snd_tail - snd_head >= SND_FIFO) {
			snd_head++;                     /* full: drop the oldest */
			snd_over++;
		}
		uint32_t at = snd_tail++ % SND_FIFO;
		snd_fifo[2 * at] = frames[2 * i];
		snd_fifo[2 * at + 1] = frames[2 * i + 1];
	}
	IOLockUnlock(snd_lock);
}

/* one ASM buffer from the FIFO (silence where it runs dry), cleaned to DRAM */
static void
snd_fill(unsigned b)
{
	int16_t *s16 = (int16_t *)(a4_va + 4096u * b);
	IOLockLock(snd_lock);
	for (unsigned f = 0; f < A4_BUF_BYTES / 4; f++) {
		if (snd_head != snd_tail) {
			uint32_t at = snd_head++ % SND_FIFO;
			s16[2 * f] = snd_fifo[2 * at];
			s16[2 * f + 1] = snd_fifo[2 * at + 1];
			snd_fed++;
		} else {
			s16[2 * f] = s16[2 * f + 1] = 0;
			snd_under++;
		}
	}
	IOLockUnlock(snd_lock);
	for (uintptr_t a = (uintptr_t)s16; a < (uintptr_t)s16 + 4096u; a += 64) {
		__asm__ volatile ("dc civac, %0" :: "r"(a) : "memory");
	}
	__asm__ volatile ("dsb sy" ::: "memory");
}

void
a4b_write_done(uint32_t addr_lsw, uint32_t status)
{
	a4_done++;
	if (status != 0) {
		a4_bad++;
	}
	if ((a4_playing || snd_on) && addr_lsw >= (uint32_t)a4_pa && addr_lsw < (uint32_t)a4_pa + A4_BUF_N * 4096u) {
		unsigned b = (addr_lsw - (uint32_t)a4_pa) / 4096u;
		if (snd_on) {
			snd_fill(b);
		}
		a4_write(b);
	}
}''')
# start/stop functions after a4b_play
patch(ta, '''/* A4a: amplifier set up, MI2S clocks through the AFE port, read the amplifier while they run, stop */''', r'''static uint16_t snd_copp = 0xFFFF;
static bool snd_ready;

/* the A4b sequence, kept running for iOS */
static bool
snd_start(void)
{
	uint32_t st;
	if (!snd_ready) {
		snd_lock = IOLockAlloc();
		lpass_smmu_dump();
		snd_ready = snd_lock != NULL && lv_amp_setup() && lpass_smmu_sid1() && a4b_buffers();
		if (!snd_ready) {
			LOG("A9: stream set-up failed");
			return false;
		}
	}
	snd_head = snd_tail = snd_under = snd_over = snd_fed = 0;
	lv_mi2s_pins(true);
	if (!afe_clock(true) || !afe_i2s_config() || !afe_port(true)) {
		return false;
	}
	uint32_t m[5] = { 3 | (1u << 16), 0, (uint32_t)a4_pa, 1, A4_BUF_N * 4096u };
	if (!apr_call("ASM map", 7, 0, 0, 0x00010D92u, m, 20, &st) || apr_got_opcode != 0x00010D93u) {
		return false;
	}
	a4_handle = apr_got_p[0];
	uint32_t o[4] = { 0, 16u << 16, 0x00010BE4u, 0x00010DA5u };
	if (!apr_call("ASM open write", 7, 0x0101, 0x0101, 0x00010DB3u, o, sizeof(o), &st)) {
		return false;
	}
	uint8_t a[28];
	bzero(a, sizeof(a));
	*(uint16_t *)(a + 2) = 1;
	*(uint16_t *)(a + 4) = 0x1000;
	*(uint16_t *)(a + 6) = 0xFFFF;
	*(uint32_t *)(a + 8) = 0x00010312u;
	*(uint16_t *)(a + 12) = 2;
	*(uint16_t *)(a + 14) = 16;
	*(uint32_t *)(a + 16) = 48000;
	a[20] = 1;
	a[21] = 2;
	if (!apr_call("ADM open", 8, 0x1000, 0x1000, 0x00010326u, a, sizeof(a), &st) || apr_got_n < 2) {
		return false;
	}
	snd_copp = (uint16_t)apr_got_p[1];
	uint32_t mm[4] = { 0, 1, 1u | (1u << 16), snd_copp };
	uint8_t f[24];
	bzero(f, sizeof(f));
	*(uint32_t *)(f + 0) = 20;
	*(uint16_t *)(f + 4) = 2;
	*(uint16_t *)(f + 6) = 16;
	*(uint32_t *)(f + 8) = 48000;
	*(uint16_t *)(f + 12) = 1;
	f[16] = 1;
	f[17] = 2;
	if (!apr_call("ADM matrix map", 8, 0, 0, 0x00010325u, mm, sizeof(mm), &st) ||
	    !apr_call("ASM media format", 7, 0x0101, 0x0101, 0x00010D98u, f, sizeof(f), &st)) {
		return false;
	}
	snd_on = true;
	for (unsigned i = 0; i < A4_BUF_N; i++) {
		snd_fill(i);
		a4_write(i);
	}
	uint32_t r[3] = { 0, 0, 0 };
	if (!apr_call("ASM run", 7, 0x0101, 0x0101, 0x00010DAAu, r, sizeof(r), &st)) {
		return false;
	}
	LOG("A9: stream on; amp SPK_EN %d GLOBAL_EN %d", lv_amp_write(0x0039, 0x01), lv_amp_write(0x0500, 0x01));
	return true;
}

static void
snd_stop(void)
{
	uint32_t st;
	LOG("A9: stream off: amp %d %d; fed %u frames, %u silent (under), %u dropped (over)", lv_amp_write(0x0500, 0x00),
	    lv_amp_write(0x0039, 0x00), snd_fed, snd_under, snd_over);
	snd_on = false;
	(void)apr_call("ASM pause", 7, 0x0101, 0x0101, 0x00010BD3u, NULL, 0, &st);
	if (snd_copp != 0xFFFF) {
		(void)apr_call("ADM close", 8, 0x1000, snd_copp, 0x00010327u, NULL, 0, &st);
		snd_copp = 0xFFFF;
	}
	(void)apr_call("ASM close", 7, 0x0101, 0x0101, 0x00010BCDu, NULL, 0, &st);
	(void)apr_call("ASM unmap", 7, 0, 0, 0x00010D94u, &a4_handle, 4, &st);
	(void)afe_port(false);
	(void)afe_clock(false);
	lv_mi2s_pins(false);
}

/* called from the thread's loop: follow what the IOAudio2 engine wants */
static void
snd_poll(void)
{
	static bool failed;
	if (apr_core_state != 1 || failed) {
		return;
	}
	if (snd_want && !snd_on) {
		if (!snd_start()) {
			LOG("A9: stream start failed - stopping what was started, no more tries");
			snd_stop();
			failed = true;
		}
	} else if (!snd_want && snd_on) {
		snd_stop();
	}
}

/* A4a: amplifier set up, MI2S clocks through the AFE port, read the amplifier while they run, stop */''')
patch(ta, '''		gpr_poll();
		apr_poll();
''', '''		gpr_poll();
		apr_poll();
		snd_poll();
''')

fw = f'{tree}/bsd/dev/topaz_fw.c'
patch(fw, '''		} else if (mgreset == 3 && lv_exists(LV_MG ".lv-new")) {''', '''		}
		{
			/* lavender (xnu/src/mk_audio16.py): audio_ios=1 puts VirtualAudio.plugin back where iOS has it */
			uint32_t ios = 0;
			static const char va_off[] = "/Library/Audio/Plug-Ins/HAL.disabled/VirtualAudio.plugin";
			static const char va_on[] = "/Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin";
			if (PE_parse_boot_argn("audio_ios", &ios, sizeof(ios)) && ios != 0 && lv_exists(va_off) && !lv_exists(va_on)) {
				if (!lv_exists("/Library/Audio/Plug-Ins/HAL")) {
					(void)sweet_mkdir("/Library/Audio/Plug-Ins/HAL", 0755);
				}
				printf("LVINSTALL VirtualAudio.plugin back to HAL: %d\\n", sweet_rename(va_off, va_on));
			}
		}
		if (0) {
		} else if (mgreset == 3 && lv_exists(LV_MG ".lv-new")) {''')
print('ok')
