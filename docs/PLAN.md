# Plan of 2026-11-28 (user; replaces the order below until done)

After the manual test of kernel run-46125445657 + userland 46134608630: no tearing, flicker or shake,
but nothing is smooth - fps dips are visible even in Settings (bench: 60 fps on average with 1-8 late
frames nearly every second; all four Gold cores at 100 %).

S1. Audit: what iOS does with its efficiency cores (which threads, by which rule; XNU's AMP scheduler,
    what CLPC adds) - docs/CORES.md.
S2. Our Silver cores the way iOS uses E cores: part of the load moves off the Gold cores. Known: Silver
    has no 16K granule (HARDWARE.md), so this means a 4K-granule kernel (the first project had one:
    its patches 0993, 0994, 1003; 8 cores without AMP were 9 % slower there).
S3. Core voltage and dynamic clocks for Gold + Silver (nothing has to sit at the top clock).
S4. Back to GPU + DDR: voltage first (the rail does not follow our vote: PM660L S3 852-856 mV at 300 and
    600 MHz), then the highest GPU clock that is stable, then dynamic scaling. Until then GPU DVFS is off
    by default again (xnu 1171: 2 of 13 boots hung right after a 300 -> 600 step, one not recovered).
S5. Smoothness of the whole system (late frames, not averages: SWEET FPS "late" / gaps).

S3 in steps (user 2026-11-28: S3 before S2; "also sort out the voltage that is missing for the top clock"):
 1. (done, xnu 1174) the Gold clock follows the load, 1113..2208 MHz, touch boost; rail untouched (868 mV).
 2. (done, xnu 1175, default) the rail goes down with the clock: 768 mV to 1401 MHz, 828 at 1747. Written
    as one two-byte SPMI write to PM660 S3 (the master phase). No measurable gain at idle.
 3. (done, xnu 1176, default) the stock voltage for the top clocks: 1958 MHz 885 mV, 2150 MHz 937,
    2208 MHz 948 (was 868: 80 mV under). Through 872 mV the array power mux goes MX <-> APC (0x179d0010 =
    2 / 0, wait 0x179d0018 & 0x1f == 3 / 0); the top step also needs mem-acc level 3 (0x179d1370 = 1,
    msm8998's registers; without it 948 mV corrupted the cores' work). Three boots clean.
 4. Silver, when the cores exist (S2).
S4 state 2026-11-29 (GPU-PLAN 2026-11-28 22:10 .. 2026-11-29 00:45): the GPU sits on CX (no rail of its
own); the chip's bin (0x87) ends at 647 MHz; clocks above 300 MHz come from GPU PLL0 now (xnu 1177) and
the governor steps 300 <-> 588 MHz between two running sources by default (seven boots, no stop; home
~25 fps). Open: 647 MHz stops within 20 s - CX stays 848-852 mV whatever level we vote (the RPM does act
on other regulator requests of ours), and PM660L S4, named with S3 as VDD_CX in the stock DT, is off.

For S4, found on the way (stock DT, cpr4-ctrl@05061000 "gfx"): GPU corners 160 / 266 / 370 / 465 / 588 /
647 / 750 MHz with CX levels 0x40 0x40 0x80 0xc0 0x100 0x140 0x180, ceilings 585..1070 mV, and a
**gfx mem-acc bit** (0x01fcf004 bit 0: 1 up to 370 MHz, 0 from 465 MHz) that we never switch - a
candidate for the hangs after 300 -> 600 MHz steps.

State 2026-11-28 15:45 (docs/CORES.md, GPU-PLAN.md): S1 done. Measured for S2: with the background quiet
the late frames in Settings stay (4-8 %), so E cores would help the minute after boot (extensions killed
on check-in timeouts, the wallpaper late) rather than steady scrolling; Gold 2208 MHz halves the late
frames (S3). Done for S5: xnu 1172 (no contiguous hunt per IOSurface), 1173 (vsync tick from the panel).
Open for S5: the 4-5 % floor (who is late: application or backboardd), the AegirPoster crash loop
(needs Metal), the panel-native resolution, widget / wallpaper extensions killed on check-in timeouts
in the busy first minute after boot (Photos widget stays a placeholder: GPU-PLAN 2026-11-28 20:35), the
GPU stop during boot that nothing notices (bg1: "gpu 100 %, sub 0", no recovery).

# Priority plan (2026-11-27, after the metrics of xnu 1160-1163)

The order work is done in until the user changes it. Each item ends with a bench (tools/bench.py, LVM
metrics), screenshots where the picture could change, and a line in GPU-PLAN.md / LEFTOVERS.md.
Base: kernel run-46077885435 (to 1167) + userland 46079146807, Gold 1747 MHz, GPU 300 MHz.

## P1 - fps: memory traffic of a frame

Measured: fps follow neither the CPU clock (1401-2208 MHz) nor the GPU clock (300/600 MHz); the GPU is
busy 94-96 % on the home screen at either clock; lower DDR lowers fps. So a frame is limited by how much
memory it moves. No picture quality may be traded.

1. Count what our GL layer (eagl.c) and Mesa move per frame in the App Library and in Settings: preserve
   copies, zero uploads, IOSurface refills, sums, resolves - in KB a frame (a counter line per second).
2. Remove or shrink the biggest mover that the picture does not need (e.g. copy only the damaged part,
   no upload for a surface that is fully redrawn).
3. Fixed waits in the frame path (fence polling, presenter) once the traffic is down.

4. (done 2026-11-28, xnu 1167 + userland patch_scanout.py) 87 % of display frames were copied into the
   surface the panel still showed; the end-of-frame copy now goes to one of four scanout surfaces
   (0 % in view, fps unchanged). Next here: the 7-20 screens of pixels a frame and the 0.85 us memory wait.
5. (done 2026-11-28, patch_flushwho.py) the display copy is put off at CA's mid-frame glFlush
   (glskip, default c0x1884b62e0): home 14.6 -> 20.6 fps, 51 -> 32.5 Mpx a frame.
6. (done 2026-11-28, patch_canvas.py) both display surfaces drawn in one texture: no preserve copy;
   Settings 20.5 -> 17.1 Mpx, home 21.2 fps. GMEM measured again: slower (rejected).
7. (done 2026-11-28, xnu 1170-1171) the home screen waits on a fixed ~800 ns GPU memory latency (not
   DDR bandwidth: same fps at DDR 1017 and 1804 MHz); GPU DVFS 300 <-> 600 MHz by default: home
   21.4 -> 24.4 fps. Next: the rail with the clock (power), why the latency is ~800 ns (VBIF / bus
   settings against Linux), native resolution (1125x2436 is drawn, panel is 1080x2340).
8. (2026-11-28, profile pf7) backboardd on the home screen: surface_changed 15 % of its CPU
   (patch_sumfast.py: -21 % of that). The ~800 ns latency: BIMC port already bypass, SMMU identity -
   taken as the SoC's own. Next: modify bits from the kernel instead of sums (own wired surfaces),
   sharing app surfaces needs SMMU translation (gpu_identity=0).

## P2 - safety: temperature (done: xnu 1165)

No thermal control exists (stock: core limit 70 C, hotplug 105 C, reset 115 C). A step-down of the Gold
clock above a limit (lv_gold_set_l, TSENS in LavenderMetrics) with a boot-arg for the limits.

## P3 - GPU stability

- A hang the soft reset does not recover: power-cycle the GPU and start the CP again.
- `gpu_mhz` (reports MAX_FREQ only, boots with 600 hung) and `lv_gpu_mhz` (the real clock): one argument,
  and find what user space does with MAX_FREQ.

## P4 - Gold at 2208 MHz inside the stock voltage

PM660 S2 + S3 to 872 mV, array power mux to APC (0x179d0010 = 2, status 0x179d0018 & 0x1f == 3), then
948 mV, then L 115. Only after P2. Gain: single-thread speed (app start), not fps.

## P5 - functions

Battery level (done: xnu 1168, PM660 fuel gauge; temperature fix in 1168 after bench ab1), AegirPoster crash loop (lock-screen
flicker), webbookmarksd crash loop, Bluetooth A2DP (Skywalk nexus), stale keyboard band; purple switcher cards (done 2026-11-28: ASTC hidden from CA,
patch_noastc.py).
