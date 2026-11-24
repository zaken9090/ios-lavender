#!/bin/bash
# Name the user-space addresses of a sampler/crash line from the kernel log (shared cache only).
#   wsl -u root -e bash tools/wsl/symbolicate.sh SLIDE ADDR...        (SLIDE: "slide 0x..." of the SMP/CRASH header)
# Reads the arm64 shared cache from the root image built by mkroot.sh ($LV_WORK/ios16-root.img).
set -euo pipefail
slide=$1; shift
work=${LV_WORK:-/root/lv-work}
mnt=$work/mnt-ro
mkdir -p "$mnt"
grep -qw hfsplus /proc/filesystems || bash "$(dirname "$(realpath "$0")")/setup.sh" >/dev/null
mountpoint -q "$mnt" || mount -t hfsplus -o loop,ro "$work/ios16-root.img" "$mnt"
cache=$mnt/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64
for a in "$@"; do
	unslid=$(printf '0x%x' $((a - slide)))
	printf '%-14s ' "$a"
	ipsw dyld a2s "$cache" "$unslid" 2>&1 | grep -v '^\s*$' | tail -1 | sed 's/^.*⨯ //'
done
