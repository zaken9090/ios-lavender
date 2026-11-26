"""lavender: the board data goes to the WLAN firmware right after "cap" (patch 1077).

Run e80 (DIAG servers on, 1075): with the WLFW handshake running the modem no longer dies; the
handshake stops after "cap" because the board data download waited for an MSA_READY indication
this firmware does not send. Linux ath10k (qmi.c, ath10k_qmi_event_server_arrive) downloads the
board data right after the capability request without waiting for it. The same here.

usage: python mk_wlfwbdf.py XNU_TREE   (after mk_uimprov.py)
"""
import sys

tree = sys.argv[1]
path = f'{tree}/iokit/Kernel/arm/TopazModem.cpp'
s = open(path, newline='').read()
old = '''	if (w_bdf_started || !w_msa_ind || !w_cap_done) {'''
assert s.count(old) == 1
s = s.replace(old, '''	if (w_bdf_started || !w_cap_done) {             /* no MSA_READY indication from this firmware (mk_wlfwbdf.py) */''')
open(path, 'w', newline='\n').write(s)
print('ok')
