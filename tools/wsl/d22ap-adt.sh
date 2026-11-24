#!/bin/bash
# Extract the real iPhone X (D22AP) device tree from the IPSW; tools/mkadt.py --product copies its
# /product node (MobileGestalt: device class, screen class, artwork) into the lavender tree.
#   wsl -u root -e bash tools/wsl/d22ap-adt.sh IPSW OUT.adt
# Apple file: keep it out of git.
set -euo pipefail
[[ $# == 2 ]] || { sed -n '2,5p' "$0"; exit 2; }
ipsw=$(realpath "$1") out=$2
command -v ipsw >/dev/null || { echo "needs the ipsw tool (github.com/blacktop/ipsw)" >&2; exit 1; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
unzip -p "$ipsw" Firmware/all_flash/DeviceTree.d22ap.im4p > "$work/dt.im4p"
ipsw img4 im4p extract "$work/dt.im4p" --output "$work/dt.bin" >/dev/null
cp "$work/dt.bin" "$out"
ls -la "$out"
