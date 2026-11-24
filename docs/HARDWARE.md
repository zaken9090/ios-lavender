# Hardware facts: Redmi Note 7 (lavender), test unit

Stage E1, 2026-11-24. Column "Source" says where each value comes from:
- **adb** - unrooted stock Android (MIUI V12.5.1.0.QFGEUXM, Android 10): `getprop`, `/proc/cpuinfo`, `/proc/meminfo`, `/proc/interrupts`
- **fastboot** - `fastboot getvar all`
- **dtb5** - the device tree ABL selects on this unit (`ro.boot.dtb_idx=5`), split out of the stock `boot.img`
  with `tools/bootinfo.py` and decompiled with `dtc`

Not available without root: `/proc/iomem`, `dmesg`, `/sys/firmware/devicetree`. The live values ABL writes into
the tree (memory banks, command line) are therefore **still to be measured by the shim in E2**.

## Unit

| Item | Value | Source |
|---|---|---|
| SoC | SDM660, msm-id 317 (0x13d), board-id 0x20008, model string "SDM 660 PM660 + PM660L MTP F7A" | dtb5 |
| RAM | 4 GB (MemTotal 3826256 kB) | adb |
| Panel | **Tianma** NT36672A, 1080x2340, video mode, 60 Hz, 24 bpp, no DSC | adb `sys.panel.display`, dtb5 |
| Panel timings | H: fp 90, bp 120, pw 2. V: fp 10, bp 8, pw 3 | dtb5 |
| Touch | Novatek `NVT-ts`, I2C address 0x62, IRQ GPIO 67, reset GPIO 66 | adb interrupts, dtb5 |
| Storage | eMMC, `variant: SDM EMMC`, boot device `c0c4000.sdhci` | fastboot, adb |
| userdata | 0xCB77F7E00 bytes (54.6 GB) | fastboot |
| Bootloader | unlocked, `secure: yes`, anti-rollback 4, max-download 805306368 (768 MB) | fastboot |

## Boot image the stock ABL accepts

| Item | Value | Source |
|---|---|---|
| Header | version 1, page size 4096 | stock boot.img |
| Kernel | gzip, load 0x8000, 35 DTBs appended after the gzip stream | stock boot.img |
| Ramdisk / second | size 0 (system-as-root), tags 0x100 | stock boot.img |
| DTB choice | index 5; index 7 has the same msm-id/board-id | adb, stock boot.img |

## CPU

| Item | Value | Source |
|---|---|---|
| Cores 0-3 | MPIDR 0x0-0x3, part 0x801 (Kryo 260 Silver) | dtb5, adb |
| Cores 4-7 | MPIDR 0x100-0x103, part 0x800 (Kryo 260 Gold) | dtb5, adb |
| Features | fp asimd aes pmull sha1 sha2 crc32 (ARMv8.0, no LSE atomics) | adb |
| Bring-up | PSCI 1.0 over SMC | dtb5 |
| 16K granule | not readable from user space: measure `ID_AA64MMFR0_EL1.TGran16` per cluster in the shim | E2 |

## Interrupts and timer

| Item | Value | Source |
|---|---|---|
| GIC | GICv3: distributor 0x17a00000 (+0x10000), redistributors 0x17b00000 (+0x100000), stride 0x20000 | dtb5 |
| Arch timer | 19.2 MHz; PPI 1/2/3/0 = INTID 17 secure, 18 physical, **19 virtual**, 16 hyp | dtb5, adb |
| MMIO timer | 0x17920000 | dtb5 |

INTID = SPI number + 32. Values seen live in `/proc/interrupts` match the tree.

## Devices

| Device | MMIO | INTID | Source |
|---|---|---|---|
| eMMC `sdhci-msm-v5` | 0x0c0c4000 (+0x1000), CQE 0x0c0c5000 | 142 (hc), 144 (pwr) | dtb5, adb |
| USB DWC3 | 0x0a800000 (+0xc8d0), wrapper to +0xfc100 | 163 (dwc3), 212 (msm_dwc3) | dtb5, adb |
| USB QUSB2 PHY | 0x0c012000 | | dtb5 |
| Display MDP | 0x0c900000 (+0x90000), VBIF 0x0c9b0000 | 115 | dtb5, adb |
| DSI 0 | ctrl 0x0c994000, PHY 0x0c994400 | | dtb5 |
| Touch bus: I2C `i2c-msm-v2` | 0x0c175000 (+0x600) | 127 | dtb5, adb |
| GPU Adreno 512 | 0x05000000 (+0x40000), chip id 0x05010200 | 332 | dtb5, adb |
| GPU SMMU (`smmu-v2`) | 0x05040000 | | dtb5 |
| SPMI PMIC arbiter | core 0x0800f000, chnls 0x08400000, obsrvr 0x09400000, intr 0x0a400000, cnfg 0x0800a000 | | dtb5 |
| TLMM (GPIO) | 0x03000000 | | dtb5 |

## Reserved memory (static part of the tree)

| Region | Base | Size |
|---|---|---|
| wlan_msa_guard / wlan_msa_mem | 0x85600000 / 0x85700000 | 1 MB each |
| removed_regions | 0x85800000 | 0x3700000 |
| modem_fw | 0x8ac00000 | 0x7e00000 |
| adsp_fw | 0x92a00000 | 0x1e00000 |
| pil_mba | 0x94800000 | 0x200000 |
| cdsp_fw | 0x94a00000 | 0x600000 |
| **splash (framebuffer left by ABL)** | **0x9d400000** | 0x2400000 |
| dfps_data | 0x9f800000 | 0x1000 |
| pstore | 0xa0000000 | 0x400000 |

All of them are `no-map` except splash, dfps and pstore. Dynamically placed (no fixed address): venus_fw 8 MB,
adsp 8 MB, qseecom 20 MB, secure 92 MB, CMA 44 MB. The `memory` node is empty in the file: ABL fills it at boot.

## Measured by the shim (stage E2, 2026-11-24)

Read from the phone screen after `fastboot boot` of `shim/` (probe builds v1 and v2).

| Item | Value |
|---|---|
| `fastboot boot` | works on this unit with a header v1 image (gzip Image + the one matching DTB) |
| Entry state | Silver cpu0 (MPIDR 0), EL1, MMU off (SCTLR 0xc00800), image at 0x80080000, DTB pointer in x0 |
| RAM banks from ABL | 0x80000000 + 0x80000000 and 0x100000000 + 0x7e4c0000 (last value read from a photo, digits 4/1 uncertain) |
| Panel argument from ABL | `mdss_mdp.panel=1:dsi:0:qcom,mdss_dsi_nt36672a_tianma_fhdplus_video:...` |
| Framebuffer | 0x9d400000, 1080x2340, 4 bytes per pixel, stride 4320 bytes, x8r8g8b8 (0x00ff0000 is red) |
| Silver | part 0x801, ID_AA64MMFR0 0x1122: **no 16K granule**, 4K yes, 40-bit PA; runs at 1382 MHz (PLL L=72) |
| Gold | part 0x800, ID_AA64MMFR0 0x101122: **16K granule present**; started with PSCI CPU_ON(0x100) |
| Gold clock as left by XBL | 149 MHz (its PLL is locked at L=32 = 614 MHz, but the core is paced by the OSM block) |
| Gold after OSM clock to 200 MHz | 599 MHz (OSM RCG cfg 0x105 -> 0x102 at 0x179d1130, update at 0x179d112c) |
| Gold PLL by hand | L=58: 1113 MHz, L=80: 1535, L=96: 1843, L=115: **2207 MHz**; 10/10 checksum runs at each step, no voltage change |
| 16K MMU on Gold | works: one level-2 table, 32 MB blocks, TCR 0x20080b51c, SCTLR 0xc01805 |
| 4 MB RAM fill on Gold | 105 ms with MMU/caches off at 149 MHz, 3 ms with caches on, under 1 ms at 2207 MHz |
| PSCI SYSTEM_RESET | cold reset, the phone boots Android |
| Payload loader self-test | 4/4 checks pass (`build.ps1 -SelfTest`): boot_args revision, load address, command line, MMU off at entry |

Gold clock sequence (register meanings from the Linux `clk-cpu-osm` driver and the first attempt's notes):
PLL at 0x17816000 (+0 mode, +4 L, rate = L x 19.2 MHz, +0x2c bit 16 = locked); Gold RCG cfg 0x17811054,
cmd 0x17811050, source 4 = GPLL0, 3 = own PLL. Park on GPLL0, write mode 0, L, mode 2, 6, 7, wait for lock, switch back.
