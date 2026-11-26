"""lavender: a CRC complaint on the last board-data segment is not fatal (patch 1078).

Run e82: the board data (image/bdwlan.bin, 19152 bytes) went in four segments and the last one
was answered "failed, error 1". Linux ath10k (qmi.c): "end = 1 triggers a CRC check on the BDF.
If this fails, we get a QMI_ERR_MALFORMED_MSG_V01 error, but the FW is still willing to use the
BDF. For some platforms, all the valid released BDFs fail this CRC check" - and goes on. So here.

usage: python mk_wlfwcrc.py XNU_TREE   (after mk_wlfwbdf.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()
old = '''	case WLFW_BDF_DOWNLOAD:
		if (!ok) {
			LOG("wlfw: bdf segment %u FAILED err %u", w_bdf_seg - 1, err);
			break;
		}
'''
new = '''	case WLFW_BDF_DOWNLOAD:
		if (!ok && !(w_bdf_off >= w_bdf_len && err == 1)) {
			LOG("wlfw: bdf segment %u FAILED err %u", w_bdf_seg - 1, err);
			break;
		}
		if (!ok) {
			LOG("wlfw: last bdf segment: CRC complaint (error 1), not fatal (as Linux ath10k)");
		}
'''
assert s.count(old) == 1
s = s.replace(old, new)
open(path, 'w', newline='\n').write(s)
print('ok')
