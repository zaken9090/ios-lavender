# ABP-ABI: what user space expects from Apple's baseband PCI services

Read from `libIOABP.dylib`, `libPCITransport.dylib`, `libTelephonyBasebandDynamic.dylib` of iOS 16.7.16 (D22), 2026-11-26. Used by `xnu/src/mk_abp.py`. "Inferred" marks what was not read directly from code.

## Services

| Kernel service | Found by | Opened with |
|---|---|---|
| `AppleBasebandPCIControl` | `IOServiceMatching` by class | `IOServiceOpen(type 0)` |
| `AppleBasebandPCIInterface` | class + string property `ABPInterfaceProtocol` = name; first-match and terminate notifications | `IOServiceOpen(type 0)` |
| `AppleBasebandPCITraceBackendRaw` | class; property `TracePipes` (array of `{Code: number, Name: string}`), `SnapshotBufferSize` | `IOServiceOpen(type 0)` |

libPCITransport picks the Qualcomm variant when `AppleBasebandPCIControl` exists (Intel: `AppleConvergedIPCBBControl`).

Interface names by PCITransportInterface number: 0 pbl, 1 sahara, 2 diag, 3 refs, 4 qmux1, 5 qmux2, 6 rom, 7 boot, 8 ari, 9 trace, 10 at, 11 dpl, 12 mediactl, 13 vcom, 14 gnss, 15 qdss, 17 virtual_timesync, 20 boot_logger.

Control properties: `bootstage` (number; libTelephonyBaseband: below 2 = "boot stage down"), `logSnapshotBufferSize` (number).

## Notifications (general interest)

- Control: message type `0xE3FF8100`, argument = 24 bytes `{u32 errorType, u32 pad, u64 arg1, u64 arg2}`.
- Interface: message type `0xE3FF8101`, same 24 bytes with 32-bit values `(errorType, unsigned, int)`.
- Inferred: the kernel sends them with `messageClients(type, &payload, 24)`.

## External methods

All async calls: `IOConnectCallAsyncScalarMethod`, async reference of 8 words with `[1]` = callback, `[2]` = refcon, 3 used. The number of completion arguments follows the callback's C signature (inferred); their meaning is not known from the library.

Control user client:

| Sel | Method | Scalars in | Async completion |
|---|---|---|---|
| 0 | open | {0} | - |
| 1 | close | - | - |
| 2 | readLogsAsync | {buffer, size, bool} | 1 argument |
| 3 | loggerTune | {subsystem, index, arg1, arg2} | - |

Interface user client (selectors 2, 3, 4 serve both forms; the async form has a wake port):

| Sel | Method | Sync form | Async form | Async completion |
|---|---|---|---|---|
| 0 | open | scalars {0} | | |
| 1 | close | | | |
| 2 | write | scalars {0,0}, struct in = data | scalars {buffer, size} | 1 argument |
| 3 | read | scalars {0,0}, struct out = data | scalars {buffer, size} | 1 argument |
| 4 | sendImage | scalars {0,0}, struct in; 2 scalars out | scalars {buffer, size} | 2 arguments |
| 5 | readRegister | scalars {register}, struct out | | |
| 6 | abortChannelAsync | | {direction} | 0 |
| 7 | startChannelAsync | | {direction} | 0 |
| 8 | timeSyncAsync | | {a, buffer, size} | 1 |
| 9 | mapMemoryAsync | | {id, buffer, size} | 0 |
| 10 | unmapMemoryAsync | | {id} | 0 |
| 11 | registerTimeEvent | | {id} | repeating, 3 or more arguments |
| 12 | deregisterTimeEvent | | {id} | 0 |

Async buffers are user virtual addresses of the calling task. Direction: 0 in, 1 out. Registers (BHI): 0 SerialNum, 1 SBLAntiRollover, 2 NumSeg, 3 MSMHwId, 4 OEMPkHash; (BTI): 0 ChipInfo. Link states: 0 Up, 1 UnpoweredUp, 2 SoftDown, 3 HardDown, 4 ManualDown.

Trace user client: 0 readLogsAsync {pipe, buffer, size, bool}; 1 flushTraceBuffers {u32, bool}; 2 dumpRegistry; 3 getRegistryInfo (struct out 0x24); 4, 5 getTraceCode (struct out 0x7EC, 0x100); 6 demo.

Error types (`abpErrorType`, 0..49) include 18 PipeOpenFailed, 21-24 device state errors, 34 SendImageFailed, 37 ControlUnexpectedExecutionEnvironment, 38 ReadFail, 39 LinkDown.
