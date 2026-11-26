#!/usr/bin/env python3
"""Build the Apple Device Tree the patched XNU boots with on lavender.

The kernel runs an iPhone X (D22AP) user space, so the identity is the iPhone's; every hardware
value is the Redmi Note 7's (docs/HARDWARE.md). Node and property names such as `sweet-fbcon`,
`sweet-io`, `qcom,kryo470` are the ones the base patch series (MakrSas/ios-topaz) matches on.

usage: mkadt.py OUT.adt [--dump] [--product D22AP.adt] [--baseband D22AP.adt]
  --product   copy /product from a real iPhone X device tree (Apple file, not in this repository);
              needed by user space later, not by the kernel
"""
import argparse
import hashlib
import os
import struct

import adt

# RAM handed to the kernel: the upper bank, above every reserved region (all are below 0xa0400000).
# ABL reports 0x100000000 + ~0x7e4c0000; rounded down to a 32 MB block.
PHYS_BASE, MEM_SIZE = 0x100000000, 0x7E000000
SOC_BASE = 0x01000000           # /arm-io children are relative to this; must not be 0
GICD, GICD_SIZE = 0x17A00000, 0x10000
GICR, GICR_SIZE = 0x17B00000, 0x100000
VTIMER_INTID = 19
TIMEBASE = 19200000
FB, FB_W, FB_H, FB_STRIDE = 0x9D400000, 1080, 2340, 1080 * 4
FB_SIZE = (FB_STRIDE * FB_H + 0x3FFF) & ~0x3FFF
EMMC, EMMC_CQ = 0x0C0C4000, 0x0C0C5000          # sdhc_1: hc_mem, cmdq_mem
GOLD_MPIDR = (0x100, 0x101, 0x102, 0x103)       # the only cores with a 16K granule
GOLD_HZ = 2208000000
ECID = 0x4C4156454E000001                        # synthetic ("LAVEN" + 1), not the phone's


def u32(*v):
    return struct.pack("<%dI" % len(v), *v)


def u64(*v):
    return struct.pack("<%dQ" % len(v), *v)


def cstr(*strings):
    return b"".join(s.encode() + b"\0" for s in strings)


def build(product_path=None, seed=None, baseband_path=None, wlan_path=None, bt_path=None):
    counter = iter(range(1, 1000))

    def node(name, props=(), children=()):
        return adt.Node(name, [("AAPL,phandle", u32(next(counter)))] + list(props), children)

    chosen = node("chosen", [
        ("dram-base", u64(PHYS_BASE)),
        ("dram-size", u64(MEM_SIZE)),
        ("random-seed", seed if seed is not None else os.urandom(64)),
        ("debug-enabled", u32(1)),
        ("firmware-version", cstr("lavender-shim")),
        ("system-firmware-version", cstr("lavender-shim")),
        ("boot-manifest-hash", hashlib.sha384(b"lavender boot manifest").digest()),
        ("crypto-hash-method", cstr("sha2-384")),
        ("display-scale", u32(3)),
        ("unique-chip-id", u64(ECID)),
        ("chip-id", u32(0x8015)),                       # A11, what the iPhone X user space expects
        ("certificate-production-status", u32(0)),
        ("effective-production-status-ap", u32(0)),
        ("certificate-security-mode", u32(1)),
        ("effective-security-mode-sep", u32(1)),
    ], [
        node("memory-map"),
        node("asmb", [("lp-sip0", u64(0x6F)), ("lp-sip1", u32(1))]),    # relaxed SIP, unsealed root
    ])

    cpus = node("cpus", [("#address-cells", u32(1)), ("#size-cells", u32(0))], [
        node(f"cpu{i}", [
            ("device_type", cstr("cpu")),
            ("compatible", cstr("qcom,kryo260", "qcom,kryo470", "ARM,v8")),
            ("reg", u32(mpidr)),
            ("cpu-id", u32(i)),
            ("cluster-id", u32(0)),
            ("cluster-type", u32(0)),
            ("die-cluster-id", u32(0)),
            ("cluster-core-id", u32(i)),
            ("l2-cache-id", u32(0)),
            ("l3-cache-id", u32(0)),
            ("state", cstr("running" if i == 0 else "stopped")),
            ("timebase-frequency", u32(TIMEBASE)),
            ("clock-frequency", u32(GOLD_HZ)),
            ("bus-frequency", u32(100000000)),
            ("memory-frequency", u32(1804800000)),
            ("peripheral-frequency", u32(TIMEBASE)),
            ("fixed-frequency", u32(TIMEBASE)),
        ]) for i, mpidr in enumerate(GOLD_MPIDR)])

    arm_io = node("arm-io", [
        ("device_type", cstr("sweet-io")),
        ("compatible", cstr("sweet-io", "arm-io")),
        ("#address-cells", u32(2)),
        ("#size-cells", u32(2)),
        ("ranges", u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [
        node("gic", [
            ("compatible", cstr("arm,gic-v3")),
            ("interrupt-controller", b""),
            ("virtual-timer-intid", u32(VTIMER_INTID)),
            ("reg", u64(GICD - SOC_BASE, GICD_SIZE, GICR - SOC_BASE, GICR_SIZE)),
        ]),
        node("wdt", [("no-pmu", u32(1))]),
        node("disp0", [
            ("device_type", cstr("display-subsystem")),
            ("compatible", cstr("sweet,display")),
            ("canvas-width", u32(1125)),            # the iPhone X canvas user space draws
            ("canvas-height", u32(2436)),
        ]),
    ])

    fbcon = node("sweet-fbcon", [
        ("reg", u64(FB, FB_SIZE)),
        ("width", u32(FB_W)),
        ("height", u32(FB_H)),
        ("stride", u32(FB_STRIDE)),
    ])
    # Root storage (xnu patch 1002): the eMMC host, absolute addresses: hc_mem (SDHCI), cmdq_mem.
    # The node name is the base series' (its driver was for UFS).
    storage = node("sweet-ufs", [
        ("compatible", cstr("qcom,sdhci-msm-v5")),
        ("reg", u64(EMMC, 0x1000, EMMC_CQ, 0x1000)),
    ])
    defaults = node("defaults", [("no-effaceable-storage", u32(1))])
    buttons = node("buttons", [
        ("button-names", cstr("volup", "voldown", "hold")),
        ("home-button-type", u32(2)),
        ("opposed-power-vol-buttons", u32(1)),
    ])

    extra = []
    if product_path:
        real, _ = adt.parse(open(product_path, "rb").read())
        src = real.child("product")
        props = [(k, cstr("sRGB") if k == "artwork-display-gamut" else v)
                 for k, flag, v in src.props if not flag and k not in ("name", "AAPL,phandle")]
        extra.append(node("product", props))
    if wlan_path:
        # arm-io/wlan as on the iPhone X: launchd starts wifid only when the device tree has a node
        # named "wlan" (or "marconi-wifi"). Its wlan.* / bcom.* tunables are kept; not copied: the
        # iPhone's MAC address, its GPIO/PMU functions, interrupts, phandles, syscfg pointers.
        real, _ = adt.parse(open(wlan_path, "rb").read())
        src = None
        for c in real.child("arm-io").children:
            for g in c.children:
                if g.name == "wlan" and g.prop("compatible") and b"uart" in g.prop("compatible"):
                    src = g
        drop = ("name", "AAPL,phandle", "local-mac-address", "interrupts", "interrupt-parent", "audio-protection-driver",
                "wifi-antenna-sku-info", "wifi-calibration-msf")
        props = [(k, v) for k, flag, v in src.props if not flag and k not in drop and not k.startswith("function-")]
        arm_io.children.append(node("wlan", props))
    if bt_path:
        # arm-io/uart1/bluetooth as on the iPhone X: bluetoothd reads local-mac-address (the kernel
        # puts the address from the modem's NV 447 there; a zero placeholder until then),
        # transport-encoding/-speed, vendor/product id, coex. Not copied: the iPhone's address, its
        # GPIO/PMU functions, phandles, syscfg calibration pointers.
        real, _ = adt.parse(open(bt_path, "rb").read())
        src = real.child("arm-io").child("uart1").child("bluetooth")
        drop = ("name", "AAPL,phandle", "local-mac-address")
        props = [(k, v) for k, flag, v in src.props if not flag and k not in drop and not k.startswith("function-")]
        props.append(("local-mac-address", bytes(6)))
        arm_io.children.append(node("uart1", [("compatible", cstr("uart-1,lavender")), ("device_type", cstr("uart"))],
                                    [node("bluetooth", props)]))
    if baseband_path:
        # /baseband as on the Qualcomm iPhone X: launchd then loads the cellular CommCenter job and
        # libTelephonyBaseband finds its "config" timings. No function-* (they point at Apple GPIO/PMU
        # nodes), no interrupts; device-imei stays the zero placeholder iBoot would fill.
        real, _ = adt.parse(open(baseband_path, "rb").read())
        src = real.child("baseband")
        keep = ("device_type", "compatible", "config", "class", "imeisv", "device-imei", "region-sku")
        extra.append(node("baseband", [(k, v) for k, flag, v in src.props if k in keep]))

    return node("device-tree", [
        ("compatible", cstr("D22AP", "iPhone10,3", "xiaomi,lavender", "xiaomi,sweet", "qcom,sdm660", "AppleARM")),
        ("model", cstr("iPhone10,3")),
        ("target-type", cstr("D22")),
        ("target-sub-type", cstr("D22AP")),
        ("manufacturer", cstr("Apple Inc.")),
        ("#address-cells", u32(2)),
        ("#size-cells", u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon, storage, buttons] + extra)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--product")
    ap.add_argument("--baseband", help="real iPhone X device tree to copy /baseband from")
    ap.add_argument("--wlan", help="real iPhone X device tree to copy arm-io/.../wlan from")
    ap.add_argument("--bt", help="real iPhone X device tree to copy arm-io/uart1/bluetooth from")
    a = ap.parse_args()
    blob = adt.serialize(build(a.product, baseband_path=a.baseband, wlan_path=a.wlan, bt_path=a.bt))
    open(a.out, "wb").write(blob)
    if a.dump:
        adt.dump(adt.parse(blob)[0])
    print(f"{a.out}: {len(blob)} bytes")
