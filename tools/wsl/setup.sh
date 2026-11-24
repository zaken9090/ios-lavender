#!/bin/bash
# Prepare WSL (Ubuntu) to build the iOS root image. Idempotent: skips whatever is already there.
#   wsl -u root -e bash tools/wsl/setup.sh
#
# Needs: hfsprogs (mkfs/fsck.hfsplus), img2simg, rsync, unzip, apfs-fuse (reads the IPSW's APFS
# images), the hfsplus kernel module (the WSL kernel has no HFS+), and user ids 272 (_logd) and
# 501 (mobile), which the root build gives files to (Ubuntu's uutils `install` wants known ids).
set -euo pipefail
[[ $EUID == 0 ]] || { echo "run as root" >&2; exit 1; }
TOOLS=${LV_TOOLS:-/root/lv-tools}
mkdir -p "$TOOLS"

need=()
for p in hfsprogs:mkfs.hfsplus android-sdk-libsparse-utils:img2simg rsync:rsync unzip:unzip \
         python3:python3 git:git; do
	command -v "${p#*:}" >/dev/null || need+=("${p%%:*}")
done
if ((${#need[@]})); then
	apt-get update -q && apt-get install -y -q "${need[@]}"
fi

# apfs-fuse, built from source (no Ubuntu package)
if ! command -v apfs-fuse >/dev/null; then
	apt-get install -y -q build-essential cmake libfuse3-dev zlib1g-dev libbz2-dev libattr1-dev fuse3
	rm -rf "$TOOLS/apfs-fuse"
	git clone -q --recursive https://github.com/sgan81/apfs-fuse "$TOOLS/apfs-fuse"
	cmake -S "$TOOLS/apfs-fuse" -B "$TOOLS/apfs-fuse/build" -DCMAKE_BUILD_TYPE=Release
	make -C "$TOOLS/apfs-fuse/build" -j"$(nproc)"
	install -m 0755 "$TOOLS/apfs-fuse/build/apfs-fuse" /usr/local/bin/apfs-fuse
fi

# hfsplus kernel module for the running WSL kernel
if ! grep -qw hfsplus /proc/filesystems; then
	ko=${HFSPLUS_KO:-}
	for c in "$TOOLS/hfsplus-$(uname -r).ko" /root/wslk/src/fs/hfsplus/hfsplus.ko; do
		[[ -z $ko && -f $c ]] && modinfo -F vermagic "$c" | grep -q "^$(uname -r) " && ko=$c
	done
	if [[ -z $ko ]]; then
		# Source of the running kernel; its own config with HFS+ as a module. The WSL kernel is
		# built with an older GCC than Ubuntu's default: GCC 13 builds a module it accepts.
		apt-get install -y -q gcc-13 make bc flex bison libelf-dev libssl-dev dwarves
		ver=$(uname -r | cut -d- -f1)
		src="$TOOLS/wsl-kernel"
		[[ -d $src ]] || git clone -q --depth 1 --branch "linux-msft-wsl-$ver" \
			https://github.com/microsoft/WSL2-Linux-Kernel "$src"
		zcat /proc/config.gz > "$src/.config"
		sed -i 's/^# CONFIG_HFSPLUS_FS is not set/CONFIG_HFSPLUS_FS=m/' "$src/.config"
		make -C "$src" CC=gcc-13 olddefconfig modules_prepare
		make -C "$src" CC=gcc-13 M=fs/hfsplus modules
		ko="$TOOLS/hfsplus-$(uname -r).ko"
		cp "$src/fs/hfsplus/hfsplus.ko" "$ko"
	fi
	insmod "$ko"
	echo "hfsplus loaded from $ko"
fi

getent group 272 >/dev/null || groupadd -g 272 _logd
getent passwd 272 >/dev/null || useradd -u 272 -g 272 -M -N -s /usr/sbin/nologin _logd
getent group 501 >/dev/null || groupadd -g 501 mobile
getent passwd 501 >/dev/null || useradd -u 501 -g 501 -M -N -s /usr/sbin/nologin mobile
echo "WSL ready: $(command -v apfs-fuse mkfs.hfsplus img2simg | tr '\n' ' ')"
