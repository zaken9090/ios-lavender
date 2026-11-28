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
flicker), webbookmarksd crash loop, Bluetooth A2DP (Skywalk nexus), stale keyboard band / purple
switcher cards.
