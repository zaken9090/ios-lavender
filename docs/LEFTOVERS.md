# LEFTOVERS: tries, diagnostics and workarounds still in the kernel and the iOS image

Audit 2026-11-26, read only. Kernel: patches 1000-1112 (113, all applied in
`ci/run-45476170670/tree/xnu`, one commit each). Image: `tools/wsl/mkroot.sh` (runs the base's
`sweet-root-tweaks.py`, log `images/mkroot.log`) plus the local `downloads/root-files/launchd.plist`
written by patch 1035. Evidence = generator docstrings (`xnu/src/mk_*.py`), the tree, MODEM-PLAN.md,
BT-PLAN.md, GPU-PLAN.md, PLAN-DRIVERS.md, AUDIO-PLAN.md.

Classes: **FIX** needed. **DIAG** logging/diagnostics only (gate given: *default-on* or the boot-arg).
**TRY-FAILED** did not help per later docstrings/docs, still in the tree (*active* or *inactive* =
off unless a boot-arg). **SUPERSEDED** replaced by a later patch (code still there unless noted).
**WORKAROUND** stubs/disables/masks an iOS or hardware function instead of fixing the cause.
"emul." = deliberate emulation of iPhone hardware (by design, not a workaround).

## Display / GPU (27)

| Patch | Class | Evidence / note |
|---|---|---|
| 1000 console-display | FIX | splash console |
| 1004 fit | FIX + DIAG | fit is used; touch report log *default-on* (`sweettouchdiag` default 40) |
| 1009 gpu-power | FIX + DIAG | `lavender_gpu_probe(7)` used by 1014; stages 1-6 only via `lv_gpu=N` |
| 1011 gpu-zap | FIX | used by `lavender_gpu_bringup()` |
| 1012 gpu-smmu | FIX + DIAG | mode 10 used; `lv_gpu=9` read-only dump, `lv_smmu_impl` path "hung the phone" |
| 1013 gpu-cp | FIX + SUPERSEDED | `a5_hw_init` used; `lavender_gpu_cp()` ring/fence test only with `lv_gpu=11` (1014 has its own cp_start) |
| 1014 redwood-gpu | FIX | gpu=1 path |
| 1015 userland-install | FIX | GPU userland, bbd_wrap |
| 1016 pool-subranges | FIX | lock-screen hang fix |
| 1017 sample-kernel-stacks | DIAG | SMK/SMM lines, sampler *default-on* (`sweetsample` default "SpringBoard,backboardd") |
| 1018 surface-stats | DIAG | SMS line, same sampler |
| 1019 zombie-no-pixels | FIX | "wired 1700 -> 219 MB" |
| 1020 mdp-direct | FIX | |
| 1021 qseed3-fit | FIX | provisional ("Scaling is NOT final", GPU-PLAN) |
| 1022 shot-scanned | FIX | test tooling (lv:shot) |
| 1023 copy-then-switch | FIX | |
| 1024 push-stats | DIAG | extra line on the RedwoodGPU 5 s stat |
| 1025 splash-clear | FIX | |
| 1026 gpu-600mhz | TRY-FAILED, inactive | "Home stayed at ~8 fps whether ... 300 or 600 MHz"; keep for planned DVFS |
| 1027 fps-paths | DIAG | `sweetfps=1` (in e7 boot-args, so on in tests) |
| 1028 vsync-hz | TRY-FAILED, inactive | `sweetfb_vhz`; memory note: "600 MHz, vhz, lock, arena gave nothing" |
| 1029 surface-arena | TRY-FAILED, inactive | "none by default: measured, hardly used"; 296-line patch |
| 1030 intf1-vsync | TRY-FAILED, inactive | `sweetfb_lock=1` only; same note |
| 1031 fps-gaps | DIAG | `sweetfps` |
| 1032 sampler-timing | DIAG | |
| 1033 cpu-by-process | DIAG | SMC line, sampler default-on |
| 1034 lock-offset | TRY-FAILED, inactive | `sweetfb_lock_us`, only with `sweetfb_lock=1` |

## Touch (3), power (2), storage (1)

| Patch | Class | Evidence / note |
|---|---|---|
| 1003 touch | FIX | polled, not IRQ (PLAN-DRIVERS item 4) |
| 1007 input | FIX | test tooling (lv:tap/swipe) |
| 1010 touch-edge | FIX | |
| 1008 perf | DIAG | 128 MB memcpy measured on *every boot* (+2 s); DDR vote only with `lv_ddr_khz` |
| 1042 wled-backlight | FIX | |
| 1002 emmc | FIX | |

## Modem core (9)

| Patch | Class | Evidence / note |
|---|---|---|
| 1043 modem-fat | FIX | |
| 1044 modem-mba | FIX | |
| 1045 modem-bus-clock | FIX + DIAG | register dump only on a failed start |
| 1046 modem-qdss | FIX | Linux proxy clock; `modem_qdss=N` diag knob |
| 1047 serror-record | WORKAROUND | `lv_serror=1` required with modem=1; SError cause "still unexplained" (MODEM-PLAN) |
| 1048 smem-cached | FIX + DIAG | item lists logged at GLINK start and in every summary |
| 1049 rmtfs-buffer | FIX | |
| 1050 modem-diag | FIX + DIAG | GLINK open acks, 8-deep FAT = fix; unserved-QRTR log, TZ log tail = diag |
| 1075 diag-servers | FIX | the real cause of "Task starvation: diag" |

## Telephony / ABP (19)

| Patch | Class | Evidence / note |
|---|---|---|
| 1036 ipappender | WORKAROUND | stub: "accepts every call, answers zeroes"; tracked as temporary (PLAN-DRIVERS) |
| 1038 baseband-service | WORKAROUND | stub AppleBaseband; tracked as temporary |
| 1057 abp-observe | FIX | base of the stand-in (`abp=1`); logs every call |
| 1059 bb-verbose | DIAG | `abp=1` (on in the working set): first 300 calls per service |
| 1062 bbfw-folder | FIX | unpacks Mav17.Release.bbfw to preboot |
| 1063-1070 | FIX (emul.) | boot stand-in pbl/Sahara/mission, pipes; 1065's DIAG-ping answer unused ("booted WITHOUT a DIAG ping") |
| 1064 qmux-bridge | FIX | |
| 1071 qmux-log | DIAG | **default-on** with abp=1: `qmux_log` default 1500; QMI payloads (IMEI/IMSI) in the USB log |
| 1072 modem-mode | FIX (emul.) | `modem_mode=0` does what an Apple baseband does |
| 1073 abp-reset-survive | FIX | |
| 1074 qmux-log-80 | DIAG | 80 bytes per message, same privacy note |
| 1076 uim-provisioning | FIX (emul.) | |
| 1079 abp-abort-reads | FIX | "built but not yet seen in a reset" |

## Wi-Fi (13)

| Patch | Class | Evidence / note |
|---|---|---|
| 1051 modem-wlfw-off | DIAG | `modem_wlfw=0` bisect switch (still in cc-run.ps1) |
| 1052 wlan-power | FIX | Android votes the same rails; was not the hang cause |
| 1053 wlfw-steps | DIAG | `modem_wlfw=N`, `modem_wlhost=0` bisect |
| 1054 wlan-rails-readback | DIAG | **default-on**: PMIC read before/after every WLFW power-on |
| 1055 wlan-smmu | FIX + DIAG | identity used by wifi=1 (1080); `modem_smmu=1` dump; `modem_smmu_cb` knob |
| 1056 wlan-msa-zero | TRY-FAILED, active | "region zeroed ... - no change"; zeroes 1 MB every boot (`modem_msa0` default 1); pin_connect flag same |
| 1077 wlfw-bdf-after-cap | FIX | the real cap-hang fix |
| 1078 wlfw-bdf-crc | FIX | as ath10k |
| 1080 wlan-addresses | FIX | |
| 1081 wlan-mac-persist | SUPERSEDED, active | "persist has no MAC file"; ext4 reader still runs first (`modem_mac` default 1) |
| 1082 wlan-mac-names | SUPERSEDED + DIAG | lists persist file names every wifi boot |
| 1083 wlan-mac-nv | FIX | NV 4678 (works with 1084) |
| 1084 diag-handshake | FIX | |

## Bluetooth (27)

| Patch | Class | Evidence / note |
|---|---|---|
| 1085 bt-b1 | FIX | `bt=1` |
| 1086 bt-bob-loopback | FIX + DIAG | BOB rail = fix; UART loopback self-test runs every bt start |
| 1087 bt-flow-control | FIX | |
| 1088 bt-firmware | FIX | |
| 1089 bt-diag-no-ibs | DIAG (+FIX) | tag 17 bit 7 clear = fix; 1 s raw "after firmware" dump still runs every start |
| 1090 bt-silent-after-fw | TRY-FAILED, dead path | "Every try (again, IBS wake, no CTS) got nothing"; cause was NVM baud (1092) |
| 1091 bt-nvm-layout | SUPERSEDED, removed | "The per-tag and dump logging of 1091 is dropped" (1092) |
| 1092 bt-nvm-container | FIX | |
| 1093 / 1094 | FIX | address order + DT, uart1 nubs |
| 1095 bt-uart-control | FIX (emul.) | Broadcom VSCs answered in kernel |
| 1096 bt-olyhal | FIX (emul.) | fake vendor-id "Murata" so BlueTool picks the D22 script |
| 1097 bt-packets-trace | FIX + DIAG | packet cutter = fix; byte trace (200 packets each way) |
| 1098 / 1099 | FIX (emul.) | debug-ACL filter, Broadcom version reported |
| 1100 bt-trace-sessions | DIAG | trace restarts at every connect (bluetoothd restarts often: log flood) |
| 1101 bt-erroneous-data | FIX (emul.) | |
| 1102 bt-vendor-return | SUPERSEDED, removed | lines replaced by 1103 |
| 1103 bt-vendor-echo | FIX (emul.) | |
| 1104 chosen-macs | FIX | |
| 1106 bt-rx-stuck | TRY-FAILED, active | forced stale at 5 ms: "FORCE_STALE changed nothing" (1112); stuck-drop + overrun log = diag |
| 1107 bt-stale-imr | TRY-FAILED, active | 1108 run: "still 'packet stuck: have 485 need 486'" |
| 1108 bt-partial-word | TRY-FAILED, active | 1109 run: "the tails are still lost"; matches Linux, may stay with the real fix |
| 1109 bt-fast-poll | TRY-FAILED, active | "whatever the polling speed, so not a race"; 20 us busy-poll 20 ms after traffic (CPU) |
| 1110 bt-stale-log | DIAG | first 60 stale events, every bt start |
| 1111 bt-stuck-regs | DIAG | regs + extra FORCE_STALE at a stuck packet |
| 1112 bt-rxstale-last | TRY-FAILED, active | IPR 31 \| 0x20; did not help either (user) |

## Other (12)

| Patch | Class | Evidence / note |
|---|---|---|
| 1001 usb-log | FIX | debug channel (infrastructure) |
| 1005 keys / 1006 rtc | FIX | RTC write refused by the arbiter (logged) |
| 1035 root-files | FIX | writes the local launchd.plist (see image table) |
| 1037 crash-scan | DIAG | always on for signal 6/5 crash reports (cheap) |
| 1039 no-container-empty | FIX | |
| 1040 scan-killed | DIAG | `sweetscan=NAME` |
| 1041 sandbox-extensions | FIX | consistent with the allow-all Sandbox stub |
| 1058 / 1060 stderr-tap | DIAG | `sweetstderr=NAME` |
| 1061 amfi-dev-vars | DIAG | only for the `sweetstderr` process |
| 1105 mgreset | DIAG | one-shot tool, `lv_mgreset=1` |

## iOS image and boot-args (outside the patches)

| Item | Where | Class | Note |
|---|---|---|---|
| `_PanicOnCrash` -> `_PanicOnCrasX` (7 jobs) | sweet-root-tweaks `launchd()`, kept in local launchd.plist | WORKAROUND | hides crash-loops of containermanagerd, lockdown, trustd, watchdogd ... |
| CommCenter jobs removed | sweet-root-tweaks | SUPERSEDED | put back by local launchd.plist (1035) |
| VirtualAudio.plugin -> `HAL.disabled` | sweet-root-tweaks `audio()` | WORKAROUND | AUDIO-PLAN: undo once an audio device exists |
| `StartRecorderServer=false` (3 MediaToolbox plists) | sweet-root-tweaks | WORKAROUND | reason was "without a GPU"; GPU now works - retest |
| SpringBoard `BKNoWatchdogs`, `FBLaunchWatchdogExceptions` | sweet-root-tweaks prefs | WORKAROUND | watchdog kills off "one slow CPU path" |
| Setup/migration/mini-buddy skipped, no cloud-config UI | sweet-root-tweaks prefs | WORKAROUND (bring-up) | acceptable until activation is solved |
| `BT_HCI_TRANSPORT=H4BC:POSIX:...` on bluetoothd | local launchd.plist | WORKAROUND | avoids the Skywalk control `com.apple.uart.sk.bluetooth` |
| `OS_ACTIVITY_DT_MODE=YES` on CommCenter, CommCenter-noncellular, BlueTool, bluetoothd (+`OS_ACTIVITY_ENABLE_DYNAMIC`) | local launchd.plist | DIAG, always on | log mirroring overhead |
| `wdt=-1 wdt_test=no_user_checkin`, `sweetbattery=0 sweetchg=0`, `sweetfb_stayon=1` | e7 boot-args (base) | WORKAROUND | watchdog off, battery/charger off, display-off ignored |

## Counts (113 kernel patches, primary class)

| Class | Count | Of which |
|---|---|---|
| FIX | 70 | ~14 deliberate emulation (ABP stand-in, BT Broadcom translation); 9 carry a DIAG part |
| DIAG | 24 | ~10 default-on: sampler (1017/1018/1033), 1008 memcpy, 1024, 1054, 1071/1074 (abp=1), 1059, 1110, plus 1004 touch log |
| TRY-FAILED | 12 | active: 1056, 1090 (dead path), 1106-1109, 1112; inactive: 1026, 1028, 1029, 1030, 1034 |
| SUPERSEDED | 4 | code left: 1081, 1082 (+ 1013's cp path); removed: 1091, 1102 |
| WORKAROUND | 3 | 1036, 1038 (tracked stubs), 1047 (SError masking) |
| Image/boot-args | 9 items | 7 WORKAROUND, 1 DIAG, 1 SUPERSEDED |

## New open items (2026-11-27 evening)

- Lock screen flickers after Power (user video 19-59-57: red poster <-> pale picture ~4 times a second):
  AegirPoster (the Photos poster extension) aborts on an uncaught exception thrown in a FrontBoardServices
  serial-queue block, again and again (pw1: 6 crashes), each relaunch swapping poster/placeholder. The
  first project answered PLPrivacy "allowed" in topaz-inject (assetsd/AegirPoster, ad84f5d) because tccd
  did not see the private TCC entitlement (our AMFI stand-in) - a workaround; the cause to fix is the
  entitlement. Exception text: sweetscan=AegirPoster (not caught yet: it starts after mediaanalysisd).
- webbookmarksd crash loop (6 in 7 min, run lg1): uncaught exception in an XPC async reply handler
  (objc_terminate <- _dispatch_client_callout3 <- mach_msg_async_reply). Next: sweetscan=webbookmarksd.
  Run ph1 (sweetscan=webbookmarksd, idle 3 min): no crash - it comes with some UI action.
- 2026-11-28 (run ad1, userland 46094073971): lock screen after Power - first picture right
  (screenshots/ui_ad1_lock1.png); once the "swipe up to open" label fades, the bottom ~280 rows are
  redrawn in a flat band of the wrong shade, with a step at the camera button's left edge
  (ui_ad1_lock2.png): a partial redraw (CA's damage) drawn wrong, likely the same as the item below.
  No AegirPoster or webbookmarksd crash in that run (Safari opened, lock/unlock); widget and poster
  extensions still die of "extension check-in timeout" at boot (ScreenTimeWidget, PhotosReliveWidget,
  LockScreenPeople).
- Bottom-of-screen flicker: a stale picture of the search keyboard in App Library frames (user video);
  also Settings overscroll and the switcher. preserve copies are right (pl1), source unknown.
- App switcher: left cards purple (not glzero). Injected swipes do not open the switcher even with
  xnu 1159 lv:swipe HOLD (ph1): the user's finger needed for checks.
- (was) App switcher: left cards purple (not glzero). 2 preserve copies into never-shown display-sized
  targets (2->95, 2->109) - check whether these are the cards' snapshots.
- BT headset: bluetoothd crashes in the A2DP Skywalk pipe (BT-PLAN).

## Clean up first

1. **Bluetooth RX try stack** 1106 (forced stale), 1107 (IMR RXSTALE), 1109 (20 us poll), 1112 (IPR
   RXSTALE_LAST), 1090 (IBS/no-CTS tries), 1089's 1 s dump: none fixed the lost tail. Revert to the 1105
   receive path, keep 1108 only if the real fix needs it, keep 1110/1111 behind a `bt_diag=` boot-arg.
   1109's busy-poll works against the 1-2 % idle goal.
2. **Wi-Fi leftovers**: 1056 MSA zeroing ("no change", every boot), 1081/1082 persist ext4 reader
   (no MAC file there; NV 4678 is the source), 1054 rails readback on by default.
3. **Default-on logs**: `qmux_log` default 1500 (QMI identifiers in the log), 1059, 1100, touch
   report log, 1008 boot memcpy, sampler: make them opt-in boot-args.
4. **iOS image workarounds**: retest `StartRecorderServer` (GPU exists now), restore `_PanicOnCrash`
   and SpringBoard watchdogs once the crash-loops are gone, `VirtualAudio.plugin` with audio,
   `BT_HCI_TRANSPORT` once the Skywalk control exists; move `OS_ACTIVITY_DT_MODE` to test runs only.
5. **Inactive GPU/display tries**: 1029 arena (296 lines), 1028/1030/1034 vsync knobs, 1013
   `lavender_gpu_cp()` and lv_gpu stages 1-6/9: remove or fold into one diag file; keep 1026 for DVFS.
   Also track 1047 (`lv_serror=1`): find the SError source instead of recording it.

## Cleanup done

- **1138** (mk_cleanup1.py; runs c1138/h1139: Wi-Fi MAC from NV, modem, BT, audio up): 1056 MSA zeroing and the 1081/1082 persist
  ext4 reader removed; opt-in now: `modem_wlrails=1` (1054 rails readback), `qmux_log=N` (default 0),
  `abp_log=1` (1059 call log; `abp=1` keeps the power hook), `sweettouchdiag=N` (default 0),
  `lv_ddr_bench=1` (1008 memcpy; also with `lv_ddr_khz`), `sweetsample=NAMES` (sampler off without it).
  BT RX tries were already cleaned in 1114.

## No-result log (kept up to date, newest last)

Every patch that did not bring the result it was made for, with what became of it. Rule: once the
real fix is found, such patches are taken out (or put behind a boot-arg) in a cleanup patch.

| Patch | Area | Meant to | Result | Now |
|---|---|---|---|---|
| 1026, 1028, 1029, 1030, 1034 | GPU | 600 MHz / vsync / surface arena tries | no gain | off unless boot-arg; 1026 kept for DVFS |
| 1056 | Wi-Fi | zero the MSA region before WLAN firmware | no change | removed in 1138 |
| 1081, 1082 | Wi-Fi | MAC from persist file | file absent (MAC comes from NV 4678, 1083) | removed in 1138 (persist no longer read) |
| 1089 | BT | 1 s raw dump after firmware | diagnostic only | removed in 1114 |
| 1090 | BT | HCI_Reset retries (again / IBS 0xFD / no CTS) | not needed after NVM fix 1092 | removed in 1114 |
| 1091 | BT | NVM layout log | diagnostic only | removed (1092) |
| 1102 | BT | vendor answers + 8 zero bytes | broke 0xFCE9 | replaced by 1103/1115 |
| 1106 | BT | FORCE_STALE after 5 ms idle, stuck-packet drop | no effect (drop kept as guard) | FORCE_STALE removed in 1114 |
| 1107 | BT | IMR RXSTALE | no effect alone | kept (as Linux msm_serial) |
| 1108 | BT | partial word read by count at stale | no effect alone | kept (part of the working path) |
| 1109 | BT | 20 us polling after traffic | no effect, CPU cost | removed in 1114 |
| 1110, 1111 | BT | stale / register logs | diagnostic only (found the cause) | removed in 1114 |
| 1112 | BT | IPR RXSTALE_LAST | no effect alone; real fix was 1113 | kept (as Linux msm_serial; not proven needed) |
| 1116 (SPMI part) | audio | read PM660L codec ids at SID 3 over the SPMI observer | hung the system | behind audio_spmi=1 (1117) |
| 1126 (SMMU part) | audio | LPASS SMMU S2CR bypass for SID 1 | hypervisor turned it into fault (0x20000); first ADSP buffer access hung the phone | replaced by a context bank with M=0 (1127) |
| 1130 | audio | clean tone buffers from CPU cache (dc civac) | SD0 still low in that run; data seen in a later run (t6) - cache not proven the cause | kept (needed for DMA anyway) |
| boot-arg glgmem=1 | GPU | GMEM tiling instead of sysmem for fps (run fgmem, 1139) | screen flickered on the side swipe (user) | rejected: picture quality |
| 1124-1129 (amp part) | audio | mainline MAX98927 init/enable (0x3A, 0xFF) | chip is a MAX98937: wrong map, GLOBAL_EN never held | replaced by the MAX98937 table in 1133 |
| 1147 | GPU/CPU | `lv_kmsg_sig=0`: no SHA-256 kmsg signatures (first project 1035) | backboardd 17.8-18.7 ms CPU a frame either way (cpuframe ks0b/ks0c vs ks1b/ks1c) | default on; remove in the next cleanup |
| userland -O2 | GPU/CPU | eagl.c built -O2 instead of -O1 | GPU hangs, wrong textures, UI stalls (st1, gs0, ka, nz1, pf3, pf6) | reverted to -O1 |
| patch_solid.py, patch_imageof.py | GPU/CPU | glsolid (first project) and an image_of index | no change in backboardd ms a frame | removed (userland 45999741177) |
| 1157 | display | sweetfb_gpucopy=1: GPU frames copied by the CPU into our flip buffer (test of "iOS draws into the scanned buffer") | the copy from write-combined GPU memory is far too slow: frames stalled, black screen (gc1) | test inconclusive; remove in the next cleanup |
| glenv=FD_MESA_DEBUG=sysmem,ttile | GPU | tiled textures in Mesa to cut texture reads (run x1, 2026-11-28) | picture broken (user), texture misses 34 % against 23-25 % | rejected: picture quality |
| glpreserve=2 (patch_damage.py) | GPU | copy only the box the other display surface lacks | first version: no gain, orange/pink bands on the home screen (user video 23-56-56) | opt-in only; to remove or redo |
| glinuse=MS (patch_damage.py) | display | wait until the panel lets the display surface go | cured the tremble, Settings 50 -> 33 fps | superseded by scanout surfaces (xnu 1167, patch_scanout.py) |
| patch_swaphook.py | GPU | copy a display frame out once, at CA's swap: libtopaz-inject interposes IOMobileFramebufferSwapBegin (userland 46084039497, bench aa1a) | the hook never ran (0 put off, no log line): dyld interposing does not reach calls between shared-cache libraries; Settings 43 fps against 50.5 | removed; replaced by patch_flushwho.py (glwho / glskip by call site) |
| patch_bbdfull.py | display | CA_DISABLE_DIRTY_REGIONS=1 for backboardd (stale keyboard band at the bottom of the App Library, user video 18-58-15) | draws a frame unchanged (26.1 -> 27.0): the variable does not change how CA renders here | removed |
| patch_scandamage.py | GPU | copy into a scanout surface only the boxes CA drew since its last frame (userland 46108278919, run ag1) | 100 % copied in every second: CA draws 143 of 159 frames with the scissor off over the whole surface (run ag2) | removed; the scissor-off copy kept in patch_canvas.py |

## New open items (2026-11-27 night: cores and clocks, docs/HARDWARE.md "CPU clocks, voltages, sensors")

- **Gold runs 2208 MHz at the boot voltage (868 mV); stock would use 948 mV open loop for this chip.**
  Either raise the rail (which of PM660 S2/S3 is Gold, SPMI write ownership, APM threshold 872 mV and
  mem-acc level 3 for the top corner must be handled) or run what 868 mV carries by the stock table
  (1747 MHz, L 91: Settings -4..-6 %, home unchanged). `lv_gold_l=91` does the second today.
- **GPU clock is the fps limit** and 600 MHz hangs: the rail vote does not raise PM660L S3. Fix the rail
  first (read it back with LVPMIC), then 465/588/600 MHz, then DVFS ([[redmi-gpu-dvfs-planned]]).
- `gpu_mhz` (TopazAdreno, cosmetic on lavender) and `lv_gpu_mhz` (TopazRpm, the real one) are two names
  for one thing: make them one.
- No thermal control at all (stock: core limit 70 C, hotplug 105 C). With `lv_gold_set_l` a simple
  step-down above a limit is now possible.
- Battery: SweetBattery reports a static 100 % (topaz fuel-gauge addresses); the PM660 gauge is readable
  (0x41A0 V, 0x41A2 I). Under load on a PC port the battery drains (input limit 500 mA).
- backboardd / SpringBoard CPU does not scale with the core clock: profile the App Library scroll.
- (late night, corrects the two items above) GPU 600 MHz works with `lv_gpu_mhz=600`; the hangs were
  `gpu_mhz=600`. fps follow neither the CPU nor the GPU clock: find the common limit (memory, waits).
- Gold voltage, how stock does it (first-project/ref clk-cpu-osm.c, cprh-kbss-regulator.c, sdm660 dtsi):
  the rail is PM660 S2 (FT) + S3 (HF), S1 is Silver; their SPMI channels (53, 66, 27) belong to the
  application CPU, so we can write them; CPRh/OSM hardware does it in stock and is not reachable from
  EL1. Above 872 mV the array power mux must go from MX to APC first: mode register 0x179d0010 = 2,
  status 0x179d0018 & 0x1f == 3 (Silver: 0x179d0004 / 0x179d000c). Not done yet: set 872 mV, switch the
  APM, set 948 mV, then L 115 - with a temperature limit, since heat grows.
