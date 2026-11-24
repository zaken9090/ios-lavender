# Audit of prior work (stage E0, 2026-11-24)

Sources read: `MakrSas/ios-topaz` (reference), our first attempt `zaken9090/ios-topaz`
(branches `lavender`, `lavender-clean`, `lavender-minimal`), `NAANG360/hackios-lavender-xnu`.
Everything here is **inherited knowledge, not yet re-measured in this project**. Each fact is
re-verified in the stage that uses it. The first attempt's probe notes (`shim-probe-v*`) are lost,
so E1/E2 must record measurements again.

Not yet audited: `pcorezzola/lavender-ios16` and `aLpHa-Git-69/ios-lavender` (another lavender port,
imported into NAANG360's `integration/lavender-ios16-base`; claims home screen and Settings).

## Hardware facts to re-verify

| Item | Value | Verify in |
|---|---|---|
| ABL entry | `fastboot boot`, boot image header v1, Image.gz + real lavender DTB appended (msm-id 317, board-id 0x20008); EL1, MMU off, x0 = DTB | E2 |
| RAM | 0x80000000 +2G, 0x100000000 +0x7e1c0000 (4 GB unit); carve-outs below 0xa0400000 | E1 |
| Framebuffer | ABL splash 0x9d400000, 1080x2340, stride 4320, a8r8g8b8 | E2 |
| MDP5 | 0x0c900000; VIG0 +0x5000 scans the splash, CTL0 +0x2000; SRC0_ADDR + FLUSH 0x20001 flips; no DSC | E6 |
| GIC | GICv3: GICD 0x17a00000, GICR 0x17b00000, stride 0x20000 | E1 |
| Timer / PSCI | 19.2 MHz, virtual INTID 19, physical 18; PSCI 1.0, no SYSTEM_RESET2 | E1/E2 |
| CPU | Silver A53-class MPIDR 0x0-0x3: **no 16K granule**. Gold A73-class MPIDR 0x100-0x103: has 16K | E2 |
| eMMC | sdhci-msm v5 at 0x0c0c4000; no SDMA, only 64-bit ADMA2; PIO does not drain the FIFO | E5 |
| Touch | Novatek NT36672A, I2C 0x62 on QUP at 0x0c175000 (GPIO 2/3), IRQ GPIO 67, reset GPIO 66 | E7 |
| USB | DWC3 at 0x0a800000, QUSB2 PHY | E4 |
| GPU | Adreno 512 at 0x05000000, GPUCC 0x05065000, SMMU 0x05040000 | E8 |
| Panel vendor | BOE or Tianma: never recorded | E1 |

## Solutions that worked before (to re-implement, not copy)

- **Gold entry:** shim starts on Silver cpu0, `PSCI CPU_ON(0x100)`; Silver cpu0 then `CPU_OFF`.
- **Gold at 1/4 clock:** XBL leaves APCS_COMMON RCG 0x179d112c at 100 MHz. Set it to 200 MHz, park Gold RCG
  (0x17811054) on GPLL0, relock Gold PLL (0x17816000) to L, switch back. L=115 gives 2208 MHz.
- **First kernel text:** topaz patch series + one hardware patch (console address, SM6225 access off);
  the topaz battery driver hangs the bus and must be off.
- **eMMC root:** one-descriptor 64-bit ADMA2. First iOS boot takes 15-25 min, must not be interrupted.
- **Display:** CPU frame copy first; later MDP flip through VIG0/CTL0; QSEED3 can scale.
- **USB log:** WinUSB bulk endpoint read by a Python script, plus remote commands (reboot to fastboot,
  screenshot, file push, key/tap). Alternative seen elsewhere: CDC-NCM + UDP 5140.
- **Reboot to bootloader without buttons:** PM660 PON restart reason 2 + warm PS_HOLD reset
  (PSCI SYSTEM_RESET is cold and boots Android).
- **GPU:** SMMU stage-1 map before the zap shader; stream on the last SMR group (bypass refused);
  TCR2.SEP=UPSTREAM; then a5xx init and Mesa freedreno in user space.
- **GPU 600 MHz:** RPM CX NOM_L1 vote + GFX mem-acc high. **DDR:** RPM vote to 1804.8 MHz.
- **Buttons (other port):** SPMI arbiter v3, PM660/PM660L.

## Dead ends and pitfalls

- AMP over 8 cores (4K kernel) was ~9% slower than 4 Gold cores; 4-core boots stalled on an AMP kernel.
- CPRh/OSM cannot be run from EL1 (external abort), so no voltage scaling.
- A second cacheable view of the GPU pool hangs the system; arena chunks below 4 GiB starve the pool.
- CI: macos-14 runners retired; ccache served stale `assym.s`; a push trigger cancels dispatched runs;
  arm64 userland jobs were never picked up.
- TWRP 3.7.0_9 crashes under `fastboot boot`.
- Open conflict: another port reports `fastboot boot` is a stub on its ABL (shim flashed to `recovery`).
  It worked on our unit; confirm at the start of E2.
- Never solved: Wi-Fi, audio, battery, PM660 keys in our tree.

## Tooling to recreate

| Tool | Purpose |
|---|---|
| shim build script (Windows LLVM, `aarch64-none-elf`) + `mkboot` | boot image for `fastboot boot` |
| `mkadt` for lavender | fake Apple Device Tree with reserved-range-aware RAM map |
| `mkpayload`, `adt` | pack kernel + ADT + cmdline |
| `mktest`, `mkfakepayload` | colour-band test image, loader self-test |
| WSL scripts | hfsplus module (GCC 13), apfs-fuse, IPSW extract, root image, img2simg |
| USB log reader | live log to a file, remote commands |
| bench scripts | boot-image matrix, fps measurement, home/app screen detection |
| CI `xnu.yml` | workflow_dispatch only; `macos-15` (~7 min), fallback `macos-15-intel` + Xcode 16.0 (~12 min) |

## Decisions for this project

1. 16K kernel on the four Gold cores is the baseline. Silver / 4K is a late, separate experiment.
2. Gold clock fix goes into the shim from the start, so later fps numbers are comparable.
3. USB log channel (E4) comes before storage work: it removes the need for screen photos.
4. Every measured fact is written to `docs/HARDWARE.md` with the command or image that produced it.
5. Patches are kept as a small lavender series on top of the reference series, one purpose per patch.
