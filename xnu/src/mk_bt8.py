"""lavender: Bluetooth B2 - the NVM is a BT+FM container (patch 1092).

Run e100: crnv21.bin starts 04 8d 11 00 - TLV type 4 (Qualcomm libbt TLV_TYPE_BT_FM_NVM) of
4493 bytes holding sub-TLVs (type 2 = BT NVM, 3 = FM NVM), each with its own 4-byte header; the
BT NVM's tags start after that (first: tag 2, the default address; then tag 17 HCI). Walking
tags right after the outer header (as for a plain type 2 file) found none, so the NVM went down
unedited - with its own HCI baud rate, after which the chip is deaf at 115200.

Now: type 2 is walked as before; type 4 is walked sub-TLV by sub-TLV and its type-2 part gets the
tag edits (17: in-band sleep off, baud 115200; 27: deep sleep off). Tags 17/27 are logged before
the edit. The per-tag and dump logging of 1091 is dropped.

usage: python mk_bt8.py XNU_TREE   (after mk_bt7.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/LavenderBT.cpp'
s = open(path, newline='').read()


def sub(old, new):
    global s
    assert s.count(old) == 1, (old[:70], s.count(old))
    s = s.replace(old, new)


# cut the whole tag walk of bt_download and put a helper in its place
start = s.index('''	if (!patch) {
		uint32_t len = (data[1] | (data[2] << 8) | ((uint32_t)data[3] << 16));''')
end = s.index('''	LOG("firmware: %s, %u bytes, download mode %u", what, size, mode);''')
s = s[:start] + '''	if (!patch && size >= 4) {
		uint32_t len = (data[1] | (data[2] << 8) | ((uint32_t)data[3] << 16));
		if (len > size - 4) {
			len = size - 4;
		}
		if (data[0] == 2) {
			bt_nvm_edit(data + 4, len);
		} else if (data[0] == 4) {
			for (uint32_t o = 4; o + 4 <= 4 + len;) {
				uint32_t sl = data[o + 1] | (data[o + 2] << 8) | ((uint32_t)data[o + 3] << 16);
				if (sl > 4 + len - (o + 4)) {
					break;
				}
				LOG("nvm: part type %u, %u bytes", data[o], sl);
				if (data[o] == 2) {
					bt_nvm_edit(data + o + 4, sl);
				}
				o += 4 + sl;
			}
		} else {
			LOG("nvm: unknown type %u", data[0]);
		}
	}
''' + s[end:]
sub('''/* one TLV file as 243-byte segments (btqca qca_download_firmware) */''', '''/* the tag edits of btqca qca_tlv_check_data on a BT NVM body (tags: id u16, len u16, 8 reserved, data) */
static void
bt_nvm_edit(uint8_t *body, uint32_t len)
{
	for (uint32_t idx = 0; idx + 12 <= len;) {
		uint8_t *t = body + idx;
		uint16_t id = (uint16_t)(t[0] | (t[1] << 8)), tl = (uint16_t)(t[2] | (t[3] << 8));
		if (idx + 12u + tl > len) {
			break;
		}
		if ((id == 17 || id == 27) && tl >= 3) {
			LOG("nvm tag %u len %u: %02x %02x %02x", id, tl, t[12], t[13], t[14]);
		}
		if (id == 17 && tl >= 3) {
			t[12] &= (uint8_t)~0x80u;      /* no software in-band sleep */
			t[14] = 0;                      /* 115200 */
		} else if (id == 27 && tl >= 1) {
			t[12] &= (uint8_t)~1u;          /* no deep sleep */
		}
		idx += 12u + tl;
	}
}

/* one TLV file as 243-byte segments (btqca qca_download_firmware) */''')
open(path, 'w', newline='\n').write(s)
print('ok')
