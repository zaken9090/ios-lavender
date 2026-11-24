"""Writes the lavender version of bsd/dev/sweet_usb.c into an extracted xnu tree (argv[1])."""
import struct, sys, uuid

GUID = '{7B1E8D2A-5C3F-4E6B-9A1D-4C41564E4452}'     # device interface GUID, also in tools/usblog.py
VENDOR_CODE = 0x20

name = 'DeviceInterfaceGUIDs\0'.encode('utf-16le')
data = (GUID + '\0\0').encode('utf-16le')
reg = struct.pack('<HHHH', 10 + len(name) + len(data), 4, 7, len(name)) + name + struct.pack('<H', len(data)) + data
compat = struct.pack('<HH', 20, 3) + b'WINUSB\0\0' + bytes(8)
total = 10 + len(compat) + len(reg)
msos = struct.pack('<HHIH', 10, 0, 0x06030000, total) + compat + reg
bos = (struct.pack('<BBHB', 5, 0x0f, 5 + 28, 1) + struct.pack('<BBBB', 28, 0x10, 5, 0) +
       uuid.UUID('D8DD60DF-4589-4CC7-9CD2-659D9E648A9F').bytes_le +
       struct.pack('<IHBB', 0x06030000, total, VENDOR_CODE, 0))
dev = bytes([18, 1, 0x01, 0x02, 0, 0, 0, 64, 0x09, 0x12, 0x05, 0x00, 0x00, 0x01, 1, 2, 3, 1])
cfg = bytes([9, 2, 32, 0, 1, 1, 0, 0x80, 250,
             9, 4, 0, 0, 2, 0xff, 0x00, 0x00, 0,
             7, 5, 0x81, 0x02, 0x00, 0x02, 0,
             7, 5, 0x01, 0x02, 0x00, 0x02, 0])

def arr(b):
    rows = [', '.join('0x%02x' % x for x in b[i:i + 16]) for i in range(0, len(b), 16)]
    return '\t' + ',\n\t'.join(rows) + ','

src = open(sys.argv[2]).read()
for key, val in (('@DEV@', arr(dev)), ('@CFG@', arr(cfg)), ('@BOS@', arr(bos)), ('@MSOS@', arr(msos)),
                 ('@DEVN@', str(len(dev))), ('@CFGN@', str(len(cfg))), ('@BOSN@', str(len(bos))),
                 ('@MSOSN@', str(len(msos))), ('@GUID@', GUID), ('@VENDOR@', '0x%02x' % VENDOR_CODE)):
    src = src.replace(key, val)
left = [w for w in src.split() if w.startswith('@') and w.endswith('@') and w[1:-1].isupper()]
assert not left, left
open(sys.argv[1] + '/bsd/dev/sweet_usb.c', 'w', newline='\n').write(src)
print('msos', len(msos), 'bos', len(bos))
