"""lavender: the boot stand-in answers what Apple's updater checks (patch 1065), telephony T3.

From libBBUpdaterDynamic / libETL* (BBUEUR13Loader::queryChipInfo, the Sahara parsers,
ETLMaverickGetBasebandInitStatusEx):
- MSMHwId (24 bytes): the chip id is the u32 at offset 4 (1063 had it at 0: "ChipID = 0").
- OEMPkHash (96 bytes): the first 32 bytes are compared with a built-in constant; equal means an
  unfused baseband (FusingStatus 1), anything else a fused one (3). The constant is returned
  unless abp_fused=1 (then zeroes, as before).
- Sahara DONE_RESP: image_tx_status 0 = all images done (1063 sent 1 = more to come).
- Both boot interfaces, "pbl" and "sahara", exist in the rom stage, with the Sahara HELLO waiting:
  whichever way the updater pushes its loader, it finds its endpoint. An image sent on "pbl" is
  accepted and changes nothing else.
- "diag" in the mission stage: QC DIAG in HDLC frames (CRC-16 X.25, 0x7E end, 0x7D escape). The
  updater's readiness ping, subsystem command 4B FD 51 00, is answered with status 1; any other
  request is logged and answered with DIAG's "bad command" (0x13 + the request).

usage: python mk_abp3.py XNU_TREE   (after mk_qmux.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/SweetWatchdog.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


sub('''			if (in[0] == 0) {
				reg[0] = lv_abp_serial;
			} else if (in[0] == 3) {
				reg[0] = lv_abp_chip;
			}
''', '''			if (in[0] == 0) {
				reg[0] = lv_abp_serial;
			} else if (in[0] == 3) {
				reg[1] = lv_abp_chip;                   /* the updater reads the chip id at offset 4 */
			} else if (in[0] == 4 && !lv_abp_fused) {
				/* the hash the updater takes for an unfused baseband (its built-in default) */
				static const uint8_t unfused[32] = {
					0xcc, 0x31, 0x53, 0xa8, 0x02, 0x93, 0x93, 0x9b, 0x90, 0xd0, 0x2d, 0x3b, 0xf8, 0xb2, 0x3e, 0x02,
					0x92, 0xe4, 0x52, 0xfe, 0xf6, 0x62, 0xc7, 0x49, 0x98, 0x42, 0x1a, 0xda, 0xd4, 0x2a, 0x38, 0x0f,
				};
				bcopy(unfused, reg, sizeof(unfused));
			}
''')
sub('''static uint32_t lv_abp_stage, lv_abp_hold, lv_abp_ifs = 0xfe3c, lv_abp_chip = 0x0003B0E1, lv_abp_serial = 1;
''', '''static uint32_t lv_abp_stage, lv_abp_hold, lv_abp_ifs = 0xfe3c, lv_abp_chip = 0x0003B0E1, lv_abp_serial = 1, lv_abp_fused;
''')
sub('''		(void)PE_parse_boot_argn("abp_hold", &lv_abp_hold, sizeof(lv_abp_hold));
''', '''		(void)PE_parse_boot_argn("abp_hold", &lv_abp_hold, sizeof(lv_abp_hold));
		(void)PE_parse_boot_argn("abp_fused", &lv_abp_fused, sizeof(lv_abp_fused));
''')
sub('''	uint32_t want = stage == LV_ABP_ROM ? 1u << 0 : stage == LV_ABP_SAHARA ? 1u << 1 : stage == LV_ABP_MISSION ? lv_abp_ifs : 0;
''', '''	uint32_t want = stage == LV_ABP_ROM || stage == LV_ABP_SAHARA ? 3u : stage == LV_ABP_MISSION ? lv_abp_ifs : 0;
	bool had_sahara = lv_abp_if[1] != NULL;
''')
sub('''	if (stage == LV_ABP_SAHARA && lv_abp_if[1] != NULL) {''', '''	if ((stage == LV_ABP_ROM || stage == LV_ABP_SAHARA) && lv_abp_if[1] != NULL && !had_sahara) {''')
sub('''		w[0] = 6; w[1] = 12; w[2] = 1;
''', '''		w[0] = 6; w[1] = 12; w[2] = 0;                 /* image_tx_status 0: all images done */
''')
sub('''	if (fItf == NULL || fItf->fIndex != 1 || len < 8) {
		return;                                 /* besides QMUX only the Sahara endpoint answers so far */
	}
''', '''	if (fItf != NULL && fItf->fIndex == 2) {
		diagSide(data, len);
		return;
	}
	if (fItf == NULL || fItf->fIndex != 1 || len < 8) {
		return;
	}
''')
sub('''	void modemSide(const uint8_t *data, uint32_t len);
''', '''	void modemSide(const uint8_t *data, uint32_t len);
	void diagSide(const uint8_t *data, uint32_t len);
''')
sub('''/* what the "modem" does with data the client wrote */
''', '''/* CRC-16 of HDLC (X.25): reflected 0x1021, start 0xffff, inverted at the end */
static uint16_t
lv_crc16(const uint8_t *p, uint32_t n)
{
	uint16_t crc = 0xffff;
	while (n-- != 0) {
		crc ^= *p++;
		for (int i = 0; i < 8; i++) {
			crc = (crc & 1) ? (uint16_t)((crc >> 1) ^ 0x8408) : (uint16_t)(crc >> 1);
		}
	}
	return (uint16_t)~crc;
}

/* QC DIAG requests on "diag", HDLC framed */
void
SweetABPUserClient::diagSide(const uint8_t *data, uint32_t len)
{
	uint8_t req[256], rsp[272], out[560];
	uint32_t n = 0, rn = 0, on = 0;

	for (uint32_t i = 0; i < len && n < sizeof(req); i++) {         /* unescape up to the flag */
		if (data[i] == 0x7e) {
			if (n == 0) {
				continue;
			}
			break;
		}
		if (data[i] == 0x7d && i + 1 < len) {
			req[n++] = data[++i] ^ 0x20;
		} else {
			req[n++] = data[i];
		}
	}
	if (n < 3) {
		IOLog("LV ABP diag: %u bytes, no frame\\n", len);
		return;
	}
	bool crc_ok = lv_crc16(req, n - 2) == (uint16_t)(req[n - 2] | (req[n - 1] << 8));
	n -= 2;
	if (n >= 4 && req[0] == 0x4b && req[1] == 0xfd && req[2] == 0x51 && req[3] == 0x00) {
		/* the updater's "baseband init status": the same header, then a u32, non-zero = ready */
		bcopy(req, rsp, 4);
		rsp[4] = 1; rsp[5] = 0; rsp[6] = 0; rsp[7] = 0;
		rn = 8;
		IOLog("LV ABP diag: init status asked (crc %s) -> ready\\n", crc_ok ? "ok" : "BAD");
	} else {
		rsp[0] = 0x13;                              /* DIAG_BAD_CMD_F + the request */
		bcopy(req, rsp + 1, n);
		rn = 1 + n;
		IOLog("LV ABP diag: request %02x %02x %02x %02x (%u bytes, crc %s) -> bad command\\n", req[0], n > 1 ? req[1] : 0,
		    n > 2 ? req[2] : 0, n > 3 ? req[3] : 0, n, crc_ok ? "ok" : "BAD");
	}
	uint16_t crc = lv_crc16(rsp, rn);
	rsp[rn++] = (uint8_t)crc;
	rsp[rn++] = (uint8_t)(crc >> 8);
	for (uint32_t i = 0; i < rn; i++) {
		if (rsp[i] == 0x7e || rsp[i] == 0x7d) {
			out[on++] = 0x7d;
			out[on++] = rsp[i] ^ 0x20;
		} else {
			out[on++] = rsp[i];
		}
	}
	out[on++] = 0x7e;
	fItf->rx(out, on);
}

/* what the "modem" does with data the client wrote */
''')
sub('''			next_sahara = fItf->fIndex == 0;
''', '''			next_sahara = false;                    /* the Sahara endpoint is there from the rom stage on */
''')
open(path, 'w', newline='\n').write(s)
print('ok')
