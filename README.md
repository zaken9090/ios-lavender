# ios-lavender

Experimental port of iOS 16.7.16 (XNU 8796, iPhone X user space) to the Xiaomi Redmi Note 7
(`lavender`, Qualcomm SDM660). Research project, work in progress.

Status (2026-11-24): the shim starts a Gold core at 2.2 GHz with a 16K-page MMU and the XNU kernel
boots to the root-device wait with its log on the screen. No storage driver, no user space yet.
See `docs/HARDWARE.md` for measured hardware facts.

Boot chain: ABL -> `fastboot boot` shim -> XNU + generated Apple Device Tree -> HFS+ root in `userdata`.

Based on the approach of [MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz)
(itself derived from `dipa-studio/ios-sweet` and HackiOS). Credits and licences will be
recorded in `CREDITS.md` as code is brought in.

## Layout
- `shim/` - first-stage loader started by `fastboot boot`
- `tools/` - host scripts (device tree, payload, images)
- `xnu/patches/` - patch series on top of Apple's open-source XNU
- `userland/` - user-space pieces
- `docs/` - audit, hardware notes, per-stage results

No Apple firmware, IPSW contents or device-unique data (IMEI, serials, `persist`) belong in this repository.
