# APR-PLAYBACK: smallest speaker tone on lavender (ADSP.VT.4.0, APR over GLINK)

Recipe for step A4 of AUDIO-PLAN: a kernel-generated 48 kHz / 16-bit / stereo tone from a physically
contiguous buffer -> ASM -> ADM -> AFE PRIMARY_MI2S_RX -> MAX98927 -> speaker.
Sources (public, GPL): LineageOS `android_kernel_xiaomi_sdm660` branch lineage-18.1 (msm-4.4, has
`CONFIG_MACH_LONGCHEER` bits): `include/linux/qdsp6v2/apr.h`, `drivers/soc/qcom/qdsp6v2/apr.c`,
`include/sound/apr_audio-v2.h`, `include/sound/q6core.h`, `sound/soc/msm/qdsp6v2/{q6afe,q6asm,q6adm,
q6core,q6common,msm-dai-q6-v2,msm-pcm-q6-v2,msm-pcm-routing-v2}.c`, `sound/soc/msm/sdm660-common.c`,
`drivers/soc/qcom/qdsp6v2/msm_audio_ion.c`, `drivers/pinctrl/qcom/pinctrl-sdm660.c`; Linux mainline
`sound/soc/codecs/max98927.{c,h}`. Local: stock DT `dump/miui-boot/split/dtb5.dts`, our log
`dump/usblog-e135-1.txt`, `xnu/src/mk_audio4.py`/`mk_audio5.py`.
**[R]** = read in that source, **[I]** = inferred. All structs are `__packed`, little endian.

## 1. APR header

### 1.1 Layout [R] `apr.h` struct apr_hdr — **20 bytes, not 16**

| Off | Size | Field | What we send |
|---|---|---|---|
| 0 | u16 | hdr_field = `(msg_type&3)<<8 \| (hdr_len_words&0xF)<<4 \| (ver&0xF)` | **0x0250** |
| 2 | u16 | pkt_size (header + payload, bytes) | |
| 4 | u8 | src_svc | = dest svc id (Linux `apr_send_pkt` copies svc->id to both) |
| 5 | u8 | src_domain | 5 (APPS) |
| 6 | u16 | src_port | see 1.3 |
| 8 | u8 | dest_svc | 3 core, 4 AFE, 7 ASM, 8 ADM |
| 9 | u8 | dest_domain | 4 (ADSP) |
| 10 | u16 | dest_port | see 1.3 |
| 12 | u32 | token | free; echoed in the answer |
| 16 | u32 | opcode | |

Every msm-4.4 command uses `APR_HDR_FIELD(APR_MSG_TYPE_SEQ_CMD=2, APR_HDR_LEN(APR_HDR_SIZE)=20/4=5,
APR_PKT_VER=0)` = **0x0250** [R] (q6afe `q6afe_set_params_v2`, q6asm `__q6asm_add_hdr`, q6adm
`adm_open_v5_v6`, q6core `core_get_license_status`).

**Bug in our client [R] `mk_audio4.py`:** `APR_HDR_FIELD_CMD 0x0140` = msg_type 1 (CMD_RSP), header
4 words = 16 bytes, while the packed struct (and what we transmit) is 20 bytes. GET_STATE/GET_VERSIONS
work only because they have no payload. With a payload the ADSP would start reading it at offset 16
(our opcode). **Use 0x0250 before any AFE/ASM/ADM command.**

### 1.2 The 32-byte answers [R] log e135 + `apr.c apr_cb_func`

Raw GET_STATE answer: `00240081 00000403 00000503 00000002 0001290d 04000102 028968d9 00000000 | 00000001`

| Words | Meaning |
|---|---|
| w0 | hdr_field 0x0081 (ver **1**, hdr 8 words = 32 bytes, msg_type 0), pkt_size 0x24 = 36 |
| w1..w4 | normal 20-byte header: src 3/4 port 0, dest 3/5 port 0, token 2, opcode 0x0001290D |
| w5..w7 | **12-byte extension** (not 16): w5 0x04000102 grows by 0x100 per ask (sequence byte), w6 grows with time (timestamp/tick), w7 0 [R values, I meaning] |
| w8 | payload: state 1 |

msm-4.4 `apr_cb_func` accepts `ver <= APR_PKT_VER + 1`, computes `hdr_size = ((hdr_field>>4)&0xF)*4`
and sets `payload = (char*)hdr + hdr_size`; it never interprets the extension [R]. So: always take the
payload offset from hdr_field (as mk_audio5 does), ignore w5..w7, keep sending v0 20-byte headers.
msg_type of answers is 0 (event) or 1 (CMD_RSP); do not filter on it.

### 1.3 Addressing, tokens, basic response [R]

| Service | dest_svc | src_port / dest_port | Linux token |
|---|---|---|---|
| core (AVCS) | 3 | 0 / 0 | 0 |
| AFE | 4 | 0 / 0 (port id goes in the payload) | AFE port index |
| ASM session cmds/data | 7 | `(session<<8)\|stream_id` both (session 1..15, stream 1) | `{u8 stream, u8 session, u8 buf_index, u8 flags}` (`union asm_token_struct`) |
| ASM mem map | 7 | 0 / 0 | session<<8\|dir |
| ADM open | 8 | AFE port id (0x1000) / same | `port_idx<<16 \| copp_idx` |
| ADM matrix map | 8 | 0 / 0 (src_svc 0 in Linux) | 0 |
| ADM close | 8 | 0x1000 / **copp_id** | |

`APR_BASIC_RSP_RESULT` = **0x000110E8**: payload `u32 opcode_of_command, u32 status` [R `apr.c`,
`q6asm_callback`]. Status: 0 EOK, 1 EFAILED, 2 EBADPARAM, 3 EUNSUPPORTED, 8 EHANDLE, 9 EALREADY,
0xA ENOTREADY [R `apr_audio-v2.h`]. `APR_RSP_ACCEPTED` 0x000100BE.
Our core answer 0x40002 = `AVCS_CMDRSP_Q6_ID_2_8` -> AVS 2.8 [R `q6core.h`].

### 1.4 Which API generation [R]

- `q6common_is_instance_id_supported()` is false unless user space sets a mixer control
  (`msm_routing_instance_id_support_put`) -> Linux uses **param_hdr_v1** (12 bytes) and
  `AFE_PORT_CMD_SET_PARAM_V2` / `AFE_SVC_CMD_SET_PARAM` (V1) [R `q6common.c`, `q6afe.c`].
- ADM: `adm_open` uses V8 only if `AVCS_CMD_GET_FWK_VERSION` (0x0001292C) reports ADM api >= 3;
  otherwise **ADM_CMD_DEVICE_OPEN_V5** [R `adm_open`, `adm_get_svc_version`]. V5 is fine for us [I].
- ASM: `q6asm_open_write()` = OPEN_WRITE_V3 + PCM fmt **V2** (0x00010DA5) [R]; Android on AVS 2.8 uses
  V4/V5 format blocks, but V2 is the base format every Elite ASM accepts [I].

## 2. AFE: clock + PRIMARY_MI2S_RX

Linux order [R]: BE startup `msm_mi2s_snd_startup` (clock) -> BE prepare `msm_dai_q6_mi2s_prepare`
-> `afe_port_start` (I2S config via SET_PARAM, then DEVICE_START). No calibration/topology is sent when
`afe_cal_mode` is NONE.

Lavender DT [R dtb5]: `qcom,msm-mi2s-master = <1 1 1 1>` (SoC is master -> IBIT, ws internal), no
`qcom,msm-mi2s-ext-mclk` (no MCLK sent), PRIM `qcom,msm-mi2s-rx-lines = <1>` (SD0, GPIO 14),
tx-lines 2 (SD1, GPIO 15, amp I/V feedback, not needed). `mi2s_rx_cfg[PRIM_MI2S] = {48000, S16_LE, 2}`
[R sdm660-common.c].

### 2.0 Pins [R pinctrl-sdm660.c + DT]
TLMM north tile 0x03900000, CFG = 0x03900000 + 0x1000*n: bits[1:0] pull, [5:2] func, [8:6] drive
(8 mA = 3), [9] OE. GPIO12 sck func **2**, GPIO13 ws func **3**, GPIO14 sd0 func **3**, (GPIO15 sd1
func 3). Values: GPIO12 **0x0C8**, GPIO13/14 **0x0CC** (DT also says output-high on sck/ws; OE bit 9
only matters in GPIO mode [I]). Sleep state = func 0, 2 mA, pull-down.

### 2.1 Clock: AFE_SVC_CMD_SET_PARAM [R `afe_set_lpass_clk_cfg`, `q6afe_svc_set_params_v1`]

| Off | Field | Value |
|---|---|---|
| 0 | apr_hdr | svc 4, ports 0, opcode **0x000100F3**, pkt_size **72** |
| 20 | u32 payload_size | 36 |
| 24 | mem_mapping_hdr {u32 lsw, u32 msw, u32 handle} | 0,0,0 (in-band) |
| 36 | param_hdr_v1 {u32 module, u32 param, u16 size, u16 rsvd} | 0x0001028F `AFE_MODULE_CLOCK_SET`, 0x00010290 `AFE_PARAM_ID_CLOCK_SET`, 24, 0 |
| 48 | afe_clk_set: u32 clk_set_minor_version | 1 |
| 52 | u32 clk_id | **0x100** `Q6AFE_LPASS_CLK_ID_PRI_MI2S_IBIT` (0x101 EBIT if slave) |
| 56 | u32 clk_freq_in_hz | **1536000** (0x177000 = 48000 * 2 ch * 16 bit, `update_mi2s_clk_val`) |
| 60 | u16 clk_attri | 1 `COUPLE_NO` |
| 62 | u16 clk_root | 0 `ROOT_DEFAULT` |
| 64 | u32 enable | 1 (0 to stop) |

Answer: BASIC_RSP {0x000100F3, 0}. (`AFE_PARAM_ID_LPAIF_CLK_CONFIG` 0x00010238 is the old v1 API; the
sdm660 machine driver only uses CLOCK_SET [R].)

### 2.2 Port config: AFE_PORT_CMD_SET_PARAM_V2 [R `__afe_port_start`, `q6afe_set_params_v2`, `msm_dai_q6_mi2s_hw_params`/`set_fmt`]

| Off | Field | Value |
|---|---|---|
| 0 | apr_hdr | svc 4, opcode **0x000100EF**, pkt_size 20+4+12+12+P |
| 20 | u16 port_id | **0x1000** `AFE_PORT_ID_PRIMARY_MI2S_RX` |
| 22 | u16 payload_size | 12 + P |
| 24 | mem_mapping_hdr | 0,0,0 |
| 36 | param_hdr_v1 | 0x0001020C `AFE_MODULE_AUDIO_DEV_INTERFACE`, 0x0001020D `AFE_PARAM_ID_I2S_CONFIG`, P, 0 |
| 48 | afe_param_id_i2s_cfg: u32 i2s_cfg_minor_version | 1 |
| 52 | u16 bit_width | 16 |
| 54 | u16 channel_mode | 1 `AFE_PORT_I2S_SD0` |
| 56 | u16 mono_stereo | 1 `AFE_PORT_I2S_STEREO` |
| 58 | u16 ws_src | 1 `WS_SRC_INTERNAL` (CBS_CFS: SoC master) |
| 60 | u32 sample_rate | 48000 |
| 64 | u16 data_format | 0 `AFE_LINEAR_PCM_DATA` |
| 66 | u16 reserved | 0 |

P: the i2s struct is 20 bytes; Linux sends `param_size = sizeof(union afe_port_config)` (larger, zero
padded) [R]. Start with P = 20; if the answer is EBADPARAM (2), resend zero-padded (e.g. P = 64) [I].
Answer: BASIC_RSP {0x000100EF, 0}.

### 2.3 AFE_PORT_CMD_DEVICE_START [R `afe_send_cmd_port_start`]
`apr_hdr` (opcode **0x000100E5**, pkt_size 24) + `u16 port_id 0x1000, u16 reserved 0`. Answer BASIC_RSP.
From here the bit clock and WS run (1.536 MHz / 48 kHz) and the AFE plays silence until ADM feeds it [I].
Stop: same struct, opcode **0x000100E6** `AFE_PORT_CMD_DEVICE_STOP`.

## 3. Shared memory and the LPASS SMMU

### 3.1 ASM_CMD_SHARED_MEM_MAP_REGIONS [R `q6asm_memory_map_regions`]

| Off | Field | Value |
|---|---|---|
| 0 | apr_hdr | svc 7, ports 0, opcode **0x00010D92**, pkt_size 40 |
| 20 | u16 mem_pool_id | **3** `ADSP_MEMORY_MAP_SHMEM8_4K_POOL` |
| 22 | u16 num_regions | 1 (contiguous) |
| 24 | u32 property_flag | **0** (bit0 0 = physical/IOVA address, 1 = already-mapped virtual) |
| 28 | {u32 shm_addr_lsw, u32 shm_addr_msw, u32 mem_size_bytes} | address (3.2), size multiple of 4 KB |

Answer `ASM_CMDRSP_SHARED_MEM_MAP_REGIONS` **0x00010D93**, payload `u32 mem_map_handle`; errors as
BASIC_RSP. Region: 4 KB aligned, size multiple of 4 KB; write buffers inside it 32-byte aligned, sizes
multiple of 32 bytes; msw bits 31..4 must be 0 (36-bit addresses) [R header comments].
Unmap at the end: **0x00010D94** `{apr_hdr, u32 mem_map_handle}`.

### 3.2 What address the ADSP gets [R `msm_audio_ion.c`]

DT `qcom,msm-audio-ion`: `qcom,smmu-enabled`, `qcom,smmu-version = <2>`, `iommus = <&lpass_q6 1>`.
Linux attaches an IOMMU domain (IOVA window 0x10000000 + 0x0FFFFFFF, `msm_audio_smmu_init`), maps the
ION buffer, and then `*addr |= smmu_sid_bits` with `smmu_sid_bits = SID << 32` -> **lsw = IOVA,
msw = 1** (`msm_audio_populate_upper_32_bits`). So the address bits 35:32 carry the SMMU stream id
and the HLOS owns the context bank of SID 1 [R]; the ADSP does no translation of its own [I].

Minimal for us [I] (same method that worked on the GPU SMMU, GPU-PLAN step 4, memory note
"SMMU hyp: plain ldr/str"):
1. Vote `hlos1_vote_lpass_adsp_smmu_clk` (GCC 0x0017D014 bit 0) and GDSC `hlos1_vote_lpass_adsp`
   (0x0017D034) on (DT `smmu-lpass_q6` clocks/vdd) [R addresses, I need].
2. LPASS SMMU 0x05100000 (size 0x40000, `qcom,skip-init`): read IDR0.NUMSMRG; scan SMRs (0x800+4n) for
   SID 1 (exact, no mask); if none, use a free entry < NUMSMRG: SMR = valid | ID 1, S2CR -> a free
   HLOS context bank, CB SCTLR.M = 0 (pass-through, IOVA = PA). Plain asm ldr/str only, log before
   each write, never touch entries >= NUMSMRG or attach-impl-defs.
3. Buffer in low RAM outside XNU and outside DT carve-outs (as for zap at 0x95000000), cleaned from
   the CPU cache before each WRITE (or mapped uncached).
4. Send lsw = PA, msw = 1. Fallbacks if WRITE_DONE never comes / LPASS SMMU fault: (a) a real
   stage-1 table mapping IOVA 0x10000000 -> buffer PA (Linux-identical address), (b) msw = 0.

## 4. ADM: COPP on the AFE port + matrix route

Linux order [R `msm_pcm_playback_prepare`]: ASM open -> `msm_pcm_routing_reg_phy_stream` (adm_open,
adm_matrix_map) -> ASM media format. Default ADM topology without ACDB = `NULL_COPP_TOPOLOGY`
[R `msm_routing_get_adm_topology`].

### 4.1 ADM_CMD_DEVICE_OPEN_V5 [R `adm_open_v5_v6`, `adm_arrange_mch_map`]

| Off | Field | Value |
|---|---|---|
| 0 | apr_hdr | svc 8, src_port = dest_port = 0x1000, opcode **0x00010326**, pkt_size 48 |
| 20 | u16 flags | 0 `ADM_LEGACY_DEVICE_SESSION` |
| 22 | u16 mode_of_operation | 1 `RX_PATH_COPP` (ADM_PATH_PLAYBACK) |
| 24 | u16 endpoint_id_1 | 0x1000 |
| 26 | u16 endpoint_id_2 | 0xFFFF |
| 28 | u32 topology_id | **0x00010312** NULL_COPP (alt. 0x00010314 DEFAULT_COPP) |
| 32 | u16 dev_num_channel | 2 |
| 34 | u16 bit_width | 16 |
| 36 | u32 sample_rate | 48000 |
| 40 | u8 dev_channel_mapping[8] | 1 (FL), 2 (FR), 0... |

Answer `ADM_CMDRSP_DEVICE_OPEN_V5` **0x00010329**: `u32 status, u16 copp_id, u16 reserved`
(copp_id 0xFFFF = invalid). Keep copp_id.

### 4.2 ADM_CMD_MATRIX_MAP_ROUTINGS_V5 [R `adm_matrix_map`]

| Off | Field | Value |
|---|---|---|
| 0 | apr_hdr | svc 8, ports 0, opcode **0x00010325**, pkt_size 36 |
| 20 | u32 matrix_id | 0 `ADM_MATRIX_ID_AUDIO_RX` |
| 24 | u32 num_sessions | 1 |
| 28 | u16 session_id, u16 num_copps | ASM session (1), 1 |
| 32 | u16 copp_id, u16 pad | copp_id from 4.1, 0 |

Answer BASIC_RSP {0x00010325, 0}. Close: `ADM_CMD_DEVICE_CLOSE_V5` **0x00010327**, header only,
src_port 0x1000, dest_port copp_id.

## 5. ASM: stream, format, data

Session 1, stream 1 -> ports 0x0101 [R `__q6asm_add_hdr`].

| # | Command | Payload after the 20-byte header | Answer |
|---|---|---|---|
| a | `ASM_STREAM_CMD_OPEN_WRITE_V3` **0x00010DB3** (36 B) | u32 mode_flags 0 (legacy); u16 sink_endpointype 0 (matrix); u16 bits_per_sample 16; u32 postprocopo_id **0x00010BE4** DEFAULT_POPP (Linux default without cal; alt. 0x00010C68 NULL_POPP); u32 dec_fmt_id **0x00010DA5** MULTI_CHANNEL_PCM_V2 | BASIC_RSP |
| b | `ASM_DATA_CMD_MEDIA_FMT_UPDATE_V2` **0x00010D98** (44 B) | u32 fmt_blk_size 20; u16 num_channels 2; u16 bits_per_sample 16; u32 sample_rate 48000; u16 is_signed 1; u16 reserved 0; u8 channel_mapping[8] = 1,2,0.. | BASIC_RSP |
| c | `ASM_DATA_CMD_WRITE_V2` **0x00010DAB** (52 B) | u32 buf_addr_lsw; u32 buf_addr_msw (1); u32 mem_map_handle; u32 buf_size; u32 seq_id (buffer index); u32 timestamp_lsw 0; u32 timestamp_msw 0; u32 flags **0** (Linux NO_TIMESTAMP 0xFF00 -> 0; bit31 ts valid, bit30 last buffer) | `ASM_DATA_EVENT_WRITE_DONE_V2` **0x00010D99**: u32 addr_lsw, addr_msw, mem_map_handle, status; token echoed (Linux puts buf_index in token byte 2) |
| d | `ASM_SESSION_CMD_RUN_V2` **0x00010DAA** (32 B) | u32 flags 0 (RUN_IMMEDIATE); u32 time_lsw 0; u32 time_msw 0 | BASIC_RSP |
| stop | `ASM_SESSION_CMD_PAUSE` 0x00010BD3, `ASM_STREAM_CMD_FLUSH` 0x00010BCE, `ASM_STREAM_CMD_CLOSE` 0x00010BCD (header only) | | BASIC_RSP each |

[R `__q6asm_open_write`, `__q6asm_media_format_block_pcm`, `q6asm_write`, `q6asm_run`,
`msm_pcm_trigger`]. Data: interleaved L,R s16 little endian. Tone suggestion: 1 kHz sine at
-12 dBFS: 48 frames per cycle, so 3840-byte buffers (20 ms) hold exactly 20 cycles and loop without
clicks; 4 such buffers in one 16 KB region, resubmit each on its WRITE_DONE.

## 6. MAX98927 (I2C 0x3A, 16-bit register address MSB first, 8-bit data) [R mainline max98927.c]

Write = `S 0x74 regH regL val P`; read = `S 0x74 regH regL Sr 0x75 val P`. DT node is
`maxim,max98927L` with `mono_stereo_mode 0`, `interleave_mode 0`, reset GPIO 77 [R dtb5]; Xiaomi's
own driver is not public in the LineageOS tree, so values below are mainline's [R] and Xiaomi's may
differ [I].

| Step | Reg | Value | Source |
|---|---|---|---|
| reset | GPIO 77 high (release), wait **5-6 ms** | | `max98927_i2c_probe` usleep_range(5000,6000) |
| ID | 0x01FF REV_ID | expect **0x40** (reg default) | probe; our A1 read 0x00 -> retry after the 5 ms wait |
| soft reset | 0x0100 | 0x01 | `max98927_probe` |
| IV slots Hi-Z | 0x001C, 0x001D | 0xFF, 0xFF | probe |
| mono mix | 0x0025 | 0x80 (CFG bits 7:6 = 2 "LeftRight" -> (L+R)/2) | probe |
| | 0x0026 | 0x01 | probe |
| volume | 0x0036 AMP_VOL | 0x38 | probe ("initial volume") |
| gain | 0x003C SPK_GAIN | 0x05 | probe |
| DC blocker | 0x0037 | 0x03 | probe |
| IV DC blocker | 0x003F | 0xF7 | probe |
| boost | 0x0040, 0x0042 | 0x1C, 0x3E | probe |
| meas ADC | 0x0043, 0x0044, 0x0045 | 0x04, 0x00, 0x24 | probe |
| brownout | 0x007F | 0x06 | probe |
| env. tracking | 0x0082, 0x0086, 0x0087 | 0x08, 0x01, 0x10 | probe |
| IV slots | 0x001E (I slot 1, V slot 0) | 0x10; then TX_EN_A 0x001A bits 0,1 set, HIZ_A bits 0,1 cleared (only matters for feedback) | probe |
| slave | 0x0021 | 0x00 | `set_fmt` CBC_CFC |
| I2S, 16-bit | 0x0020 PCM_MODE_CFG | **0x40** (format I2S 0 in bits 5:3, CHANSZ_16 bits 7:6 = 1, BCLK edge normal) | `set_fmt` + `hw_params` |
| RX ch0+1 | 0x0018 | 0x03 | `set_fmt` |
| PCM source | 0x003B = 0x00, 0x0035 = 0x00 (no PDM) | | `set_fmt` |
| BCLK/LRCLK | 0x0022 low nibble | **2** (32 BCLK per frame -> index 0 + 2); default 0x22 stays 0x22 | `max98927_set_clock` |
| rate | 0x0023 = **0x08** (48 kHz); 0x0024 = **0x88** (SR 8 << 4 \| IV-ADC SR 8, interleave off) | | `hw_params` |
| **enable** (after AFE DEVICE_START, BCLK running) | 0x003A AMP_EN | 0x01 | `max98927_dac_event` POST_PMU |
| | 0x00FF GLOBAL_SHDN | 0x01 | POST_PMU |
| disable (before AFE stop) | 0x00FF = 0, then 0x003A = 0 | | POST_PMD |

Order matters [I]: Linux applies set_fmt/hw_params while the link is set up and enables the amp only
in DAPM POST_PMU, i.e. after the CPU DAI started the clocks. Enable with BCLK/LRCLK present; check
INT_RAW1..3 (0x0001-0x0003) / INT_STATE1..3 (0x0004-0x0006) and 0x0011 CLK_MON after enable (bit
meanings are in the datasheet, not in the driver).

## 7. Full order, risks, clean stop

**Order** (each step waits for its answer, 5 s Linux timeout):
1. Fix hdr_field to 0x0250. 2. Amp: reset release, REV_ID, init table (6) without enable.
3. Pins GPIO12-15 to pri_mi2s. 4. SMMU SID 1 pass-through + buffer + tone (3.2).
5. AFE clock enable (2.1). 6. AFE I2S config (2.2). 7. AFE DEVICE_START (2.3).
8. ASM mem map (3.1) -> handle. 9. ASM OPEN_WRITE_V3. 10. ADM DEVICE_OPEN_V5 -> copp_id.
11. ADM MATRIX_MAP session 1 -> copp. 12. ASM MEDIA_FMT_UPDATE_V2. 13. 4 x ASM WRITE_V2.
14. ASM RUN_V2. 15. Amp AMP_EN, GLOBAL_EN. 16. Loop: resubmit on WRITE_DONE.

**Clean stop** (Linux `msm_pcm_playback_close` + BE shutdown order [R]): amp GLOBAL_EN 0, AMP_EN 0 ->
ASM PAUSE -> ASM CLOSE -> ASM UNMAP (0x00010D94) -> ADM CLOSE_V5 -> AFE DEVICE_STOP -> AFE clock
enable = 0 -> pins to sleep state -> (optionally) amp reset low.

**Risks / do-not-touch**
- Wrong hdr_field (today's 0x0140): payload misparsed -> wrong ports/addresses reach the DSP [R/I].
- A DMA address the LPASS SMMU cannot translate -> context fault; the ADSP may take a fatal error. An
  ADSP crash cannot be recovered without SoC reset (stale SMEM, AUDIO-PLAN 5) -> costs a reboot; watch
  SMEM 423 crash reason and SMP2P after every new command [I].
- Starting PRIMARY_MI2S without its IBIT clock, or two different configs on RX/TX of the same MI2S
  (Linux rejects mismatched rate/bitwidth, `msm_dai_q6_mi2s_hw_params`) [R]; do not start PRI_MI2S_TX.
- Do not touch: LPASS registers 0x15000000+ (ADSP-owned), LPI TLMM, SMMU entries other than SID 1,
  SMRs >= NUMSMRG, attach-impl-defs; no AFE commands to INT0/INT3/SLIMBUS ports; no ACDB/topology
  commands (`ADM_CMD_ADD_TOPOLOGIES`, AFE cal) in this test.
- Speaker has no protection running: keep the tone at -12 dBFS or lower, short (seconds).
- Do not pulse GPIO 77 while playing (it is also the TFA98xx/TAS2557 reset line in DT).
- Keep the ADSP alive between runs; tear down with the clean-stop order instead of rebooting the DSP.
