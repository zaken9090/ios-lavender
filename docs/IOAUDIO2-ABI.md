# IOAUDIO2-ABI: what iOS 16.7.16's audio server needs from a kernel IOAudio2 device

Step A8 of AUDIO-PLAN. Static read 2026-11-27 of the D22 user space (`/root/lv-work/mnt-ro`):
CoreAudio.framework from the dyld cache (local symbols present; `HALS_IOA2Manager`,
`HALS_IOA2Device`, `HALS_IOA2UCDevice`, `HALS_IOA2Engine2`, `HALB_UCObject`,
`AMCP::IOAudio2::*`), VirtualAudio.plugin (in `HAL.disabled` on our root), `Library/Audio/Tunings/D22`.
Scratch: `/root/lv-work/ioa2` (`CoreAudio`, `dis.txt`, `nm.txt`, `rd.py` CFString resolver, `va.txt`).
**[R]** = read from the binaries, **[I]** = inferred. No Apple code here: only names, numbers and layouts.
The kernel's own `IOAudio2DeviceUserClient` table was not decoded (D22 kernelcache is not a fileset, so
kexts cannot be split out). The client side below defines what our kernel must answer.

## 1. Matching and registry properties

**How mediaserverd finds devices** [R]: `HALS_IOA2Manager::Activate` calls
`IOServiceMatching("IOAudio2Device")` and `IOServiceAddMatchingNotification(kIOFirstPublishNotification)`.
`IOServiceMatchingHandler` then does the following for each service:
- It checks `IOObjectConformsTo(svc, "IOAudio2Device")`. Our class must be named `IOAudio2Device` or
  inherit from a metaclass with that name.
- It reads `"device UID"`. If a device with that UID already exists, it kills the old one first.
- If `"is private"` is true, it skips the service.
- It reads `"supports prewarming"` and `"data exchange blocks"`.
- It creates `HALS_IOA2Device` (class `adev`) with that UID.

`IOServiceAddInterestNotification` is used for termination. No ADT node is required by the HAL [I].

Every property is read from the **service's registry** (`IORegistryEntryCreateCFProperty` or `...Properties`,
through `HALB_UCObject::CopyProperty_*`), not through the user client [R]. Key strings use spaces, as below.

**Device keys** [R names, I types]:

| Key | Type | Notes |
|---|---|---|
| `device UID` | CFString | `Speaker`, `Hawking`, `Codec`... (section 3). Required. |
| `device name`, `device manufacturer`, `model UID` | CFString | name/manufacturer used for `lnam`/`lmak`; model UID optional |
| `transport type` | UInt32 | `'bltn'` (built-in) |
| `clock domain` | UInt32 | same non-zero value for devices sharing the I2S clock |
| `sample rate` | SInt64 CFNumber, **32.32 fixed** | 48000 << 32 [R: decoded as int + frac/2^32] |
| `io buffer frame size` | UInt32 | **ring size in frames** (also the zero-timestamp period). The max HAL IO size is 3/8 of it [R]. Use for example 4096 or 8192. |
| `input safety offset`, `output safety offset` | UInt32 | frames, for example 256..512 |
| `input latency`, `output latency` | UInt32 | frames |
| `wants input trap`, `wants output trap` | bool | **false** (no DoIO trap, see 2.3) |
| `supports prewarming` | bool | false (then StartIO = selector 0) |
| `supports client description` | bool | false (skips selector 12) |
| `is private` | bool | false |
| `is running` | bool | IsRunning (`goin`) |
| `output streams`, `input streams` | CFArray of stream dicts | |
| `controls` | CFArray of control dicts | |
| optional | | `input/output channel layout`, `legacy UID list`, `allows auto route`, `custom property info`, `headset info`, `data exchange blocks`, `IOAudioEngineDescription`, `exclusive access owner` (hog mode; the HAL writes it with SetProperty_SInt32 = `setProperties`) |

**Stream dict** [R]:
- `stream ID`: UInt32, non-zero and unique within the device. It is also the map type.
- `starting channel`: UInt32, starts at 1.
- `terminal type`: UInt32, `'spkr'` or `'micr'` (for example).
- `buffer mapping options`: UInt32, default 1.
- `current format`: a dict with `sample rate` (Fixed64 [I]), `format ID` (`'lpcm'`), `format flags`,
  `bytes per packet`, `frames per packet`, `bytes per frame`, `channels per frame`, `bits per channel`.
- `available formats`: an array of the same dicts, each with `min sample rate` and `max sample rate`.

Use the physical format the kernel plays: s16le interleaved stereo, flags `kAudioFormatFlagIsSignedInteger|IsPacked`
(0xC). The HAL writes the ring in that format.

**Control dict** [R]:
- Always: `control ID` (UInt32, unique), `class`, `base class`, `scope` (`'glob'`/`'inpt'`/`'outp'`),
  `element`, `value`, `read only`, `name`.
- Level (volume, class `'vlme'`, base `'levl'`): `minimum value`, `maximum value`, `range map`. The range
  map is an array of `{start int value, integer steps, start db value, db per step}` (dB as Fixed64 [I]).
  `transfer function` is optional.
- Selector (data source, class `'dsrc'`, base `'slct'`): `value` (current item ID) and `selectors`, an array
  of `{value, name, kind}` items. `multi-selector` is optional.
- Others: `left value`/`center value`/`right value` (stereo pan), `property selectors`, `descriptor`.

## 2. IOAudio2DeviceUserClient

`IOServiceOpen(svc, task, type 0)` [R]. The client uses selectors **0..12** only. That fits a 13-entry table
and corrects the "~34" in AUDIO-PLAN. All calls go through `IOConnectCallMethod`. Return 0 for success.

| Sel | Name (client) | Scalars in | Struct in | Out | Meaning |
|---|---|---|---|---|---|
| 0 | TellHardwareToStart (no prewarm) | 0 | - | - | start IO engine [R] |
| 1 | TellHardwareToStop | 0 | - | - | stop IO engine [R] |
| 2 | SetControlValue | 2: controlID, value | - | 1 scalar: value applied | [R] |
| 3 | PerformConfigChange | 0 | 32 B IOAudio2Notification | - | the HAL acks a `conf` notification by echoing it; the kernel applies the pending change [R] |
| 4 | (HALS_IOA2Device::SetPropertyData) | 0 | 8 B | - | nominal sample rate, Fixed64 [R size, I meaning; matches public UniXNU notes] |
| 5 | SetStreamCurrentFormat | 1: streamID | 40 B ASBD | - | [R] |
| 6 | SetStreamActive | 2: streamID, bool | - | - | sent for every stream after mapping [R] |
| 7 | MoveDataExchangeBlockData | 3 | - | - | optional (data exchange blocks) [R] |
| 8 | SetMultiControlValue | 0 | var: control ID + values | var | multi-selector [R] |
| 9 | MoveBlockControlData | 3 | - | - | block controls (`lbko`/`seqb`), optional [R] |
| 10 | StartIOWithFlags | 1: flags | - | 1 scalar | prewarm path; flags 1 = prewarm state [R] |
| 11 | StopIOWithFlags | 1: flags | - | 1 scalar | [R] |
| 12 | ClientDescriptionChanged | 2 | - | (AMCP path: struct out) | only if `supports client description` [R] |

**2.1 Memory** (`IOConnectMapMemory64(conn, type, task, &addr, &size, options)`) [R]:

| Type | What | Options | Check |
|---|---|---|---|
| `0` | engine status (IOAudio2EngineStatus) | 1 (anywhere) | size must be >= 0x28, otherwise the HAL throws |
| `0x10000000 + streamID` | that stream's IO ring (`ringFrames * bytesPerFrame`) | the stream's `buffer mapping options` | non-NULL |
| `0x20000000 + blockID` [I] | data exchange blocks | | optional |
| `0x30000000 \| controlID` | block-control buffers | | optional |

**2.2 Engine status layout** (all u64, little-endian) [R]:

| Off | Field | Written by |
|---|---|---|
| 0x00 | zero-timestamp **sample time** | kernel |
| 0x08 | zero-timestamp **host time** (mach_absolute_time ticks) | kernel |
| 0x10 | **seed** | kernel (change it on discontinuity/restart) |
| 0x18 | highest input sample time read by the HAL (end of its last read) | HAL |
| 0x20 | highest output sample time written by the HAL (end of its last write) | HAL |

The HAL reads the 0x00/0x08/0x10 triple, re-reads it, and loops until both reads are equal. The kernel
should write sample time, host time and seed and then issue a barrier. 0x18 and 0x20 are zeroed when the
first IO thread starts.

How the kernel publishes time [I, the standard IOAudio scheme, matching the HAL code]: each time the
hardware position wraps the ring, add `ringFrames` to the sample time and set the host time to the time of the wrap.
The HAL extrapolates `rate = ringFrames / (hostΔ)`.

**Write position** [R]: for an output cycle with output sample time T and N frames, the HAL `memcpy`s to
ring offset `(T mod ringFrames) * bytesPerFrame`, wrapping around the end. It then raises status+0x20 to
T+N. Input is the mirror (it reads at `(T mod ring)` and raises +0x18). The HAL writes ahead of the
hardware by at least `output safety offset`. The kernel reads the ring at its own DMA/ASM position. It
can use +0x20 to see how far valid data goes and zero the stale part (an IOAudio-style erase-head [I]).

**2.3 Trap.** `DoIO` = `IOConnectTrap6(conn, 0, isInput, nFrames, T_hi, T_lo, host_hi, host_lo)` [R]. It is
called only when `wants input/output trap` is true. Set both to false and the trap is never called.

## 3. VirtualAudio: devices for the speaker route

These are the device UIDs it knows [R strings]: `Speaker`, `Codec`, `Hawking` (`VirtualAudioDevice_Hawking`,
VAD type `vhaw`, companion of `vdef`), `Actuator`, `Baseband`/`Baseband Voice`, `Halogen`, `Digital Mic`,
`AppleSongbirdDSP`, `PuffinInput/Output`. Its port names are `Speaker`, `Receiver`, `Headphones`,
`Built-In Microphone`.

The microphone data-source fourccs it accepts are `imic`, `smic`, `fmic`, `lmic`, `imi1`, `imi2`
(also `tmic`, `umic`, `imi3`, `imi4` in its tables) [R]. D22 tunings name the bottom, front, back and beam
mics. A likely mapping is imic = bottom, fmic = front, smic = back [I].

Minimal set [I; the first project never ran it, the coordinator confirmed]:
1. **`Speaker`**: one output stream, 2 ch s16 48 kHz, terminal `'spkr'`, transport `'bltn'`. Add one output
   volume control (`vlme`, scope `outp`, element 0). iOS keeps the D22 speaker in software volume and sets
   the control to 0 dB. An IV-sense input stream on `Speaker` is what D22 has. Add a silent 2-ch input only
   if the route is refused without it.
2. **`Hawking`**: one silent 1-ch input stream, nothing else. VirtualAudio's speaker route needs this
   companion, and without it everything stays on the null port.
3. **`Codec`**: one 1-ch input stream, terminal `'micr'`, plus an input data-source control (`dsrc`, scope
   `inpt`) with at least `imic`. VirtualAudio refuses a codec input without data sources. Public port
   notes (UniXNU-droidvm) report that `Codec` gave "no port" for them, so try the speaker route first and
   add `Codec` after it works.
4. Later: Receiver and headphones. D22 drives the receiver from the codec (CS42L75), so expose them as an
   output on `Codec` with output data sources [I]. Jack plug/unplug becomes a `conf`/`prop` notification
   (data-source list change). `Actuator` (haptics) comes in PLAN-DRIVERS 6.

The `Speaker`, `Hawking` and `Codec` devices should share one `clock domain`. Tunings
(`d22_speaker_general` etc.) are loaded by mediaserverd itself.

## 4. Notifications

Setup: `IOConnectSetNotificationPort(conn, type 0, port, refcon = HAL device object ID)` [R]. The kernel
keeps the port from `registerNotificationPort(port, 0, refCon)`. Each message is a plain mach message
(no reply) of at most 0x448 bytes [R]:

```
0x00 mach_msg_header_t (24 B)        0x18 u32 (reserved [I])   0x1c u32 count (<= 33)
0x20 + 32*i  IOAudio2Notification:  u32 objectID (stream/control ID, 0 = device)
                                     u32 type
                                     u32 payload[6]
```

| type | Effect in the HAL [R] |
|---|---|
| `'conf'` | config change. The HAL re-reads streams and controls from the registry (update the properties first) and calls selector 3 with the same 32 bytes. |
| `'prop'` | property changed. The payload is an AudioObjectPropertyAddress {selector, scope, element} at +8, for the object `objectID`. |
| `'cval'` | control value changed. The new value is at +8, for control `objectID`. |
| `'crng'` | control range changed. The HAL re-reads that control dict. |
| `'goin'`, `'halt'` | IsRunning (`goin`) changed. Send them on engine start/stop or halt. |

No overload message was seen in the IOA2 path [R: the dispatch has only the types above].

## 5. Smallest test (A9)

1. Kernel: register `IOAudio2Device` (UID `Speaker`), set the registry keys from section 1, and set
   `IOUserClientClass` to our `IOAudio2DeviceUserClient`. Then call `registerService()`. Register
   `Hawking` the same way: one input stream, its ring kept zeroed.
2. User client: `clientMemoryForType` 0 = status page (one page). 0x10000000+ID = the stream ring from the
   A4 pool (a cleaned DMA buffer, mapped into mediaserverd). Selectors 0/1/10/11 start and stop the A4
   ASM session. 2/5/6/4 log and return 0. 3 returns 0.
3. Timing: start the ASM playback reading the ring. On each period (or WRITE_DONE), advance the position.
   On every wrap, update status sampleTime += ringFrames and hostTime, then a barrier.
4. Root: put `VirtualAudio.plugin` back into `/Library/Audio/Plug-Ins/HAL` (drop the `audio()` move from
   `tools/sweet-root-tweaks.py`).
5. Check (L): mediaserverd stays up (`sweetstderr=mediaserverd`: no "this is not an IOAudio2Device",
   "Mapped engine status is not large enough", "failed to map in the memory"). Selectors 0 (or 10) and 6
   are logged. Trigger a UI sound (lv:tap the keyboard or lock), and the kernel logs a non-zero sample
   peak in the ring. If there is no route, add the IV input on `Speaker`, then `Codec`.

## 6. Public references (checked 2026-11-27, no Apple code, read for comparison only)

| Project | What it shows | Use |
|---|---|---|
| github.com/Droid-VM/UniXNU-droidvm `package/DroidVMAudio.cpp` (BSD-2-Clause-Patent) | Kernel IOAudio2Device and user client with selectors 0-6 and 10-12, status {+0 sample, +8 host, +0x10 seed, +0x20 HAL write end}, map type 0x10000000+ID, 32.32 rates. Reports `Speaker`/`Mic` working and `Codec` "no port". | Best pattern; agrees with section 2 |
| github.com/lenzhang/UniXNU-xiaomipad8pro `package/PianoAudio/*`, `docs/drivers/audio.md` | Same ABI with real control dicts, on SM8750 with a DSP | Controls/volume |
| github.com/nagatoquin33/UniXNU-diting `drivers/DitingPower/DitingIOAudio2.h` (BSD-2-Clause-Patent) | Output-only minimal set of registry keys, volume/mute with a range map, DoIO no-op. It places the HAL position at +0x18/+0x20, which our read confirms: +0x18 input, +0x20 output. | Smallest example |
| github.com/OctoDevStudios/ios-popsicle `wsl/PandoraAudio.cpp` | Notes taken from the same iPhone X 20H392 binaries: 13 methods, memory type = `type>>28`, the HAL waits 5 s for a zero timestamp | Cross-check |
| HackiOS RedwoodAudio.driver (first project's `userland/audio`) | An AudioServerPlugIn in user space, not IOAudio2. It contains VirtualAudio notes (Hawking, Codec data sources). It never played sound on our side. | VirtualAudio notes only |
| darlinghq, alephsecurity xnu-qemu-arm64, qemu-t8030 | Nothing on IOAudio2 | - |
| BlackHole, BackgroundMusic, libASPL, AppleALC/VoodooHDA | AudioServerPlugIn or old IOAudioFamily code; not searched in depth | not relevant |
