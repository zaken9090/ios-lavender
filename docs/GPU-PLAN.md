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
   **Partial 2026-11-25**: GL draws the lock screen (FD512), but no unlock, frames 0.5-1.5 s late,
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
