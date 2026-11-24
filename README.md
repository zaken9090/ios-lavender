# ios-lavender

Experimental port of iOS 16.7.16 (XNU 8796, iPhone X user space) to the Xiaomi Redmi Note 7
(`lavender`, Qualcomm SDM660). Research project, work in progress: nothing boots from this
repository yet.

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
