"""lavender: audio A3 - APR payload after the header length the packet gives (patch 1123).

Run e134 (xnu 1122): "apr_audio_svc" opens both ways and the ADSP answers every
AVCS_CMD_ADSP_EVENT_GET_STATE - but the "state" read was 0x04000102 + 0x100 per ask, i.e. not
the payload: the answer's header length is not the 16 bytes assumed. APR (msm-4.4 apr.c) takes
it from hdr_field bits 7:4 (in 32-bit words) and the payload starts there.

Now the payload offset is hdr_field's header length (bounded by the packet), and the first 3
packets are dumped raw (32 bytes) to see the real layout.

usage: python mk_audio5.py XNU_TREE   (after mk_audio4.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazAudio.cpp'
s = open(path, newline='').read()
old = '''	const uint32_t *p = (const uint32_t *)(data + sizeof(*h));
	uint32_t n = (len - (uint32_t)sizeof(*h)) / 4;
	apr_rxn++;'''
assert s.count(old) == 1
s = s.replace(old, '''	uint32_t hlen = ((h->hdr_field >> 4) & 0xF) * 4u;
	if (hlen < 8 || hlen > len) {
		hlen = (uint32_t)sizeof(*h);
	}
	const uint32_t *p = (const uint32_t *)(data + hlen);
	uint32_t n = (len - hlen) / 4;
	apr_rxn++;
	if (apr_rxn <= 3) {
		const uint32_t *w = (const uint32_t *)data;
		LOG("APR: raw %u bytes (hdr_field %#x, header %u): %08x %08x %08x %08x %08x %08x %08x %08x", len, h->hdr_field, hlen,
		    w[0], len > 4 ? w[1] : 0, len > 8 ? w[2] : 0, len > 12 ? w[3] : 0, len > 16 ? w[4] : 0, len > 20 ? w[5] : 0,
		    len > 24 ? w[6] : 0, len > 28 ? w[7] : 0);
	}''')
open(path, 'w', newline='\n').write(s)
print('ok')
