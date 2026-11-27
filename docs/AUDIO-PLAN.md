# AUDIO-PLAN: full audio on lavender (SDM660) for iOS 16.7.16 (D22 user space)

Survey 2026-11-26. Sources: kernel tree `ci/run-45476170670/tree/xnu`, generators `xnu/src/mk_*.py`,
stock DT `dump/miui-boot/split/dtb5.dts` (+ `dtbo.img`), NON-HLOS firmware volume
(`downloads/miui-nonhlos`), D22 kernelcache and `d22ap.adt`, iOS root (`/root/lv-work/mnt-ro`),
first project (`first-project/ios-lavender/userland/audio`, reference only).
**[R]** = read from code/data, **[I]** = inferred. No Apple code, no blobs, no identifiers here.

## 1. State today on our port

**There is no working audio on lavender.** PLAN-DRIVERS item 5 "Готово: звуки системи, гучність
кнопками" is the *done criterion*, not the current state; the table in section 1 of the same file
says "Звук | TopazAudio, topaz_redwood_audio | не запускали". [R]

| Piece | What it is | Status on lavender |
|---|---|---|
| `iokit/Kernel/arm/TopazAudio.cpp` (1980 lines) | Base-project (topaz, **SM6225**) driver: PAS boot of the ADSP, SMP2P, GLINK "lpass" edge, QRTR + pd-mapper, **GPR/AudioReach** (APM graph), WCD937x codec over SoundWire, sia8159 amp, `/dev/topaz-audio` (48 kHz s16 stereo ring, ioctl `_IOW('r',1,{below,muted})` volume), audio thread | Called from `AppleCLCD::start()` via `topaz_audio_init()`, gated by boot-arg `adsp=1`, never run. Every address is SM6225's (carveout 0x53800000, LPASS 0x0A600000, TLMM GPIO92). [R] |
| `bsd/dev/topaz_redwood_audio.c` | `/dev/redwood-audio` alias of the same node for HackiOS's `RedwoodAudio.driver` HAL plug-in | Not used: that plug-in is not on our root. [R] |
| `bsd/dev/sweet_i2c1.c` | GENI QUP0 SE1 polled I2C (topaz battery bus) with a write helper "sia8159 amp at 0x2b" | SM6225 GENI hardware; SDM660 has BLSP QUP, not GENI. Not usable. [R] |
| `sweet_keys.c` (`mk_keys.py`) | Volume down = PM660 PON RESIN, volume up = PM660L GPIO 7, delivered as HID | Works: the keys reach iOS. They change nothing audible: no route/device exists. [R]/[I] |
| Root image `tools/sweet-root-tweaks.py` (`audio()`) | Moves `/Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin` to `HAL.disabled` ("mediaserverd crash"); sets `StartRecorderServer=false` in MediaToolbox configs | Active on today's root (`images/mkroot.log`: "VirtualAudio.plugin disabled"). This is a workaround that disables an original iOS component; it must be undone once a device exists (rule "keep original functions"). [R] |
| IOKit audio classes published | none (no `IOAudio2Device`, no AppleEmbeddedAudio-like service) | [R] |

PCM path to hardware today: none. Hardware blocks driven: none (the PMIC and I2C code above is
for the keys and the topaz battery). Stubs: none for audio; mediaserverd runs without VirtualAudio.

Reusable as-is from the lavender modem work (MODEM-PLAN): SMEM + cached-item lookup (1048), APCS
doorbell `topaz_apcs_kick`, SCM calls, pool, FAT16 firmware reader `topaz_part_fw_*` (1043),
GLINK/QRTR/pd-mapper on lavender addresses, read-only ext4 reader (1081/1082, for `/vendor` or
`persist` files), DIAG/QMI bridge (1064+), RPM requests. From TopazAudio: the PAS loader
(init_image/mem_setup/auth_reset), SMP2P out/in, crash-reason read, ring + thread design.

## 2. Lavender audio hardware (stock DT dtb5, firmware)

| Block | Details | Src |
|---|---|---|
| Sound card | `sound` node `qcom,sdm660-asoc-snd` "sdm660-snd-card", status okay; `sound-9335` (WCD9335/tasha) and `sound-tavil` (WCD934x) **disabled**; dtbo only disables `slim_aud`. `qcom,wsa-disable`. | [R] |
| Digital codec | SDM660 internal: `msm-dig-codec` (LPASS digital codec core, reg 0x152C0000), `msm-sdw-codec@152c1000` (SoundWire for WSA881x, unused since WSA disabled). MCLK "INT_MCLK0" 9.6 MHz. | [R] |
| Analog codec | **PM660L** `analog-codec@f000` (`qcom,pmic-analog-codec`) on SPMI **SID 3**, reg 0xF000 +0x200 (analog 0xF000, digital-of-analog 0xF100 [I]). Interrupts on 0xF0/0xF1 blocks: spk_cnp/clip/ocp, ins_rem_det1, but_rel/press_det, ins_rem_det, mbhc_int, ear_ocp, hphr/hphl_ocp, ear/hphr/hphl_cnp. Supplies: cdc-vdda-cp and cdc-vdd-pa = PM660 S4 (RPM `smpa` 4), mic bias = PM660L L7. PDM link codec<->PMIC on LPI pins (`cdc_pdm_pinctrl`, `cdc_comp_pinctrl`). | [R] |
| Speaker amp | External smart amp on **I2C `i2c@c1b6000`** (BLSP QUP, SDA/SCL = TLMM GPIO 22/23, SPI 102). Three alternative parts are all enabled in the DT: **TFA98xx @0x34**, **MAX98927 @0x3A**, **TAS2557 @0x4C**; shared reset GPIO 77 (0x4D), IRQ GPIO 73 (0x49), supply PM660L L6. Which one this unit has: unknown, probe at run time (step A1). Fed by **Primary MI2S** (TLMM GPIO 12-15, `pri_mi2s`/`pri_mi2s_ws` in the card's pinctrl). | [R] parts/bus, [I] MI2S |
| Earpiece | PM660L EAR output (analog codec "ear" interrupts); no separate amp node. | [I] |
| Headphone jack | 3.5 mm, PM660L HPHL/HPHR + MBHC (`msm-mbhc-hphl-swh`, `gnd-swh`), headset mic bias **external** (`msm-hs-micbias-type = "external"`, `micbias1-ext-cap`). No US/Euro switch in the active card. | [R] |
| Microphones | Routing: "Handset Mic" (AMIC1, bias External), "Headset Mic" (AMIC2, bias External2), "Secondary Mic" (AMIC3). DMIC pins defined but lavender has 2 analog mics (bottom, top). | [R] routing, [I] count |
| LPASS | PIL `qcom,lpass@15700000` = `pil-tz-generic`, **PAS id 1**, firmware "adsp", carveout **0x92A00000 + 0x1E00000** (`adsp_fw_region`), SPI 162; crash reason SMEM 423; proxy votes CX + XO. LPI TLMM 0x15070000 (32 pins, MCLK0 on LPI gpio18), AVTimer 0x150F700C. LPASS SMMU `smmu-lpass_q6@5100000`; audio buffers use stream **1** (`msm-audio-ion iommus = <lpass_q6 1>`). | [R] |
| ADSP links | SMP2P remote pid 2, APCS 0x17911008 bit **10**, SPI 158; GLINK edge "lpass", SMEM 0x86000000, APCS bit **9** (irq-mask 0x200), SPI 157. Items 443 in / 429 out (Qualcomm standard, same as TopazAudio). | [R] bits, [I] items |
| ADSP firmware | `image/adsp.mdt` + `adsp.b00..b21` on the modem FAT partition, plus pd-mapper JSONs `adspr.jsn`, `adspua.jsn` (`avs/audio`, `msm/adsp/audio_pd`). Build **ADSP.VT.4.0** (Elite) with `apr_glink.c`, `apr_voice_svc`, `apr_apps2`: the protocol is **APR over GLINK** (q6core/AFE/ASM/ADM/voice), **not** GPR/AudioReach. | [R] |

ADSP is required [I]: on SDM660 the LPASS clocks (internal MCLK, MI2S bit clocks), the LPAIF DMA and
the AFE ports are owned by the ADSP firmware (Android sets them through AFE APR commands; the HLOS
only maps the digital-codec registers). Driving LPAIF directly from the AP (like msm8916 without a
DSP) is unproven on SDM660 and likely XPU-blocked; keep it as a fallback experiment only.

Android signal path [I, from the DT and the msm-4.4 sdm660 machine driver]:
`ASM stream (shared buffer, SMMU SID 1) -> ADM COPP -> AFE port`, with ports
`PRIMARY_MI2S_RX` -> smart amp -> speaker; `INT0_MI2S_RX` -> dig codec RX1/RX2 -> PDM -> PM660L EAR/HPH;
`INT3_MI2S_TX` <- dig codec TX <- PM660L ADC1/2/3 <- mics. Voice: modem <-> ADSP CVS/CVP/MVM
(APR), AFE ports as above; the AP only starts the session and picks devices.

## 3. What iOS 16 on D22 expects

| Layer | What | Src |
|---|---|---|
| D22 kexts | IOAudio2Family, AppleEmbeddedAudio (`AppleEmbeddedAudioDevice`, `...HeadsetSwitch`, `...Buttons`), AppleARMIISAudio (MCA I2S), AppleCS42L75Audio (codec, SPI), AppleCS35L26Amp (amp, I2C), AppleAOPAudio (always-on mics, voice trigger), AppleMikeyBusAudio, IOAudioCodecs, AppleHapticsSupportCallan | [R] kernelcache |
| HAL entry | CoreAudio's built-in IOAudio2 driver (`AMCP::IOAudio2::Driver`, `HALS_IOA2Device`, in mediaserverd) matches services of class **`IOAudio2Device`** and opens **`IOAudio2DeviceUserClient`** (entitlement string `com.apple.private.audio.driver-host`). Kernel strings give the dictionary keys: device UID, transport type, input/output streams, stream ID, starting channel, current/available formats, terminal type, buffer mapping options, Sample Time / Host Time / Time Stamp Seed, Engine Running, controls (control ID, base class, selectors, min/max, range map, dB per step). The user client has ~34 external methods (method-type map string length). Exact selectors: to be read (step A8). | [R] names, [I] counts |
| Routing | `/Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin` builds iOS routes from devices it knows **by UID**: `Speaker`, `Codec`, `Hawking`, `Actuator`, `Baseband`/`Baseband Voice`, `Halogen`; ports `Receiver`, `Headphones`, `Built-In Microphone`. On D22 the first project found: `Speaker` (stereo out + IV-sense in), `Hawking` (mandatory silent companion input, VAD type 'vhaw'), `Codec` (input whose **data sources** are the mics; VirtualAudio refuses a codec without them), `Actuator` (haptics). Tunings `/Library/Audio/Tunings/D22` (d22_speaker_general etc.) are applied by mediaserverd itself. | [R] strings + first-project plug-in |
| D22 ADT | `arm-io/spi2/audio-codec` (`audio-control,cs42l75`: mic/micbias map, receiver, HAC, ASP config), `arm-io/i2c2/audio-speaker-top` (`audio-control,cs35l26`, `speaker-calib = syscfg/SpCl`), MCA data nodes `mca1a/audio-codec`, `mca2a/audio-speaker-top`, `mca2b/audio-loopback`, **`mca3a/audio-baseband-voice`** (`audio-data,baseband-voice`, clock sources System/Baseband), `mca3b/audio-halogen`, `mca5a/audio-haptic`, `aop/.../aop-audio` (mca0/1, voice trigger), `product/audio` (`supports-always-listening`, `wireless-splitter`). | [R] |
| Jack | iPhone X has no 3.5 mm jack; headsets come over Lightning (MikeyBus, `AppleEmbeddedAudioHeadsetSwitch`, "Headphones detected. Begin mic detection"). Our jack must be presented as the `Headphones` port (+ headset mic data source) with plug notifications. | [R] strings, [I] mapping |
| Call audio | D22's Qualcomm modem sends voice PCM to the AP over **I2S** (MCA3 `audio-baseband-voice`); mediaserverd mixes/processes it (VP tunings `d22-vp-*`). `BasebandVoice.driver` (PCIe voice) refuses to publish: "BVCanPublishBasebandVoice: NO (I2S device present)". CommCenter also asks the modem for Apple's QMI service "AUDIO" (refused today, MODEM-PLAN T4). | [R] |

Call audio on lavender [I]: voice never needs to pass through the AP. The plan is to publish the
`Baseband Voice` device to keep mediaserverd's call state machine happy (silent PCM), and when it
starts I/O (or the QMI VOICE call-status indication passes the bridge), the kernel starts the ADSP
voice session (MVM/CVS/CVP, CS-voice VSID) on the AFE ports of the route mediaserverd selected
(receiver/speaker/headset). Mute/volume map to CVP/CVS commands.

## 4. Steps (smallest verifiable first)

Verification: **L** = USB log only (autonomous), **E** = user's ears/voice/action needed.
Boot-args kept separate per stage (`audio=1`, `audio_amp=`, `audio_tone=` ...), defaults off.

| Step | Work | Done when | Check |
|---|---|---|---|
| A1 Census | No DSP. Read PM660L analog codec revision/peripheral type at SID 3 0xF000/0xF100 (sweet_spmi). Bit-bang I2C on GPIO 22/23 (as sweet_touch does on its pins), pulse reset GPIO 77, read the ID register of 0x34 / 0x3A / 0x4C. Read PM660L L6/L7, PM660 S4 state. | Log names the amp part and the codec revision | L |
| A2 ADSP boot | New `LavAudio` (or TopazAudio rewritten): PAS id 1, firmware via FAT reader, carveout 0x92A00000 (check ADT memory does not cover it), RPM CX + XO votes, SMP2P 429/443 bit 10, refuse over stale SMEM state. | "slave-kernel" READY from item 443; crash reason empty after 60 s | L |
| A3 Links + APR | GLINK "lpass" edge (bit 9), QRTR with the ADSP, pd-mapper serving `avs/audio` from `adspr.jsn`; open the APR channel (`apr_audio_svc`, name to confirm in the log of channel opens), q6core ADSP-state query, AFE/ASM/ADM version queries. | ADSP reports ready; service versions logged | L |
| A4 Speaker tone | LPASS SMMU SID 1 bypass/identity (plain ldr/str, as for the GPU SMMU); AFE clock + `PRIMARY_MI2S_RX` 48k/16/2; amp init for the part found in A1 (MAX98927 needs no firmware; TFA98xx/TAS2557 need their container/firmware from `/vendor` via the ext4 reader, never committed); ASM playback of a kernel-generated tone from a pool ring. | AFE/ASM return 0; amp status registers show clocks locked, no fault; then the user hears the tone once | L + E (once) |
| A5 Earpiece + headphones | AFE `INT0_MI2S_RX`; dig-codec RX path (AP-mapped 0x152C0000); PM660L EAR and HPH power-up sequences (charge pump, PA). | Codec registers read back, cnp interrupts seen, no OCP; user confirms earpiece once | L + E (once) |
| A6 Mics | AFE `INT3_MI2S_TX`, PM660L ADC1/ADC3 + mic bias; ASM record into a ring. **Acoustic loopback**: play a tone on speaker (A4) while recording, Goertzel at that frequency per mic. | Each mic's level at the tone frequency well above the silent baseline | L (autonomous) |
| A7 Jack (MBHC) | PM660L insertion/removal + button interrupts (polled first), headset vs headphone by mic detection. | Log shows plug/unplug/button | L after one user plug-in (E) |
| A8 IOAudio2 ABI | Static read (like `ABP-ABI.md`) of CoreAudio's IOAudio2 driver and VirtualAudio: matching, user-client selectors, stream/engine dictionaries, buffer mapping and zero timestamps, controls (volume, data sources), notifications, the UIDs and data sources VirtualAudio needs for Speaker/Codec/Hawking/Receiver/Headphones. Write `docs/IOAUDIO2-ABI.md`. | Doc complete | static |
| A9 iOS speaker | Kernel `IOAudio2Device` services `Speaker` (+ `Hawking` companion) backed by the A4 stream; minimal ADT audio nodes if matching needs them (`tools/mkadt.py`). Restore VirtualAudio (remove the `audio()` move in sweet-root-tweaks; keep StartRecorderServer change only if still needed). | mediaserverd stays up; VirtualAudio routes to Speaker (`sweetstderr=mediaserverd`); kernel logs non-zero sample peaks when a UI sound plays (lock, keyboard click via lv:tap) | L |
| A10 Volume | IOAudio2 volume control (or ASM soft volume / dig-codec gain); keys already reach iOS. | Volume HUD; logged gain follows lv key presses | L |
| A11 Routes | `Codec` device: input data sources (bottom, top, headset mic), outputs Receiver / Headphones; jack events from A7 raise route changes; earpiece in Voice Memos/calls. | mediaserverd route-change lines for plug/unplug; recording in Voice Memos has non-silent samples | L (+E for quality) |
| A12 Call audio | `audio-baseband-voice` equivalent device (silent I2S stand-in); kernel starts/stops the ADSP voice session (APR MVM/CVS/CVP with the modem) on call start, devices per route; mute, in-call volume; look at what CommCenter wants from QMI "AUDIO". | Call-state + voice-session-up lines; then a real call (user speaks/listens) | L + E |
| A13 Polish | Speaker protection/calibration (amp container), sample-rate switching 44.1/48k, idle: graphs and LPASS clocks off when silent (PLAN-DRIVERS idle goal), ADSP SSR handling. Haptics (`Actuator`) is PLAN-DRIVERS item 6. | No audio CPU load at idle | L |

Order rationale: A1 needs nothing new and decides the amp driver; A2-A3 reuse the modem stack;
A6's loopback lets every later step be checked from the log; the iOS side (A8+) starts once a PCM
path exists, so each kernel piece has been proven before iOS touches it.

## 5. Risks and notes

- SM6225 pieces in TopazAudio (GPR/AudioReach, WCD937x, SoundWire, sia8159, GENI I2C) do not apply;
  only its PAS/SMP2P/ring skeleton does. [R]
- ADSP boot leaves SMEM state; like the modem, never restart over stale items without a SoC reset.
- The LPASS SMMU may need the same care as the GPU SMMU (C accesses hung there; use plain ldr/str).
- Calibration (ACDB) is not available without vendor files; the ADSP runs uncalibrated defaults
  [I]. Voice EC/NS quality may need ACDB data read at run time from `/vendor` (never committed).
- The three amp candidates share one reset GPIO; probe with the reset released and only read.
- Proprietary firmware (adsp.*, amp containers) is read from the phone's own partitions at run time.

## State

- 2026-11-26: survey written. Next: A1.
- 2026-11-26: A1 (xnu 1116-1117, run e132): PM660L L6 1.8 V on; on I2C6 (GPIO 22/23 bit-banged) only 0x3A ACKs, only with GPIO 77 high -> the amplifier is **MAX98927** (reset active low, no firmware); its revision register 0x01FF read 0x00 (expected 0x40, re-check with a longer reset delay). NFC 0x28 does not answer (not powered). The SPMI observer read of PM660L SID 3 0xF000 hung the system (1116) - codec ids now only with audio_spmi=1 (1117); read the codec through an owned channel later.
- A2/A3 done (xnu 1119, 1122, 1123; runs e133-e135): TopazAudio's PAS/SMP2P/GLINK/QRTR on lavender values (carveout 0x92A00000 + 0x1E00000, GLINK bit 9), started from the audio thread after A1 with adsp=1: PAS init/mem_setup/auth_and_reset 0, slave-kernel READY in 30 ms, GLINK channels glink_ssr, apr_audio_svc, apr_apps2, fastrpcglink-apps-dsp, LOOPBACK_CTL_LPASS, IPCRTR. APR client on apr_audio_svc (16-byte headers out, hdr_field 0x0140; answers come with 32-byte headers, hdr_field 0x81/0x181): AVCS state 1 READY; services core 3 (0x40002), AFE 4 (0x260000), ASM 7 (0x70002), ADM 8 (0x70000), 9/a/b (0x10000), c, d. Next: A4 (docs/APR-PLAYBACK.md in work).
- **A4 done (xnu 1124-1133, run tb, 2026-11-27): the user heard the 1 kHz tone from the speaker.** Path: amplifier is a **MAX98937** (REV 0x0600 = 0x43; Xiaomi lavender-q-oss max98937.c init table, speaker 0x0039=1, global 0x0500=1; docs/MAX98927.md); pins GPIO 12/13/14 pri_mi2s; AFE clock set PRI_MI2S IBIT 1.536 MHz, I2S config, DEVICE_START on 0x1000; LPASS SMMU: SID 1 -> context bank 0 with M=0 (bypass refused by the hypervisor); buffers from TopazModem's pool, cleaned to DRAM; ASM map (pool 3, msw 1) / OPEN_WRITE_V3 / ADM OPEN_V5 NULL COPP / matrix map / media format / WRITE_V2 x4 + resubmit on WRITE_DONE / RUN_V2; clean stop. APR commands need hdr_field 0x0250. Tunables: audio_step, audio_secs, audio_level, audio_freq, audio_amp, audio_amp_init, audio_amp_on, audio_amp_read (ranges). Test sounds from now on: quiet and 1 s (user request).
- **A9 works (xnu 1134, run ia1, 2026-11-27): the user hears iOS's own system sounds from the speaker.** LavenderIOAudio2.cpp publishes IOAudio2Device "Speaker" (2 ch out) and "Hawking" (silent 1 ch in) with the registry description of docs/IOAUDIO2-ABI.md (structure after UniXNU-droidvm DroidVMAudio.cpp); mediaserverd opens both, maps status + rings, takes hog mode, starts/stops the speaker per sound; the engine (5 ms periods) feeds TopazAudio's FIFO, which refills the ASM buffers on WRITE_DONE. VirtualAudio.plugin put back into HAL by the installer with audio_ios=1. 1135: kernel volume audio_vol (percent, default 0 = silent at start, user request) until A10 connects iOS's volume.
- **A10 done (xnu 1136, run ia3): volume control** 'vlme' (control 1, 0..100 = -64..0 dB) on Speaker; iOS sets it to 100 at start and applies its own volume in software (as on D22); the user confirmed the volume buttons and the Sounds slider change the loudness. Silent until iOS's first set (audio_vol default 0). Left: A5 earpiece/headphones, A6 mics, A7 jack, A11 routes, A12 call audio, A13 idle power; Bluetooth pairing test.
