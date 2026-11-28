# GPU plan: Adreno 512 (a5xx) on lavender, after ios-topaz's Adreno 610 path

Base path (ios-topaz e4772911, patches 0900-0950): TopazAdreno.cpp (power, zap, SMMU, CP, ring;
polled fences) + RedwoodGPU.cpp (msm-DRM-like ioctls over IOConnect) in the kernel; userland
Mesa 25.0.7 freedreno + OSMesa (redwood-drm instead of libdrm), libtopaz-gl (eagl.c: EAGLContext
for CoreAnimation), injected into backboardd (bbd_wrap / kern.exec_inject). Boot-arg `gpu=1`.
The base builds the userland **locally on a Mac** — there is no workflow; we need our own CI job.

## What changes for A512
| | A610 (base) | A512 (lavender) | mainline reference |
|---|---|---|---|
| GPU / GPUCC / SMMU / GCC | 0x05900000 / 0x05990000 / 0x059A0000 / 0x01400000 | 0x05000000 / 0x05065000 / 0x05040000 / 0x00100000 | gpucc-sdm660.c, gcc-sdm660.c |
| GDSCs | CX 0x106c, GX 0x100c, GMU clocks | CX 0x1004, GX 0x1094, no GMU | gpucc-sdm660.c |
| gfx3d | RCG 0x101c, branch 0x1054 | RCG 0x1070 (GPLL0 src 5), branch 0x1098 | gpucc-sdm660.c |
| CP microcode | one SQE (a630_sqe) | PM4 + PFP (a530_pm4.fw, a530_pfp.fw) | a5xx_ucode_load, a5xx_hw_init, a5xx_me_init |
| HW init | a612_hwcg, a6xx UCHE | a5xx_hw_init (VBIF, UCHE, GMEM, protect), a512_hwcg | a5xx_gpu.c |
| zap | PAS 13, region 0x55B15000 | PAS 13, lavender region from DT, a512_zap.mdt/.bNN (device-signed) | a5xx_zap_shader_init |
| ids for Mesa | 610 / 0x06010001 / GMEM 0x21000 | 512 / 0x05010200 / 0x44000 | a5xx catalog |
| userland | framebuffer fetch on | `glfetch=0` (fd5 has no FBFETCH) | — |

## Steps (each with a kernel-log signal)
1. Addresses + power (GCC branches, CX/GX GDSC, gfx3d from GPLL0) → GDSC on, RBBM_STATUS sane.
   **Done 2026-11-25** (patch 1009, lv_gpu=7): needs the GX rail voted over RPM (smpb3 vlvl) and the
   gfx LDO head switch (BHS, 0x506e01c) on and unclamped, else unclamping GX stops the display + touch.
   GX PWR_ON shows only after the unclamp. RBBM_STATUS 0x1, always-on counting, scratch r/w ok.
2. Chip id → 0x05010200 (from DT qcom,chipid; a5xx has no id register).
3. Zap (PAS 13) → init_image / mem_setup / auth_reset = 0.
   **Done 2026-11-25** (patch 1011, lv_gpu=8): firmware travels in the payload's ramdisk slot
   (tools/mkpayload.py --fw, never in the repo), with a zeroed 64 KB zone handed to mem_setup.
4. SMMU pass-through (gpu_identity=1) → GFSR 0.
   **Done 2026-11-25** (patch 1012, lv_gpu=10): SMR0 = SID 0 exactly, S2CR0 -> CB0, CB0 M off.
   The SMMU global space is emulated by the hypervisor: only plain asm ldr/str work (compiler
   ldp/writeback accesses hang), only entries below NUMSMRG (3), no attach-impl-defs.
5. PM4/PFP, a5xx_hw_init, ring, ME_INIT → "CP up".
6. Self-test CACHE_FLUSH_TS → fence value in memory.
   **Steps 5-6 done 2026-11-25** (patch 1013, lv_gpu=11): A512 a5xx_hw_init, PM4/PFP + ring in low RAM
   (0x95400000), ME_INIT, SET_SECURE_MODE 0, PKT4 scratch write and CACHE_FLUSH_TS fence all complete.
7. Ids 512 / 0x05010200 / 0x44000 → RedwoodGPU published.
   **Done 2026-11-25** (patch 1014, gpu=1): TopazAdreno's hardware layer on the A512, GPU pool moved to
   0xA1000000 (free low RAM), empty-submission fence self-test done; UI fps unchanged (4.5 / 13.0).
8. Userland CI (macOS runner: Mesa freedreno + OSMesa, redwood-drm, libtopaz-gl, inject) → into the root → UI drawn by the GPU, bench.
   **Works 2026-11-25** (patches 1016-1019, gpu=1 glfetch=0): unlocks, Settings 28.6 fps (CPU: 13.0),
   home 7.3. The stall was memory: released IOSurface views kept as zombies (256 per client) held
   their whole pixel buffers, 1.2 GB wired of 1.95 GB (CollectionsPoster 914 MB, PosterBoard 300+),
   so the UI paged code in from disk, throttled. 1019 keeps only the state page: wired 1700 -> 219 MB.
   Open: scrolling shows stale rows (CA draws only damage; first project's glpreserve), home 7 fps.
   Display (2026-11-25): 1020 MDP shows GPU pool frames directly (frame ~11 ms after the tick, was
   ~900 ms: CPU copy into the splash, seen as a slow top-to-bottom wipe); 1021 QSEED3 scales
   1125x2436 to 1080x2340. **Scaling is NOT final (user, 2026-11-25): try other variants later** -
   e.g. 750x1624 @2x upscaled (first project 1028), 828x1792 (1031), native panel size, other
   QSEED3 filters/preload; pick by sharpness and fps.
   Earlier note - **Partial 2026-11-25**: GL draws the lock screen (FD512), but no unlock, frames 0.5-1.5 s late,
   then a hang. Plan (from a review of the user's first project, ios-lavender patches 1018-1036 and
   userland commits; each port asked for first):
   a. **Pool descriptors as sub-ranges of the chunk's** (first project 1021, ~30 lines, TopazAdreno.cpp).
      Our tree still makes a descriptor of its own per buffer; its last unmap destroys the device
      pager and backboardd's render thread waits in vm_object_destroy for good - their "lock-screen
      freeze" a minute or two after boot. Test: gpu=1 glfetch=0, unlock + bench.
   b. GPU hang report + recovery (1036) - if a. is not all of it.
   c. Userland defaults: FD_MESA_DEBUG=sysmem (home 36->45 fps there), glorder=2, glsolid, glzero,
      cheaper surface_changed (was 15% of backboardd).
   d. Surface arena (1018/1019): the GPU reads app/SpringBoard surfaces in place, no 11 MB copy.
   e. Threaded Mesa context + its three freedreno fixes (c60e82a, dc161c9, 93d9897, 1c88839).
   f. Picture correctness: framebuffer-fetch emulation, blur fixes (glsync, glpreserve, ds8).
   g. Later: 750x1624 scaled scanout (1028/1029), vsync rate (1033), ipc speed (1035).
9. Later: SMMU translation, interrupts, GPU clock 600+ MHz (GX voltage vote), render straight into display surfaces.

## GPU hang (xnu 1139, 2026-11-27)

- Seen in 11 logs: "TopazGPU: no answer", RBBM_STATUS 0x8..001c1 / 0xc50801c3 (HI, RAS, RB, PC_DCALL
  busy: a draw that never ends), CP_HW_FAULT 0, SMMU no fault; afterwards every submit failed with -60
  (ETIMEDOUT, ring full): black or frozen screen, power key dead (run c1138: hang at fence 13, lock screen).
- 1139: full dump at a hang (IB2, STATUS3, scratch, ring at rptr, IB1/IB2 dwords; gpu_hangdump=0 off) and
  recovery as Linux a5xx_recover (RBBM_SW_RESET_CMD 0x43, CP restarted, fences written done; gpu_recover=0
  off, at most 20 a boot). Run h1139r1: hang at fence 2918 inside an IB2 of 2782 dwords (rem 2094,
  CP done fetching IB1) -> "recovery done", UI went on (33 fps, 465 submissions / 5 s), home screen fine.
- Open: the cause (a draw in backboardd's IB2; decode the IB2 from the dump), RBBM_STATUS after the reset
  still 0xc00003c1.

## Hang hunt and fps levers (2026-11-27, kernels 1140-1141, userland 45927392351)

| Run | Change | Home fps | Settings fps | Hang |
|---|---|---|---|---|
| h1139, h1139r1 | base (300 MHz, sysmem) | 10-11 | 37-43 | 1 of 2 |
| f600 | gpu 600 MHz | 11.2 | 45.4 | yes |
| fgmem / f600g | glgmem=1 (tiles) | 19.6 / 22.7 | - / 25.7 | yes; side-swipe flicker (user): rejected |
| cg1-cg3 | gpu_hwcg=0 (1140) | 9.6-28.6 | 40-45.6 | none in 3 |
| u1, u2 | + userland blur/colour fixes, MADVISE, LTO | 24.6 / 8.8 | 49.3 / 47.2 | none |
| r1 | + lv_rpm_scale=1 lv_ddr_khz=1804800 (1141) | 14.3 | 51.8 | none; memcpy 2050 -> 2524 MB/s |

- gpu_hwcg=0 (all GPU block clocks on): 6 boots in a row without a hang (before: about one a boot). Next: find
  the block whose gating hangs (bisect the a512_hwcg table) so gating can stay on elsewhere.
- Home fps varies a lot between runs (8.8-28.6) with the same setup: the bench's home phase is not stable.
- Userland (first project ea74d71/e157d39/877dd11): dock and search pill correct again (were white/yellow).
- Settings shot during scrolling shows doubled text; lv:shot mixes frames in motion, static shots are clean.

## Kernel CPU, App Library (2026-11-27, kernels 1142-1145)

- 1142/1144: `sweetsample=kernel_task` prints SMT lines (CPU ms of each kernel thread per round, name, stack);
  our driver threads are named after their functions.
- 1143 (`sweetfb_latch_sleep`, default 1): the presenter slept 100 us at a time for the MDP latch (~16% of a
  core while drawing); now it sleeps until ~200 us before the panel frame ends (INTF_1 line counter; panel
  frame measured from its frame counter: ~6.8 ms, 148 Hz). Presenter out of the top list.
- 1145 (`sweettouch_edge`, default 1): the NT36672A event line rests low and pulses high, so touch read 65
  bytes of bit-banged I2C every 12 ms forever (11% idle, 26% touched). TLMM now latches the rising edge
  (INTR_CFG 0x76, no GIC); read on edge, finger down, or every 250 ms. Idle kernel_task 14% -> 6%
  of a core, touch_thread 2%. Real fingers not yet checked by the user (injected taps bypass the chip).
- Home phase of the bench now swipes into the App Library (Suggestions filled): 13-16 fps on every kernel
  incl. 1143 again (l2) - phone state, not a regression. backboardd frames there take 2-5 ms; GPU 600 MHz
  (m1: 14.5-16), lower DDR (d1b: 13.3) and GMEM (g1: 9.0, Settings 33) do not move it. The limit is
  upstream of the GPU (CA commits); SpringBoard stacks need a symbolicated shared cache (not set up).
- glgmem=1 measured again: slower (home 9, Settings 33-34) - rejected on speed as well.
- Lower DDR (1017600): Settings 58 -> 38-44, so Settings is memory-bound; keep 1804800.
- 1146 (`modem_idle_ms`, default 8): the modem watch loop sleeps 8 ms after 500 ms without glink traffic
  (from 30 s on); modem thread 80 -> 25 ms per 6 s. Modem, Wi-Fi, LTE bars came up as before.
- Static home with the cellular "searching" bars animating: backboardd draws 60 fps (51% of a core).
- 1148/1149 `sweetprof=NAME`: IPI sampling profiler (live pc of the target's running threads, user and
  kernel), report by image. `tools/cpuframe.ps1` = Settings scrolling, backboardd CPU per frame.
  backboardd while scrolling Settings: ~18 ms CPU a frame (80-97% of one core) - CPU-bound. User samples:
  libOSMesa 39%, QuartzCore 33%, libtopaz-gl 9% (surface_changed 3.3%, image_of walk ~2%), Espresso?
  9% (attribution doubtful), dnssd+corecrypto 5%. Next: Mesa offsets with the mesa-symbols artifact;
  QuartzCore needs the dyld shared cache symbols.
- First project's backboardd findings, checked against this base: async flush (OSMesaFlushSync at frame
  end), SubImage refill, glorder=2-style ordering, sampled surface_changed, MADVISE, LTO: already here.
  Ported now: glsolid (patch_solid.py, one-colour full-viewport quads skipped or cleared, +27% home fps
  there), image_of index, eagl -O2. Not taken: lower render size (picture quality). Raw first-project
  profiles: C:\Users\Vasyl\Desktop\Claude\Projects\Android-iOS\dump\ (glprof*.txt, prof-*.txt).
- Kernel part of backboardd samples (1149): mostly at ml_set_interrupts_enabled (the IPI lands when
  interrupts come back on: time with interrupts off, caller unknown); next: kernel lr in the report.
- Shared-cache symbols: WSL has /root/ipsw/systemos.dmg (apfs-fuse -> /mnt/systemos), the dyld cache
  copied to /root/dsc, `ipsw` in /usr/local/bin; `ipsw dyld symaddr ... --image X` dumps, tools/dscsym.py
  names the profiler's pieces (slide = run-time image base - cache __TEXT address).
- backboardd while scrolling Settings (pf5/pf6, symbols): QuartzCore 34% = CA's layer-tree update
  (HitTestTree::append_layer_node, Updater::prepare_layer0/layer_node, LayerNode alloc/delete); Mesa 37%
  flat (fd_submit_append_bo, _mesa_use_program, state validation); malloc/free 8.5% ("Espresso" in 1149's
  report = libsystem_malloc), memcmp/memset 2.8% ("dnssd"), pthread_mutex 2.2% ("corecrypto"); eagl 9%.
- patch_bbdnano.py: the wrapper's execv lost launchd's nano-allocator spawn flag (xnu adds
  MallocNanoZone=1 only for posix_spawn with attributes); now set in the environment (bbdnano=0: off).
  nanov2_malloc in use; backboardd 18.1-19.4 -> 17.0-17.8 ms CPU a frame, fps 53/43 -> 55/51 (nz2).
- glsolid, image_of index, eagl -O2 (userland 45984996010): no measurable change in ms a frame (pf5);
  screenshots pixel-identical (dock max diff 1 level).
- Hangs: 3 boots with sweetprof= (pf3, nz1, pf6) hung or lost lv:shot later; without it (nz2) stable.
  sweetprof stays diagnostic only (opt-in); cause not found (last lines: failed contiguous scans + zone_gc,
  which also show in good runs).
- Red corner (user photos 2026-11-27): a red square with a white quarter circle at the panel's top-left,
  on the boot logo and on a hung screen. Not in iOS's frames (no red there in any lv:shot); so it is in the
  buffer VIG0 shows when no iOS frame is (console shadow / splash). Not drawn by the shim (text only) nor by
  our patches (no such colour); next: dump that buffer's corner, check ABL's layer mixer / border colour.
- Bisect of today's GPU hangs, wrong textures (Photos icon drawn as Phone) and stalls: eagl built -O2
  (userland 45980620775..45988478727). Kernel 1147 + old userland: stable; -O1 + nano (+/-): stable,
  4 benches each, 0 hangs (o1, o1n, o1k). eagl stays -O1 (undefined behaviour somewhere in eagl.c).
- Known-good now: kernel run-45979058523 (to 1149), userland 45999741177 (nano malloc in the backboardd
  wrapper; glsolid and image_of removed: no gain), boot-args as before. Bench cl/clb/clc: home 27.3-27.8,
  Settings 51-57, 0 GPU hangs; screenshots clean. sweetprof's "hangs" were all on -O2 userland.
- Bench (tools/bench.py) now drags slowly like a finger by default (2 s drags, first project's bench.sh);
  --fast = the old flicks. lv:swipe steps every 8 ms (xnu 1151, lv_swipe_ms). Slow-drag numbers (g0b-d,
  kernel 1151, userland 46003048295 with glzero=0): home 13.4-13.9, Settings 51.6-53.2, 0 hangs.
- xnu 1150 (sweettouch_down_ms=1, sweettouch_down_max=30): with a finger down, touch reads each report
  when its edge comes (was every 8 ms on its own clock: uneven steps, judder with a slow real finger).
- glzero (patch_zero.py, first project 125fe46): 2 GPU hangs then a stall in the first boot (z1); with
  glzero=0 stable. Off until reworked (the shade still flickers).
- Touch was the finger judder (2026-11-27): one report read took ~53 ms (delay() in the bit-banged I2C
  blocked for tens of us per wait) -> ~17 reports/s. 1153 spins the waits (4.2 ms a read), 1154 reads
  32 bytes (fingers 1-5) + sweettouch_half_us, 1155 half_us 1 by default: 1.3 ms a read, a report every
  8.3 ms, 0 bus errors in 1745 reads. User: Settings scroll by finger without judder or tearing (sw0).
- glzero v2 (zeros uploaded instead of a framebuffer clear): no hangs (tt1, zk); with glzero=0 the home
  screen flashes black (user, sw0) - keep glzero on. The switcher had flickered on the build without
  it; with v2 no flicker (user).
- Open: app switcher's cards on the left (Phone) are purple, also with glzero=0 (ui_sw0_6_shot);
  the first rows tear for a frame or two when a scroll starts (user saw it on the panel with the bench's
  drag; not caught by lv:shot); home background black for a while after boot until a few lock/unlock.
- Settings scrolling artefacts found from the user's videos (2026-11-27) and lv:shot during momentum /
  overscroll jerks: (1) stale bands of old rows = glpreserve's copy of the last frame (2/8 shots; 0/16
  off) -> patch_nopreserve.py, off by default (glpreserve=1: on); (2) reused cells with stale or
  half-new pictures ("Код допуску" icon a red striped grid, label a grey smear, 3/8 shots) = the
  sampled surface sum missed redraws -> patch_sumfull.py, full sum by default (glsumfull=0: sample);
  0/12 and 0/8 shots after. Userland 46017997725 (nd1): Settings 55.9-57.2 fps slow drag, 0 hangs.
  tools/ghost.ps1: Settings short drags with shots.
- CORRECTION (same evening): lv:shot sent the scanned buffer over ~0.5 s while CoreAnimation reused it,
  so shots in motion mixed frames; the "stale bands" that turned glpreserve off were that. 1156 makes
  lv:shot wait (presenter frozen until sent; lv_shot_freeze=0: old) - but frozen frames also upset CA's
  buffer cycle, so shots during a freeze still showed doubled rows while the user saw none by eye.
  Judge motion artefacts by eye/video. User (sm1: kernel 1156, userland 46025789290, glpreserve=1):
  Settings scrolling by finger fine without screenshots. glpreserve is ON by default again
  (patch_nopreserve.py removed). patch_sumfull.py now: full sum below 1 MB (glsummb), sample above -
  the whole-surface sum made the home screen judder (wallpaper-sized surfaces).
- App Library pulled down (user video 18-58-15): when the search keyboard slides away, some frames keep
  an old picture of the keyboard at the bottom (the bottom flicker; also Settings overscroll, switcher).
  CA_DISABLE_DIRTY_REGIONS=1 for backboardd: no change in draws a frame (removed). glpreservelog +
  lv_swaplog (xnu 1158, userland 46040112491; run pl1): 161 of 163 preserve copies go between the two
  swapped display surfaces (2<->4), 2 copy the frame into display-sized offscreen targets never shown
  (2->95, 2->109: snapshots? the switcher's purple cards?). Open: the stale keyboard band itself.
- GPU hangs again on 2026-11-27 evening, now sometimes NOT recovered ("recovery FAILED: RBBM_STATUS
  c00003c1 rptr 0 wptr 9", rb1; ag1 hung at fence 98 with STATUS3 0x00500000): black screen with the
  backlight on until reboot. Seen with userland 46025789290 / 46040112491; 46027949301 + xnu 1159 gave
  4 clean benches (rb2) - known-good for now. Next: a stronger recovery (GPU power cycle when the soft
  reset does not get the CP going) and the hang's cause (still open since 1139).
- Metrics (xnu 1160/1161, 2026-11-27 night, kernel run-46053107226 + userland 46027949301): a line a second
  with every core's load, the load average, the Gold clock, core/GPU temperatures, **GPU busy share**
  (RBBM_PERFCTR_RBBM_0, countable 6), submissions, recoveries, memory, battery V/I (LVM), CPU by process
  (LVP), measured core clocks (LVK); tools/metrics.py (table, CSV), bench line with a summary per phase,
  tools/lvcmd.py for `lv:peek` / `lv:pmic` / `lv:gold`. What they show (runs m1, m4a, m4L91/73/115):

  | Gold clock | home (App Library) | Settings slow drag |
  |---|---|---|
  | 2208 MHz | 13.5-14.2 fps, GPU 94-99 %, CPU 234-256 % | 50.8-52.4 fps, GPU 71-76 %, CPU 219-259 % |
  | 1747 MHz | 13.9 fps, GPU 97 % | 49.3 fps, GPU 73 % |
  | 1401 MHz | 14.0 fps, GPU 97 %, CPU 250 % | 47.3 fps, GPU 69 % |

  - **The GPU (300 MHz) is the limit**: the home phase does not move with the CPU clock at all, Settings
    loses 8 % for 37 % less clock. In Settings the GPU works 13.8 ms a frame (71 % at 51.6 fps): no room
    for 60 at 300 MHz. Home: the GPU is busy all the time and each frame waits 55 ms for it.
  - CPU use does not follow the clock either: backboardd 110-138 %, SpringBoard 88 % (home) at any of the
    three clocks. Its work is not bound by the core clock (memory traffic or waiting busily) - to profile
    (sweetprof) in the App Library.
  - Heat 55-62 C in the bench, 42-47 C idle; battery +450..530 mA out under load, -100 mA idle.
  - 600 MHz for the GPU does not work now: `lv_gpu_mhz=600` votes rail level 0x180 (acked) but PM660L S3
    stays 848 mV (LVPMIC), the GPU hung at fence 22 and the second recovery failed (m3). `gpu_mhz=600`
    alone (TopazAdreno) only changes the reported MAX_FREQ on lavender, not the clock - and that boot
    (m2, real 300 MHz) had 14 hangs + backboardd SIGSEGV after each, while boots without it had 0 hangs in
    6 benches. To check: what user space does with MAX_FREQ, and how the stock rail (CX level per gfx
    corner: 0x100 for 588 MHz, 0x140 for 647) really gets raised.
- CORRECTION (2026-11-27, late night, xnu 1162, runs n1-n3): the GPU clock is **not** the limit either, and
  600 MHz does not lack voltage.
  - 600 MHz set live (`lv:poke 5066074 501`, `lv:poke 5066070 3`) or at boot with `lv_gpu_mhz=600` alone:
    0 hangs in 4 benches, no artefacts, CX (PM660L S3) 852-856 mV as at 300 MHz. fps do not move:
    home 15.6-16.8 (15.2 at 300), Settings 49.4-50.1 (50.3 at 300).
  - The hangs of m2 / m3 came with `gpu_mhz=600` (TopazAdreno: on lavender it only changes the MAX_FREQ
    reported to user space): 2 boots with it hung, 3 without it did not. Do not pass it; why user space
    hangs on it is open.
  - So neither the Gold clock (1401..2208 MHz) nor the GPU clock (300 / 600 MHz) moves fps: what limits
    is something that scales with neither - memory traffic or fixed waits in the frame pipeline. The LVM
    GPU share is computed with the 300 MHz the driver believes (capped at 100 %): at 600 MHz it reads
    double; to fix (read the gfx3d RCG).
  - RPM requests on the rails from the host (`lv:rpm rwcx 0 vlvl N`, also rwmx, swen, vfl; stock: CX is
    resource "rwcx" 0, not smpb3): all acked, PM660L S3 / S5 read the same right after each, but after
    the series (it included a vote DOWN to level 64) the GPU stopped and the scanned buffer was garbage
    (user photos, screenshot ui_garb). Never vote a rail down from the host; which request did it is not
    known (no log was kept). TWRP 3.7.0 for lavender does not start on this phone (black screen), so the
    Android side is read from the stock kernel sources (first-project/ref).
  - Gold: 1747 MHz (L 91) is now the default, in the shim and the kernel (`lv_gold_l=115` gives 2208
    back). Bench at 1747: home 15.2, Settings 50.3, 0 hangs (n2a).
- xnu 1163 (kernel run-46064163663, runs p1a/p1b): one lock for the PMIC bus - the metrics' fuel-gauge
  reads collided with the keys thread's reads (2-6 key events nobody pressed per bench since 1160: the
  volume slider twitched, user; 0 before 1160, 0 again now). The LVM GPU share now uses the real clock:

  | GPU clock | home | Settings |
  |---|---|---|
  | 300 MHz | 14.8 fps, GPU busy 94 % | 50.3 fps, busy 74 % |
  | 600 MHz | 15.9 fps, GPU busy 96 % | 49.7 fps, busy 65 % |

  Twice the core clock and the GPU is busy for the same share of the time: its time goes into memory,
  not into its own logic (sysmem rendering: every blend reads and writes DRAM; glgmem=1 gave home
  19.6-22.7 against 11 before it was rejected for flicker). The lever for the home screen is the
  memory path (tiled rendering without the flicker, bus/DDR), not the GPU or CPU clock. 300 MHz stays
  the default (less heat for the same fps).
- xnu 1164 (LVG line: the GPU's own counters) and 1165 (thermal guard), kernel run-46068017640. Baseline
  to compare every later optimisation with (user, 2026-11-27; bench q1a, Gold 1747 MHz, GPU 300 MHz;
  the bench line now carries Mpx/frame, mem wait, tex miss):

  | per frame | home (App Library), 14.1 fps | Settings slow drag, 51.7 fps |
  |---|---|---|
  | pixels passed by the render backend | **55.1 M** (20 screens of 2.74 M) | **20.0 M** (7.3 screens) |
  | texture cache line requests / misses | 30.1 M / 6.9 M (23 %) | 3.5 M / 0.88 M (25 %) |
  | memory read beats for textures | 4.98 M | 0.78 M |
  | memory requests, wait each | 54 098, **253 cycles** (0.84 us) | 7 516, **268 cycles** |
  | GPU time waiting for memory | 64 % | 35 % |
  | render backend stalled on a full FIFO | 138 % of the clock (summed over pipes) | 100 % |
  | shader ALU working / busy | 92 % / 191 % | 96 % / 146 % |

  The GPU draws many screens' worth of pixels a frame and every memory request costs ~0.85 us; that
  product is the frame time on the home screen. Next: which draws make the 7 and 20 screens (ours:
  the preserve copy is one of them) and why a request waits that long (DDR / BIMC really at 1804 MHz?
  kernel memcpy 1776 MB/s at Gold 1747 MHz, 2500 at 2208).
  Thermal guard checked with lv_therm_hi=55: Gold stepped 1747 -> 1401 -> 1113 MHz by itself (r1); even
  at 1113 MHz the bench gave home 15.0, Settings 48.7.
  Open: boot r2 (same kernel, default limits) stopped answering over USB ~50 s after the UI was up
  (host writes time out, then no log); r1 and q1 ran their benches. Cause not known yet.
- 2026-11-28 night, kernel run-46071568759 (to 1166: recovery halts the VBIF before the reset, tries
  twice) + userland 46074724297 (patch_damage.py: glpreserve=2, glinuse=MS, in-use counter).
  - Where the pixels go: a plain frame passes exactly one screen (2.76 M at 60 fps), so the counter is
    real. Without the preserve copy (glpreserve=0, s1): Settings 20.0 -> 18.0 Mpx, 51.0 -> 53.7 fps;
    home 56 -> 51.5 Mpx, 13.7 -> 15.6 fps. The copy is ~10 % of the work; the rest is CoreAnimation's.
  - glpreserve=2 (copy only the box the other surface lacks): first version changed nothing (most
    frames' first draw has the scissor off: 3355 of 4207 display frames, box 0,0 1125x2436 in 835)
    and left orange/pink bands behind icon labels on the home screen (user video 23-56-56). Second
    version (no copy when the scissor is off, the complement of the box otherwise) is built but not
    judged yet. Opt-in only; default is the whole copy.
  - **87 % of display frames begin in a surface the panel still shows** (4328 of 4970, bench v1a:
    IOSurfaceIsInUse at the frame's first draw into a display surface). CoreAnimation has two display
    surfaces; SwapEnd returns at once, so it starts frame N+1 in the surface that is on the panel until
    frame N has latched. The preserve copy and the draws happen in view: the trembling / lagging
    bottom of the screen, the torn first rows of a scroll, likely the stale band at the bottom.
  - glinuse=20 (wait until the display lets the surface go): Settings 50.3 -> 32.8 fps (the frames no
    longer overlap), home unchanged (14). Proves the cause; not a fix.
  - Plan for the fix: CoreAnimation draws into one canvas that is never scanned (no preserve copy
    needed: it always holds the last frame); at the frame's end the canvas is copied (one screen, what
    the preserve copy costs today) into one of three scanout buffers that is neither on the panel nor
    waiting, and that buffer is shown. Needs eagl (texture substitution, end-of-frame copy) and the
    kernel (three scanout buffers, "show this one for the surface swapped").
  - s2 boot (gltrace_draws=11): three GPU hangs, the third recovery failed (old code), garbled picture
    (user video 23-35-46). r2 boot: USB stopped answering once; did not repeat in 8 later boots.
- **Frames are no longer drawn where the panel shows them** (xnu 1167, kernel run-46077885435 + userland
  46079146807, runs w2a/w2b). CoreAnimation draws a display frame into a texture of its own and eagl
  copies it into the surface at the frame's end (the "mirror" blit): that copy was what landed in a
  surface on the panel. The copy now goes into one of four scanout surfaces of ours that the display
  does not hold, the swapped surface names it (IOSurface value "lv-show"), and the kernel shows the
  named one. No copy added.

  | | before (v1a) | waiting, glinuse=20 (v2) | scanout surfaces (w2) |
  |---|---|---|---|
  | display frames begun in a surface in use | 87 % | (waited out) | **0 %** (0 of 9033) |
  | Settings slow drag | 50.3 fps, 20.7 Mpx | 32.8 fps | 50.5 fps, 19.8 Mpx |
  | home (App Library) | 14.9 fps, 53.7 Mpx | 13.9 fps | 13.7 fps, 56.4 Mpx |
  | memory wait / texture misses | 259-266 cyc / 23-25 % | same | 255-267 cyc / 23-25 % |

  9032 of 9033 copies went to a scanout surface, none had to fall back; 0 GPU hangs; screenshot of
  Settings correct. With glinuse=20 the user saw the tremble gone (and fewer fps); the scanout build
  is to be judged by eye next. glscan=0 turns it off, sweetfb_show=0 makes the kernel ignore the value.
  Still open by the user's eye: purple cards in the app switcher.
- 2026-11-28 01:10: the user checked the scanout build by finger - the tremble at the bottom and the
  torn rows are gone ("все зникло"). Scanout surfaces stay the default.
- Tiled textures in Mesa (glenv=FD_MESA_DEBUG=sysmem,ttile, run x1): a tear at boot and "many problems
  with the screen" (user); memory wait 216 cycles (255-267 without), texture cache misses 34 % (23-25 %).
  Rejected: picture.
- 2026-11-28 02:20, copies per shown frame (bench w2a): **9.7 mirror copies for every frame shown on the
  home screen**, 1.6 in Settings - eagl copies the display frame out at every glFlush / glFinish and
  CoreAnimation flushes many times a frame. That is ~27 of the 56 Mpx of a home frame. Fix in work
  (userland/gpu/patch_swaphook.py): copy once, when CoreAnimation swaps (libtopaz-inject interposes
  IOMobileFramebufferSwapBegin and calls redwood_eagl_before_swap). State: userland 46084039497 -
  the hook costs time (Settings 43.2 fps, 22.7 Mpx against 50.5 / 19.8) but never puts a copy off and
  logs nothing (0 put off, 0 at the swap; bench aa1a). Not understood yet. Known-good userland stays
  46079146807; the phone has 46084039497 installed now.
- Opening Messages by hand (build y1): 15 GPU hangs in a row, 14 recovered (new recovery: bus halt
  acknowledged, try 1 each time), one failed, backboardd crashed: flicker, tears, a blue screen (user,
  video 01-48-05). After a first hang the GPU hangs again within 10-30 submissions ("rem 231"). Not
  reproduced on the confirmed build yet.
- The night's "USB stopped answering" was an empty battery (3551 mV under load, the phone drains
  ~500 mA under iOS on a PC port). The phone is parked in fastboot between tests now (quick.ps1 -Park,
  tools/charge.ps1; bench line shows the lowest mV).
