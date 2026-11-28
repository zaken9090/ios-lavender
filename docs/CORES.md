# Cores: what iOS does with efficiency cores, and what our Silver cores need (PLAN S1, 2026-11-28)

Sources: xnu-8796.141.3 (read by a subagent, paths below), the base's patches 0140-0142, the first
lavender project's patches 0993 / 0994 / 1003 / 1026 and its commit cbc75fa, our bench logs.

## 1. What iOS does (XNU, AMP phones)

- iOS 16 on P+E phones runs the plain "amp" scheduler (`sched_amp_dispatch`, osfmk/kern/sched_amp.c);
  Edge is macOS-only (osfmk/arm64/proc_reg.h:85-99). One P and one E cluster exactly
  (sched_amp_common.c:437). `__ARM_AMP__` comes from the CPU-family header, and is dropped when
  `MAX_CPU_CLUSTERS == 1` (board_config.h:120).
- The kernel learns the cluster from the device tree: `/cpus/*` `cluster-type` = 'E' (0x45) or 'P' (0x50)
  (`ml_parse_cpu_topology`, osfmk/arm64/machine_routines.c:944-1132); absent = one SMP cluster.
- Who runs where (`recommended_pset_type`, osfmk/kern/processor.c:1643), by base priority:
  1. a thread bound to a cluster: that cluster;
  2. background (base_pri <= 4) and utility (<= 20): **E**;
  3. everything else: what the thread group recommends (CLPC); with no recommendation, user threads
     (default, user-initiated, UI, fixed, realtime) go to **P** and all kernel_task threads to **E**.
- E work never runs on P while an E core is recommended. P work spills to E only when no P core is idle,
  the P load is at least ncpu + 3 (`sched_amp_spill_count`) and the thread is not realtime; only E cores
  steal (from the P queue); an idle P core pulls P threads back from E.
- CLPC (closed kext) adds: per-thread-group recommendations (so utility work of a foreground app may
  ride P, kernel threads are not all on E), recommended / powered cores, and all of DVFS. Open XNU has
  no frequency governor: only the callbacks (sched_perfcontrol_*: oncore / offcore / csw / state_update /
  max_runnable_latency, osfmk/arm/machine_routines.h:1084-1238).
- So on a real iPhone the daemons we see eating the Gold cores after boot (dasd, biomed, coreduetd,
  contextstored, duetexpertd, analyticsd, mobileassetd ... : background / utility QoS) run on E cores
  and never take a P core from backboardd, SpringBoard or the app.

## 2. What our Silver cores need

- The translation granule is a compile-time global (`__ARM_16K_PG__` -> ARM_PGSHIFT, TCR for every CPU;
  nothing reads ID_AA64MMFR0.TGran). Silver has no 16K granule (HARDWARE.md), so all eight cores means a
  **4K-granule kernel**. User space keeps 16K pages: without `__ARM_16K_PG__` the VM page size is a
  runtime constant set to 16K above 1 GB of RAM (osfmk/arm/arm_init.c:396-411, PAGE_RATIO 4), and
  64-bit tasks get 16K from the commpage / `vm_map_set_page_shift` (mach_loader.c:511).
- It exists already: the base builds with `TOPAZ_4K=1` (0140: 4 KiB pages, 0141: Gold = P, Silver = E,
  0142: early console). The first project ran it: 0993 / 0994 / 1003 (4K kernel booted on Gold, ADT
  `--all8`, shim `lv_gold=`) and 1026 (AMP made safe: no NULL ecore_set, kernel threads on P, boot-args
  lv_amp_spill / lv_amp_steal / lv_amp_spillsteal).
- Its result (commit cbc75fa, 2026-11-21): eight cores with sched_amp were **stable but ~9 % slower in
  Settings** than four Gold cores with Clutch (one render thread; and a four-core boot stalled on an AMP
  kernel), so AMP was switched off there. Without AMP eight cores were slower too (the render thread
  landed on a 1.37 GHz A53 as often as on an A73).
- Needed here: build our series (to 1171) with TOPAZ_4K, 4K-clean drivers (GPU, IOSurface, modem, Wi-Fi,
  audio were written on 16K), `MAX_CPUS 8`, `MAX_CPU_CLUSTERS 2`, `__ARM_AMP__`, ADT with eight cpu nodes
  and `cluster-type`, PSCI start of the Silver cores, Silver clock (PLL L 72 = 1382 MHz at entry; top
  1843 MHz) and its rail (PM660 S1).
- Risks: 4x smaller TLB reach on the Gold cores (CPU-bound backboardd would lose some), kernel threads
  confined to E without a controller (our display / GPU / touch threads must be bound to P), A73 / A53
  feature differences (commpage from the boot CPU), all drivers retested.

## 3. Would it buy smoothness? (measured before building anything)

Bench "Settings slow drag", kernel run-46125445657, GPU 300 MHz, tools/late.py:

| run | when | CPU load | late frames | seconds without a late frame |
|---|---|---|---|---|
| ar1 | right after boot | 309 % | 5.4 % | 6 % |
| ar2 | same boot, after 8 min idle | (see GPU-PLAN) | | |

If the late frames stay with the background quiet, moving daemons to E cores will not cure them.
