# Ideas from the user's first lavender project (review 2026-11-25)

Source: `Android-iOS/ios-lavender` (xnu/patches 0990-1036, userland/gpu and userland/mesa commits).
Only ideas are taken; code is written for this tree, each port asked for first.
Their best result: home 45 fps, Settings 29 fps with the GPU (4K kernel, 3 GB RAM, sysmem rendering).

## A. Memory and stalls (our GL hang: UI threads page code in from disk, throttled)
| # | Idea | Their patch | Here |
|---|---|---|---|
| A1 | iOS RAM 3 GB: 0xc0000000..0x17e000000 (lower bank above the carve-outs + upper bank) instead of 2 GB | mkadt_lavender.py --silver | we give 0x100000000 + 0x7e000000 (2 GB); GPU pool would move below 0xc0000000 (they used 0xa4000000, 384 MB) |
| A2 | GPU pool descriptors as sub-ranges of the chunk | 1021 | **done** (our 1016) |
| A3 | Waiting threads' kernel stacks in the sampler | 1020 | **done** (our 1017, + memory line) |
| A4 | Surface arena: GPU-shareable surfaces from contiguous chunks, read in place (no 11 MB copies) | 1018, 1019 (chunks above 4 GiB only) | missing |
| A5 | Contiguous surface allocation backs off instead of failing | 1000 | check |

## B. GPU and rendering speed
| # | Idea | Their patch/commit | Here |
|---|---|---|---|
| B1 | FD_MESA_DEBUG=sysmem by default (home 36->45, Settings 26->29) | 55753d2 | missing (userland env) |
| B2 | Threaded Mesa context + 3 freedreno fixes (hangs in glFinish) | c60e82a, dc161c9, 93d9897, 1c88839, d7b452a | missing |
| B3 | glorder=2, glsolid, glzero, cheap surface_changed (was 15% of backboardd) | c828344, 44ae361, 125fe46, ebc93d2 | check our eagl.c |
| B4 | DDR vote + RPM clock scaling (BIMC stayed 648 MHz without it) | 1002, 1024, 1025 | missing |
| B5 | GPU clock 600 MHz (CX vote) | 0999, gpu_mhz | missing (step 9) |
| B6 | GPU hang report + recovery | 1036 | missing |
| B7 | push_seen / push_ms: fewer cache pushes per submission | 1012, 1013 | check |

## C. Display
| # | Idea | Their patch | Here |
|---|---|---|---|
| C1 | iOS draws 750x1624 (or 828x1792), MDP QSEED3 scales to the panel: ~2x fewer pixels | 1028, 1029, 1031 | missing |
| C2 | Real vsync from INTF_1 frame counter | 1001 | check |
| C3 | sweetfb_vhz=120: finer frame grid (20 ms frame -> 40 fps instead of 30) | 1033 | missing |

## D. CPU / kernel speed
| # | Idea | Their patch | Here |
|---|---|---|---|
| D1 | No kmsg signatures, no zalloc zero check | 1035 | missing |
| D2 | 4K-page kernel on gold at full clock (gold4k), AMP off (8 cores were 9% slower) | 0993, 0994, 1003, cbc75fa | we run 16K on gold |

## E. Picture correctness (later, after speed)
Framebuffer-fetch emulation, blur fixes (glsync, glpreserve, ds8, colour matrix), CoreImage in apps.

## Proposed order
1. A1 (3 GB RAM) - most likely fix for the GL stall; confirm with the SMM memory line first.
2. B1 + B3 (userland defaults) and A4 (no surface copies).
3. B4 DDR, C1 scaled drawing, C3, D1.
4. B2 threaded Mesa, B5 600 MHz, B6.
