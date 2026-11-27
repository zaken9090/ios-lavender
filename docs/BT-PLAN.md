# BT-PLAN: Bluetooth on lavender (WCN3990 BT over UART) for iOS 16.7.16 (iPhone X user space)

## Hardware (stock device tree)

- `bt_wcn3990`: supplies PM660 L9 1.8 V (core), L6 1.3 V (PA), L19 3.3 V (LDO), PM660L BOB pin (chip power); clock RF_CLK1. Same rails and clock as the Wi-Fi part.
- UART `uart@c1af000` (BLSP2 UART1, UARTDM v1.4, BAM at 0xc184000 not used), GPIO 16 TX, 17 RX, 18 CTS, 19 RFR (TLMM centre tile 0x03500000, function 1 "blsp_uart5"). GCC: blsp2_uart1_apps_clk_src RCG2 at 0x2700c, branch 0x27004, blsp2_ahb vote 0x52004 bit 15.
- Firmware: partition `bluetooth` (mmcblk0p38), FAT16 with 4096-byte sectors: image/crbtfw21.tlv (rampatch) + crnv21.bin (NVM) for WCN3990 2.1 (also 1.1/2.0 and "ap" variants).
- Bluetooth address: modem NV item 447 (read via DIAG, xnu 1084; stored reversed).
- Linux bring-up (hci_qca/btqca): rails on; host 2400 baud, pulse 0xC0 (off); host 115200, pulse 0xFC (on); 100 ms; EDL version 0xFC00 {0x19} -> vendor event; rampatch + NVM as TLV segments (0xFC00 {0x1E, len, data}); baud change; set BD_ADDR (NVM tag 2 via 0xFC0B, or 0xFC14); HCI reset.

## What iOS expects (analysis of bluetoothd, BlueTool, the D22 kernel cache)

- bluetoothd: local address from env BT_DEVICE_ADDRESS, else the IORegistry service named "marconi-bt"/"bluetooth" (`local-mac-address`, 6 bytes, all-zero = "No bluetooth on this device", exit). Port check: /dev/cu.bluetooth or /dev/uart.bluetooth, or that service. Transport from env BT_HCI_TRANSPORT or the node's `transport-encoding` (D22: 3 = H4BC, driver POSIX) and `transport-speed` (D22: 3000000).
- Data path on D22: kernel control socket "com.apple.uart.sk.bluetooth" (AppleOnboardSerial; Skywalk channel via sockopts IOAOSSKYSETCHANNELSPEC/GETCHANNELUUID). With BT_HCI_TRANSPORT="H4BC:POSIX:<name>,<speed>" bluetoothd uses plain read/write on control <name> instead.
- BlueTool (`/usr/sbin/BlueTool -R`, XPC com.apple.BlueTool) boots the chip for bluetoothd: kernel control "com.apple.uart.bluetooth" (termios via sockopts level 2), /dev/btpoweroff (open = off, close = on), /dev/btwake. Script: power cycle, HCI reset, 0xFC18 baud, 0xFC2E Download_Minidriver + 835 x 0xFC4C Write_RAM + 0xFC4E Launch_RAM (Broadcom firmware built into BlueTool), 0xFC18, 0xFC01 Write_BD_ADDR, name, 0xFD18/0xFD97/0xFD1E calibration, power table, 0xFC27 sleep mode. Every reply: Command Complete, status 0.
- Chip identification: HCI_Read_Local_Version must report manufacturer 15 (Broadcom) and LMP subversion 0x420E (BCM4357B1); MobileGestalt ProductHash / WifiVendor pick the script.

## Plan

- B1 (xnu 1085): power, UART, pulses, EDL version, HCI reset, local version - logged.
- B1 result (xnu 1087): with RTS/CTS on after the pulses the chip answers HCI (manufacturer 0x1D).
- B2 (xnu 1088, in test): UARTDM stale/SNAP receive, FAT16 reader, rampatch + NVM (tag 17 baud 115200, tag 27 deep sleep off), address via 0xFC14; 3 Mbit/s later.
- B2 result (xnu 1088-1093): crnv21.bin is a type-4 container (BT NVM type 2 + FM NVM type 3); the BT NVM's tag 17 holds baud 0x11 (3.2 Mbit/s) - edited to 115200, no in-band sleep. After rampatch + NVM: NOP Command Complete, HCI_Reset 0, Read_Local_Version HCI 9 / LMP 9 / manufacturer 0x1D / subversion 0x2BE. 0xFC14 takes the address in written order (NV 447 is stored reversed); Read_BD_ADDR confirms.
- B3 (xnu 1093-1095): mkadt.py --bt adds arm-io/uart1/bluetooth (D22 props, zero address); the kernel writes local-mac-address and publishes nubs for uart1's children; kernel control com.apple.uart.bluetooth (stream, TIOCGETA/TIOCSETA sockopts at level 2, raw H4); vendor opcodes >= 0xFC00 answered locally. bluetoothd job env BT_HCI_TRANSPORT=H4BC:POSIX:com.apple.uart.bluetooth,3000000 (local launchd.plist) avoids Skywalk. Result: bluetoothd reads the address and transport 3, asks BlueTool "boot"; BlueTool finds platform fd079b29... but MobileGestalt WifiVendor fails (Manufacturer -1, chip null) -> no firmware entry, "No WiFi - Iteration N".
- B4 (xnu 1096-1103): AppleOLYHAL service with vendor-id "Murata" (MobileGestalt WifiVendor -> BlueTool picks the D22 entry, fwPos 30); RX cut into whole H4 packets; Qualcomm debug ACL (handle 0x2EDC/0x2EDD) kept in the kernel; Read_Local_Version reported as manufacturer 15 / subversion 0x420E; Read_Local_Supported_Commands gets octet 18 bits 2/3 and 0x0C5A/0x0C5B are answered locally; vendor opcodes answered with status 0 + echo of their parameters (Broadcom meta VSCs check the sub-opcode). Result: BlueTool boot + init = 0, bluetoothd "Stack initialization complete", STACK_READY, LE/AFH/antenna VSCs status 0. Open: Settings shows no Bluetooth row; host UART still 115200 (termios 3000000 ignored); RX polled every 1 ms (power).
- B5 (xnu 1104-1115): /chosen mac-address-bluetooth0 / -wifi0 (MobileGestalt "bluetooth" capability -> Settings row; lv_mgreset=1 renames the MG cache once); receive fix: IPR.RXSTALE_LAST (1112) + DMRX/stale re-armed after every batch as Linux msm_handle_rx_dm (1113) - before, after the chip's long 0x2EDC debug ACL no stale event fired and partial last words stayed in the UART; tries 1106/1107-IMR-kept/1109/1090/1089/1110/1111 removed in 1114 (traces behind bt_debug=1); vendor answers = status + parameter echo + zeros to 32 bytes (1115; Broadcom parsers check minimum lengths, 0xFD1B FACTORY_CAL_READ_TABLE needs 2). Result e130: Settings > Bluetooth on, "discoverable as iPhone", scanning; bluetoothd receives LE advertisements.
- Run bp1 (xnu 1136, 2026-11-27): the user's headset is seen, connects, pairs (SSP, link key, encryption), SDP/HFP/A2DP connect, the headset plays its tone, then the link drops ("disconnected" on the phone); 1339 stray zero bytes in the receive path. 1137: outside a stale event only RXFS's full words are read. **Queued (user): retest the headset with 1137.**
- Open: pairing/audio test with a real device (user); stray 0x00 bytes logged now and then (rx: stray byte); host UART 115200 (BlueTool asks 3 Mbit/s); RX polled each 1 ms (interrupt later); BlueTool power off/on is a no-op (/dev/btpoweroff absent).
- Local userland change (not committed, Apple file): launchd.plist bluetoothd job env BT_HCI_TRANSPORT=H4BC:POSIX:com.apple.uart.bluetooth,3000000 and OS_ACTIVITY_DT_MODE=YES (BlueTool too) for logs.
- BlueTool contract (static analysis): device -D, wake on, power off/on (/dev/btpoweroff, absent = no-op), hci reset, FC18, FC2E + HCD records, FC01, 0x0C13, calibration, FC27; each must give Command Complete with ncmd 1, opcode, status 0; no version check.
- B2 goal: Qualcomm firmware (rampatch, NVM) from the bluetooth partition, BD address from NV 447, baud 3 Mbit/s with flow control; the controller answers standard HCI.
- B3: kernel side for iOS: the "bluetooth" registry node (address, transport-encoding 3), /dev/btpoweroff, /dev/btwake, kernel control "com.apple.uart.bluetooth" (and the Skywalk one, or the BT_HCI_TRANSPORT route), all on top of the B2 driver.
- B4: translation layer in the kernel control: Broadcom boot commands (FC18, FC2E, FC4C, FC4E, FC01, FC27, FD18/FD97/FD1E, ...) answered locally (FC01 -> Qualcomm address), Read_Local_Version rewritten (manufacturer 15, subversion 0x420E), Qualcomm vendor events and sleep bytes filtered; runtime Broadcom VSCs answered or refused.
- B5: Settings shows Bluetooth on, scan finds devices; pairing needs the user.
- Headset retest (2026-11-27, xnu 1149, run bt2): connects, then drops; the BT switch in Settings
  restarts. Cause: **bluetoothd crashes** (SIGSEGV, far 0) in `os_channel_get_fd(NULL)` from its
  "AudioSkywalkPipeReadLoop" thread, right after "Publishing audio device ... on a2dpHandle": the A2DP
  audio path goes through a Skywalk user-pipe nexus that bluetoothd creates itself ("Created skywalk
  nexus provider", AudioSkywalkProvider / nexus_controller); the channel open failed and was not
  checked. The decision is a virtual call ("Device supports Skywalk Path"). Next: bluetoothd's own log
  (sweetstderr=bluetoothd / OS_ACTIVITY_DT_MODE) for the nexus error, then the kernel's Skywalk
  user-pipe nexus (os_nexus_controller_create / os_channel_create) on our xnu. Symbols: WSL
  /root/dsc (ipsw), bluetoothd from /root/ipsw/os.dmg (apfs-fuse /mnt/os).
