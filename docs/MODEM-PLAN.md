# MODEM-PLAN: modem and Wi-Fi on lavender (SDM660 + WCN3990)

Why together: on this SoC the Wi-Fi firmware (`wlanmdsp.mbn`) runs inside the modem processor. No
modem boot, no Wi-Fi. The same modem boot is the base for telephony later (replaces the kernel
stubs AppleBaseband / AppleIPAppender, patches 1036/1038).

## What the tree already has (from the base project, written for topaz / SM6225)

`iokit/Kernel/arm/TopazModem.cpp` (boot-args `modem=1`, `wifi=1`, `modem_part=`): firmware read
from the modem partition by a baked offset table, PAS boot through TrustZone, SMP2P, GLINK over
SMEM (polled), QRTR, host services (pd-mapper, TFTP, rmtfs, WLFW), then the Wi-Fi radio (copy
engines, HTC/WMI/HTT, scan, join, WPA2 in software). `redwood_*.c`, `topaz_sta.c`,
`RedwoodWLAN.cpp`, `MiniIONetworkStack.cpp`: en0 and what wifid needs. None of it runs on lavender
today (no `modem=1` in the boot-args) and every address in it is topaz's.

## Rules

- `modemst1`, `modemst2`, `fsg`, `fsc`, `persist` are never written and never copied off the
  phone (calibration, IMEI). The code reads them into RAM for the modem; modem writes stay in RAM.
  Anything that would need a write: ask the user first.
- Qualcomm firmware (NON-HLOS, BTFM) is not committed. It is read from the phone's own `modem`
  partition at run time. A PC copy for study: `RedmiNote7\downloads\miui-nonhlos` (from the MIUI
  V12.5.1.0.QFGEUXM fastboot ROM).
- Every step is checked from the USB log; the user is not needed until a real network is joined.

## Steps

1. **Firmware files.** lavender's `modem` partition (mmcblk0p58, not A/B) is FAT16: `image/mba.mbn`,
   `modem.mdt` + `modem.b00..b09`, `wlanmdsp.mbn`, `bdwlan.*`, `qdsp6m.qdb`, 484 files. Replace the
   baked table (topaz offsets and CRCs) with a small read-only FAT16 reader in the kernel, so any
   firmware version on the phone works and nothing proprietary is in the repo.
   Done when: the kernel logs the size of `image/mba.mbn` and `image/modem.mdt` read from the phone.
2. **Addresses.** SMEM 0x86000000 (2 MB), APCS IPC 0x17911008, TCSR mutex 0x1F40000, modem carveout
   0x8AC00000 + 0x7E00000, MBA 0x94800000 + 0x200000, rmtfs 0x85E00000 + 0x200000, WLAN MSA
   0x85700000 + 0x100000. The work pool must leave 0xA1000000..0xE1000000 (GPU pool) alone.
   Check that iOS memory (ADT) does not cover these ranges.
   Done when: SMEM is parsed (version, partitions) and logged.
3. **Modem boot.** lavender's node is `qcom,pil-q6v55-mss` with `qcom,pil-self-auth`: not a PAS
   call but the MBA way (Linux `qcom_q6v5_mss.c`, MSM8998/SDM660 path): RPM votes for CX/MX and
   the clocks, MSS reset (GCC 0x179000), Q6 power-up at 0x4080000, `mba.mbn` at 0x94800000, RMB
   handshake (0x4180000), memory handed to the modem (SCM assign, as the code does for rmtfs),
   metadata and segments authenticated by the MBA.
   Done when: SMP2P from the modem appears (item 435) and "slave-kernel" reports READY.
4. **Links.** SMP2P doorbell bit 14 (same), GLINK doorbell bit 15 (was 12), channel IPCRTR.
   Done when: QRTR hello from node 1 and the modem's services are listed.
5. **Host services.** rmtfs with the DT buffer, pd-mapper, TFTP - as the old modem asks for them.
   Done when: the modem stays up for minutes with no FATAL in SMP2P.
6. **WLFW.** MSA at 0x85700000, board file by the chip's board id.
   Done when: FW_READY.
7. **Wi-Fi radio.** Power: RPM votes for PM660 LDO 5/9/6/19 and RF_CLK1 (the code votes nothing).
   Registers 0x18800000 (CE at +0x240000, shadow +0x32000), SMMU anoc2 0x16C0000 SIDs 0x1A00/1.
   Done when: a scan lists access points in the log.
8. **iOS side.** en0, wifid, Settings shows networks; join needs the user (password).
9. **Bluetooth** (WCN3990 over UART c1af000, firmware from `bluetooth` partition) - after Wi-Fi.
10. **Telephony** (QMI services of the modem to CommCenter) - a stage of its own.

## State

- 2026-11-26: survey done, plan written. Next: step 1.
