#!/bin/bash
# Find files in the built iOS root that contain a string (read-only mount of $LV_WORK/ios16-root.img).
#   wsl -u root -e bash tools/wsl/rootgrep.sh TEXT [find-name-pattern]      e.g. BoundingPathBitmap '*.car'
set -euo pipefail
text=$1 pattern=${2:-*}
work=${LV_WORK:-/root/lv-work}
mnt=$work/mnt-ro
mkdir -p "$mnt"
grep -qw hfsplus /proc/filesystems || bash "$(dirname "$(realpath "$0")")/setup.sh" >/dev/null
mountpoint -q "$mnt" || mount -t hfsplus -o loop,ro "$work/ios16-root.img" "$mnt"
cd "$mnt"
find . -xdev -type f -name "$pattern" -print0 2>/dev/null | xargs -0 grep -l -a -F -- "$text" 2>/dev/null || true
