#!/bin/bash
# Build the iOS root image for the userdata partition from the iPhone X IPSW.
#   wsl -u root -e bash tools/wsl/mkroot.sh IPSW OUT.simg [SIZE]      (SIZE default 16G)
#
# 1. The three APFS disk images of the D22AP "Erase" restore (OS, SystemOS and AppOS cryptexes)
#    are picked by BuildManifest.plist and unzipped from the IPSW.
# 2. MakrSas/ios-topaz tools/mkiosroot.sh copies them into one case-sensitive journaled HFS+
#    volume; tools/sweet-root-tweaks.py applies the bring-up changes (no CommCenter, Setup and
#    migration skipped, ...). Both are fetched at the same pinned commit as the kernel patches.
# 3. img2simg makes the sparse image `fastboot flash userdata` takes.
# Work files go to $LV_WORK (default /root/lv-work, WSL's own disk: much faster than /mnt/d).
set -euo pipefail
[[ $EUID == 0 ]] || { echo "run as root" >&2; exit 1; }
[[ $# -ge 2 ]] || { sed -n '2,3p' "$0"; exit 2; }
ipsw=$(realpath "$1") out=$2 size=${3:-16G}
here=$(dirname "$(realpath "$0")")
BASE_REPO=https://github.com/MakrSas/ios-topaz
BASE_SHA=$(sed -n 's/^  BASE_SHA: //p' "$here/../../.github/workflows/xnu.yml")
work=${LV_WORK:-/root/lv-work}
mkdir -p "$work"
bash "$here/setup.sh"

# 1. disk images
if [[ ! -f $work/appos.dmg ]]; then
	unzip -p "$ipsw" BuildManifest.plist > "$work/BuildManifest.plist"
	python3 - "$work/BuildManifest.plist" > "$work/dmgs.txt" <<'EOF'
import plistlib, sys
m = plistlib.load(open(sys.argv[1], 'rb'))
for ident in m['BuildIdentities']:
    info = ident['Info']
    if info.get('DeviceClass', '').lower() == 'd22ap' and info.get('RestoreBehavior') == 'Erase':
        man = ident['Manifest']
        for key, name in (('OS', 'os'), ('Cryptex1,SystemOS', 'systemos'), ('Cryptex1,AppOS', 'appos')):
            print(name, man[key]['Info']['Path'])
        break
else:
    sys.exit('no D22AP Erase identity')
EOF
	cat "$work/dmgs.txt"
	while read -r name path; do
		echo "unzip $path -> $name.dmg"
		unzip -p "$ipsw" "$path" > "$work/$name.dmg.part" && mv "$work/$name.dmg.part" "$work/$name.dmg"
	done < "$work/dmgs.txt"
fi

# 2. base tools at the pinned commit
if [[ ! -f $work/base/tools/mkiosroot.sh || $(git -C "$work/base" rev-parse HEAD) != "$BASE_SHA" ]]; then
	rm -rf "$work/base"
	git init -q "$work/base"
	git -C "$work/base" fetch -q --depth 1 "$BASE_REPO" "$BASE_SHA"
	git -C "$work/base" checkout -q FETCH_HEAD
fi

img=$work/ios16-root.img
rm -f "$img"
bash "$work/base/tools/mkiosroot.sh" "$work/os.dmg" "$work/systemos.dmg" "$work/appos.dmg" "$img" "$size"
mnt=$work/mnt
mkdir -p "$mnt"
mount -t hfsplus -o loop,force "$img" "$mnt"
trap 'umount "$mnt" 2>/dev/null || true' EXIT
python3 "$work/base/tools/sweet-root-tweaks.py" "$mnt"
umount "$mnt"
trap - EXIT
fsck.hfsplus -f -n "$img"

# 3. sparse image
img2simg "$img" "$out.part"
mv "$out.part" "$out"
sha256sum "$img" | tee "$out.img.sha256"
ls -la "$out"
