#!/usr/bin/env python3
"""Read the kernel log the phone sends over USB (xnu patch 1001) and send it commands. Windows only.

The phone shows up as a WinUSB device (VID 1209, PID 0005) with no driver to install; this script
talks to it through winusb.dll, so nothing needs to be installed in Python either.

usage: usblog.py [--out FILE] [--wait SECONDS] [--idle SECONDS] [--until TEXT] [--cmd lv:reset]
  --out FILE     also append everything received to FILE
  --wait N       how long to wait for the device to appear (default 60)
  --idle N       stop after N seconds without new log bytes (default: run until Ctrl+C)
  --until TEXT   stop when TEXT appears in the log
  --cmd TEXT     send a command (lv:ping, lv:reset) once connected; with --idle 0 exit right after
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

GUID_TEXT = "{7B1E8D2A-5C3F-4E6B-9A1D-4C41564E4452}"      # DeviceInterfaceGUIDs in the phone's descriptors
EP_IN, EP_OUT = 0x81, 0x01

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winusb = ctypes.WinDLL("winusb", use_last_error=True)
ole32 = ctypes.WinDLL("ole32")


class GUID(ctypes.Structure):
    _fields_ = [("d1", wt.DWORD), ("d2", wt.WORD), ("d3", wt.WORD), ("d4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("guid", GUID), ("flags", wt.DWORD), ("reserved", ctypes.c_void_p)]


INVALID = ctypes.c_void_p(-1).value
setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD,
                                                 ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                      ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
kernel32.CreateFileW.restype = ctypes.c_void_p
kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
winusb.WinUsb_Initialize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
winusb.WinUsb_Free.argtypes = [ctypes.c_void_p]
winusb.WinUsb_ReadPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p, wt.ULONG,
                                   ctypes.POINTER(wt.ULONG), ctypes.c_void_p]
winusb.WinUsb_WritePipe.argtypes = winusb.WinUsb_ReadPipe.argtypes
winusb.WinUsb_SetPipePolicy.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, wt.ULONG, wt.ULONG, ctypes.c_void_p]

DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x2, 0x10
PIPE_TRANSFER_TIMEOUT = 0x03
ERROR_SEM_TIMEOUT = 121


def device_path():
    """Path of the first present device interface with our GUID, or None."""
    guid = GUID()
    ole32.CLSIDFromString(GUID_TEXT, ctypes.byref(guid))
    devs = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    if devs == INVALID:
        return None
    try:
        iface = SP_DEVICE_INTERFACE_DATA()
        iface.cbSize = ctypes.sizeof(iface)
        if not setupapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(guid), 0, ctypes.byref(iface)):
            return None
        need = wt.DWORD()
        setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(iface), None, 0, ctypes.byref(need), None)
        buf = ctypes.create_string_buffer(need.value)
        ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8       # cbSize of the detail struct on 64-bit
        if not setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(iface), buf, need, None, None):
            return None
        return ctypes.wstring_at(ctypes.addressof(buf) + 4)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(devs)


class Phone:
    def __init__(self, path):
        self.file = kernel32.CreateFileW(path, 0xC0000000, 3, None, 3, 0x40000000, None)   # read/write, overlapped
        if self.file == INVALID:
            raise OSError(ctypes.get_last_error(), "CreateFile failed")
        self.usb = ctypes.c_void_p()
        if not winusb.WinUsb_Initialize(self.file, ctypes.byref(self.usb)):
            err = ctypes.get_last_error()
            kernel32.CloseHandle(self.file)
            raise OSError(err, "WinUsb_Initialize failed")
        timeout = wt.ULONG(200)
        winusb.WinUsb_SetPipePolicy(self.usb, EP_IN, PIPE_TRANSFER_TIMEOUT, 4, ctypes.byref(timeout))
        timeout = wt.ULONG(1000)
        winusb.WinUsb_SetPipePolicy(self.usb, EP_OUT, PIPE_TRANSFER_TIMEOUT, 4, ctypes.byref(timeout))

    def read(self):
        """Bytes received within the pipe timeout (may be empty). Raises OSError when the device is gone."""
        buf = ctypes.create_string_buffer(4096)
        got = wt.ULONG()
        if winusb.WinUsb_ReadPipe(self.usb, EP_IN, buf, len(buf), ctypes.byref(got), None):
            return buf.raw[:got.value]
        err = ctypes.get_last_error()
        if err == ERROR_SEM_TIMEOUT:
            return b""
        raise OSError(err, "read failed")

    def write(self, data):
        sent = wt.ULONG()
        if not winusb.WinUsb_WritePipe(self.usb, EP_OUT, data, len(data), ctypes.byref(sent), None):
            raise OSError(ctypes.get_last_error(), "write failed")

    def close(self):
        winusb.WinUsb_Free(self.usb)
        kernel32.CloseHandle(self.file)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--wait", type=float, default=60)
    ap.add_argument("--idle", type=float)
    ap.add_argument("--until")
    ap.add_argument("--cmd")
    a = ap.parse_args()

    deadline = time.time() + a.wait
    path = device_path()
    while path is None and time.time() < deadline:
        time.sleep(0.5)
        path = device_path()
    if path is None:
        print("usblog: no device", file=sys.stderr)
        return 2
    phone = Phone(path)
    print("usblog: connected", file=sys.stderr)
    out = open(a.out, "ab") if a.out else None
    seen = b""
    last = time.time()
    status = 0
    try:
        if a.cmd:
            phone.write(a.cmd.encode())
            if a.idle == 0:
                return 0
        while True:
            data = phone.read()
            if data:
                last = time.time()
                sys.stdout.write(data.decode("utf-8", "replace"))
                sys.stdout.flush()
                if out:
                    out.write(data)
                    out.flush()
                if a.until:
                    seen = (seen + data)[-65536:]
                    if a.until.encode() in seen:
                        break
            elif a.idle is not None and time.time() - last > a.idle:
                break
    except OSError as e:
        print(f"\nusblog: device gone ({e})", file=sys.stderr)
        status = 1
    except KeyboardInterrupt:
        pass
    finally:
        phone.close()
        if out:
            out.close()
    return status


if __name__ == "__main__":
    sys.exit(main())
