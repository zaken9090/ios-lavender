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

## Reference for step 3: MBA boot of an SDM660 modem (summary of Linux qcom_q6v5_mss.c v6.6, MSS_SDM660)

Resources (sdm660_mss): proxy clocks xo, qdss, mem; active clocks iface, bus, gpll0_mss, mnoc_axi,
snoc_axi; power domains cx, mx; memory protection needed; no alt reset. Registers: qdsp6 base
0x4080000, RMB base 0x4180000, MSS restart GCC 0x179000, halt regs (q6, modem, nc) from the DT.

RMB (offsets from 0x4180000): MBA_IMAGE 0x00, PBL_STATUS 0x04, MBA_COMMAND 0x08, MBA_STATUS 0x0C,
PMI_META_DATA 0x10, PMI_CODE_START 0x14, PMI_CODE_LENGTH 0x18. PBL success = 1. MBA status:
1 XPU unlocked, 2 unlocked+scribbled, 3 metadata authenticated, 4 authentication complete,
negative = error. Commands: 1 metadata ready, 2 load ready.

QDSP6SS (offsets from 0x4080000): RESET 0x14 (bit0 STOP_CORE, bit1 CORE_ARES, bit2 BUS_ARES),
GFMUX_CTL 0x20 (bit1 CLK_ENABLE), PWR_CTL 0x30, MEM_PWR_CTL (v6) 0x34, XO_CBCR 0x38 (bit0 enable,
bit31 off), BHS_STATUS 0xC4 (bit0 ack), STRAP_ACC 0x110 (write 0x20). PWR_CTL bits: 24 BHS_ON,
25 LDO_BYP, 22 CLAMP_QMC_MEM, 21 CLAMP_WL, 20 CLAMP_IO, 19 SLP_RET_N, 18 L2DATA_STBY_N.

Order:
1. cx/mx votes, proxy and active clocks on, MSS reset deasserted (GCC restart register = 0).
2. Give the MPSS region and the MBA region to the modem (SCM assign: HLOS RWX -> MSS_MSA RW).
3. mba.mbn copied to the MBA region; RMB MBA_IMAGE = its address.
4. Q6 reset sequence: STRAP_ACC = 0x20; RESET |= core|bus|stop; XO_CBCR |= 1, wait bit31 clear;
   PWR_CTL |= BHS_ON, wait BHS_STATUS bit0; PWR_CTL |= LDO_BYP; clear CLAMP_QMC_MEM;
   PWR_CTL |= L2DATA_STBY_N | SLP_RET_N; MEM_PWR_CTL bits 28 down to 0 set one by one (1 us
   apart); clear CLAMP_WL; clear CLAMP_IO; RESET &= ~CORE_ARES; GFMUX |= CLK_ENABLE;
   RESET &= ~STOP_CORE. Wait PBL_STATUS != 0 (1 s), must be 1. Wait MBA_STATUS != 0 (5 s), 1 or 2.
5. Metadata (ELF header + hash segment of modem.mdt) in a buffer assigned to the modem;
   PMI_META_DATA = address; command 1; wait status 3 (1 s); buffer back to HLOS.
6. PMI_CODE_LENGTH = 0. Each loadable segment copied to mpss + (paddr - reloc base), tail zeroed.
   After the first: PMI_CODE_START = boot address, command 2. After every segment:
   PMI_CODE_LENGTH = total so far; a negative status = authentication failed. While loading the
   region is shared HLOS+MSA; at the end MSA only. Wait status 4 (10 s).

- 2026-11-26: step 1 written (xnu 1043).
- 2026-11-26: step 1 verified on the phone (kernel CI 45731435398): 316 files, image/mba.mbn 238256 bytes, image/modem.mdt 8412, image/wlanmdsp.mbn 3859712. Next: steps 2 and 3.

## Reference: SDM660 clocks and registers for the modem (Linux gcc-sdm660.c v6.6, sdm630.dtsi)

GCC base 0x100000. Branch clocks (enable = bit 0 of the register, bit 31 = off):
gcc_mss_cfg_ahb_clk 0x8a000 (iface), gcc_mss_mnoc_bimc_axi_clk 0x8a004, gcc_mss_q6_bimc_axi_clk
0x8a040 (bus), gcc_mss_snoc_axi_clk 0x8a03c, gcc_bimc_mss_q6_axi_clk 0x4401c;
gcc_boot_rom_ahb_clk (mem): vote bit 10 of 0x52004, status at 0x38004. GCC_MSS_RESTART 0x79000
(the DT's 0x179000 absolute). No MSS power domain in GCC. Upstream GCC has no "gpll0_mss" clock.
Halt registers (stock DT, TCSR): q6 0x1f63000, modem 0x1f65000, nc 0x1f64000 (HALTREQ +0,
HALTACK +4, IDLE +8). smp2p-mpss: items 435 (in) / 428 (out), mailbox apcs bit 14, SPI 451.
SMEM 0x86000000 + 0x200000, hwlock tcsr-mutex 0x1f40000 lock 3. APCS 0x17911000.
- 2026-11-26: steps 2-3 written (xnu 1044, 1045). Run 1 (no BIMC clock): everything up to the Q6 sequence works, PBL silent. Run 2 (BIMC clock gcc 0x4401c on): the phone dies within the second after the Q6 starts (USB gone, needs a manual fastboot). Not yet voted: RPM qdss clock, cx, mx (Linux proxy votes) - next thing to add before trying modem=1 again.
- 2026-11-26: **step 3 done** (kernel CI 45760100215, xnu 1046 + 1047, boot-args `modem=1 lv_serror=1`): PBL status 1, MBA status 2, metadata authenticated (3), 28 segments loaded (122644193 bytes), MBA status 4, SMP2P item 435 up, slave-kernel READY HANDOVER. What it took: RPM qdss clock (1046) was not enough alone - the kernel still died of an SError the instant the core ran (runs 2, 3); with SErrors recorded instead of fatal (1047, lv_serror=1) the boot goes through. Open: where that SError comes from (count was 0 one second after the release; it is not reported later yet). The modem reports FATAL 35 s later (no GLINK traffic, no host services): step 4.
- 2026-11-26: **steps 4 and 5 work, step 6 started** (kernel CI 45762295889, xnu to 1049, run e48). 1048: SMEM lookups read the cached list too (the modem's GLINK FIFO, item 480, is a cached entry) - VERSION/ACK, IPCRTR, QRTR HELLO, 41 services (nas, wds, dms, uim, wda, ipa, WLFW ...). 1049: rmtfs buffer is the fixed region 0x85E00000 + 2 MB shared HLOS+MSA (a pool address made the modem FATAL 15 ms later). WLFW: msa_info (0x85700000+0x4000 secure, +0xfc000), cap: chip_id 0x140 family 0x4002, board_id 0xff, fw WLAN.HL.1.0.1.c2-00811; MSA_READY indication not seen yet.
- Open: the modem dies 13.5 s after its start: `dog_hb.c:266:Task starvation: diag, ping: 4`. Two SErrors (esr 0xbf000002, asynchronous, pc random) arrive around its start. 1050 = diagnostics for both (modem_qdss=N, GLINK open acks, unserved QRTR packets, TZ log) and the firmware volume read 8 directories deep (mcfg files were not found).
- 2026-11-26: the diag starvation is the WLAN firmware. modem_wlfw=0 (1051): no crash. Bisect (1053, `tools/modem-bisect.ps1`, kernel CI 45766383364): stopping after ind_register, msa_info + assign, or msa_ready - no crash; sending `cap` - crash 12 s later; leaving host_cap out changes nothing. MSA assign returns 0. Chip supplies L5/L9/L6/L19 and RF_CLK1 voted through the RPM (1052), all acked, no change. MSA_READY indication never arrives, even when stopped after msa_ready. 1054 reads the regulators back from the PMIC. Boot-args: modem_wlfw=N, modem_wlhost=0, modem_wlpwr=0, modem_qdss=N, lv_serror=1.
- For plain modem work (telephony) use `modem=1 lv_serror=1 modem_wlfw=0`: the modem stays up.
- 2026-11-26, Wi-Fi firmware hang at `cap`, what is ruled out (kernel CI of 1056; each tested with `tools/modem-bisect.ps1`):
  - chip power: PM660 L5/L9/L6/L19 in regulation and RF_CLK1 on, read from the PMIC (1054);
  - SMMU: anoc2 (0x16C0000) has 6 SMRs, 21 CBs, USFCFG set, no fault recorded; stream 0x1a00/1 -> CB0 with translation off programs fine (1055, `modem_smmu=2`; bank 20 hung the thread) - no change;
  - message order: equals Android's icnss (ind_register, msa_info, assign, msa_ready, cap); host_cap left out or sent - no change; pin_connect_result_enable added (1056);
  - stale MSA contents: region zeroed before the assign (1056; it held 122525 non-zero words) - no change.
  Still unexplained: MSA_READY indication never arrives; two SErrors (esr 0xbf000002) at every modem start; TZ log ring printed no lines. Ideas not tried: 8-bit host_cap (ath10k "host-cap-8bit-quirk"), wlan_pd service-notifier state, reading the modem's crash/diag buffers through SMEM, vbatt/dynamic-feature messages after cap, comparing with a boot where Android ran just before (warm) versus a cold power-on.

## Telephony (step 10): CommCenter on the real modem

Survey, 2026-11-26 (root image 16.7.16, D22 = the Qualcomm "Mav" iPhone X; nothing of this existed in the earlier projects):

- CommCenter itself only loads libraries; the baseband is run by the AppleBasebandManager code (libBasebandManager.dylib: BootController, QMITransportService, QMIXpcServer, RouterDelegate, RouterIPCController) and reached through `libPCITransport.dylib`.
- libPCITransport probes the variant by which service exists: `AppleBasebandPCIControl` (Qualcomm, through `libIOABP.dylib`: classes IOABPControlClass, IOABPClass, IOABPTraceClass) or `AppleConvergedIPCBBControl` (Intel). Kernel services of the Qualcomm variant: `AppleBasebandPCIControl`, `AppleBasebandPCIInterface` (one per interface, property `ABPInterfaceProtocol`), `AppleBasebandPCITraceBackendRaw`, plus `AppleBaseband` (power/reset/properties, libTelephonyBasebandDynamic) and `AppleIPAppender` (PDP contexts, ApplePDPHelper) - the last two are today's empty stubs 1038/1036.
- The interface methods are pipes: open, read/write (async), readRegister (BHI/BTI registers), sendImage, map memory, time sync; the control service has events and a "last known boot stage"; libTelephonyBaseband reads an "ABP boot stage" registry property.
- QMI on Mav goes over Qualcomm's IPC router (`libmav_ipc_router_dynamic.dylib`, "MavRouter", RouterIPCController) - the protocol our modem already speaks to us as QRTR - and/or QMux pipes ("Mapping service %s to QMux %s"). Firmware in the image: `usr/standalone/update/Mav17.Release.bbfw`; the manager boots the modem through libBBUpdaterDynamic ("bootModem"), and has paths "Faking bootup", "Transport bypass enable", "skipping establishing transport", a `BootMode` key.

Design (CommCenter and its libraries stay untouched; the kernel offers the same services Apple's kext does, with the phone's modem behind them):

T1. The user-client ABI of libIOABP: selectors, arguments, async conventions, notifications (static analysis).
T2. Kernel services AppleBasebandPCIControl / AppleBasebandPCIInterface that accept and log everything, to see what the manager does first (which interfaces, registers, boot stage).
T3. Boot stage: present the modem as already running (it is: our kernel booted it), so the manager goes to its transport without pushing firmware. If it insists on its updater protocol, answer that protocol.
T4. The router pipe: IPC-router packets between the manager and TopazModem's QRTR (our own host services keep their ports).
T5. Services the Apple firmware has and this modem lacks (Apple-specific QMI services such as "bsp"): find which ones block, answer what is needed.
T6. SIM, registration, signal bars; then calls (voice audio path), SMS, data (PDP contexts through AppleIPAppender to a network interface).
Each step is checked from the USB log; a SIM card and a call need the user.

### Telephony log

- 2026-11-26, T1 done: `docs/ABP-ABI.md`. T2 (xnu 1057, `abp=1`): the services exist; CommCenter does not reach them yet.
- AppleBaseband user client decoded (libTelephonyBasebandDynamic): 0 ResetModem, 1 PowerOnModem, 2 EnableModemMux, 3 GetReset (out: non-zero = in reset), 6 PowercycleModem, 10 VoteDeviceWake, 15 identify (64-byte string), 16/17/18 GetDiagReady/GetFSEraseDone/GetResetReq, 20 APTimeSync, 22/23 Set/GetManagerState (0 stopped, 1 started), 26/27 Get/SetBasebandState, 28/29 Get/SetBasebandProperty, 32 ClearFreqList. Interest messages from the kernel: 0xE3FF8000 reset detected, 0xE3FF8001 baseband alive, 0xE3FF8007 wake, 0xE3FF800D coredump ready. Registry: `config` (timings) on the device-tree node `baseband`.
- The manager's start (libBasebandManager, inside CommCenter): init -> GetReset, GetManagerState, SetManagerState(0); start -> SetManagerState(1), BootModule: `capabilities::bb::abm::shouldBoot()` is a constant true (the "Faking bootup" path cannot be reached), BootControllerLegacy::prepare needs the personalized firmware path (MSUDataAccessor: /private/preboot/<boot-manifest-hash>/..., "Baseband Firmware Path Not Found" otherwise), then BBUpdater "performBootup": PowerOnModem(1), PCI interfaces pbl / sahara (image push), then diag ("Ping success"), then the event "booted"; FSModule serves `refs`, TransportModule opens qmux1/qmux2. There is no "already booted" shortcut: the kernel has to play the modem's side of the firmware push.
- Observed (xnu 1059, runs e60/e61): GetReset, identify, ClearFreqList(3), GetManagerState, SetManagerState(1), more identifies, abm-helper starts (identify x3, GetReset) - and nothing after: no PowerOnModem, no PCI open. Consistent with the firmware path check failing (/private/preboot is empty on our root). The device-tree node `baseband` (mkadt.py --baseband, shim/out/lavender-bb.adt) changes nothing in this sequence.
- Tools: `sweetstderr=NAME` (xnu 1058/1060) prints a process's stderr / date-prefixed log lines; CommCenter's launchd job gets OS_ACTIVITY_DT_MODE=YES in the local launchd.plist (a launchd.plist change takes effect from the second boot). `tools/cc-run.ps1` runs one telephony test boot.
- 2026-11-26: CommCenter's own log is readable (xnu 1058/1060/1061: stderr tap + AMFI dyld-policy bit 0x100 for the tapped process, OS_ACTIVITY_DT_MODE=YES in its launchd job). It named the stop: `FW path "/private/preboot/<boot-manifest-hash>/usr/local/standalone/firmware/Baseband/Mav17" does not exist` -> "Baseband is declared dead".
- xnu 1062: with abp=1 the kernel unpacks the root's `/usr/standalone/update/Mav17.Release.bbfw` into that folder (11 files, once). Run e64: the manager then calls PowerOnModem(1), opens an interface, reads boot registers 4/3/0 (OEMPkHash 96 bytes, MSMHwId 24, SerialNum 4) and reports `ChipID = 0 ... FusingStatus = 3; VendorID = 3`, fails "output did not return done", power-cycles and repeats. Firmware Info.plist: ChipId 0x0003B0E1. Matching bug found: ABPInterfaceProtocol must be compared in matchPropertyTable (it had opened "qdss").
- xnu 1063 (T3): boot-stage stand-in - off / rom ("pbl", registers) / sahara (device HELLO, END_IMAGE_TX, DONE_RESP) / mission (abp_ifs interfaces + "baseband alive"); boot-args abp_chip, abp_serial, abp_hold, abp_ifs.
- 2026-11-26, boot stand-in progress (runs e65-e67, xnu 1063-1066): interface matching by name works ("pbl" opened); registers accepted once the chip id sits at MSMHwId offset 4 and OEMPkHash carries the updater's "unfused" constant; sendImage on "pbl" (sbl1.mbn, 238208 bytes) accepted when the completion carries {size transferred, code}; the updater then opens "sahara", starts both channels, reads our HELLO, answers HELLO_RESP (version 1, mode 0) - and refuses END_IMAGE_TX sent right away: "BBUpdater error 12 - failed handling sahara mode operation". Next: the packet sequence a real loader sends in Sahara (image ids / Maverick extension commands).
- libPCITransport completion arguments (bh::generateCallback): read/write completion = size; sendImage completion = {size, code}; the client checks status 0 and size == requested size.
- xnu 1064: QMUX <-> QRTR bridge with CTL service is in the kernel (TopazModem.cpp), not exercised yet (needs the mission stage).
