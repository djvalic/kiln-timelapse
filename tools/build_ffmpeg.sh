#!/bin/sh
# Build this plugin's ffmpeg (bin/ffmpeg + its libraries in ffmpeg/) from
# source with Kiln OS's Buildroot toolchain, so it runs on the printer.
#
# usage: tools/build_ffmpeg.sh KILN_OS_DIR
#   KILN_OS_DIR: a Kiln OS checkout (github.com/djvalic/kiln-os) whose
#   buildroot/output has been built (its toolchain and C library are the
#   printer's). Adds tools/ffmpeg.config to that output, builds x264 and
#   ffmpeg, then copies the program and the libraries Kiln OS doesn't have
#   into ffmpeg/bin and ffmpeg/lib (ffmpeg/ffmpeg, the wrapper, stays), and the source archives' names into ffmpeg/SOURCES.
set -e
K=$(cd "${1:?usage: build_ffmpeg.sh KILN_OS_DIR}" && pwd)
HERE=$(cd "$(dirname "$0")/.." && pwd)
O=$K/buildroot/output
cat "$HERE/tools/ffmpeg.config" >> "$O/.config"
make -C "$K/buildroot/src" O="$O" BR2_EXTERNAL="$K/buildroot" olddefconfig >/dev/null
make -C "$K/buildroot/src" O="$O" BR2_EXTERNAL="$K/buildroot" ffmpeg
F=$HERE/ffmpeg
rm -rf "$F/bin" "$F/lib"; mkdir -p "$F/bin" "$F/lib"
cp "$O/target/usr/bin/ffmpeg" "$F/bin/"
for l in libavcodec libavdevice libavfilter libavformat libavutil \
		libswresample libswscale libx264; do
	for f in "$O/target/usr/lib/$l".so.*; do
		[ -L "$f" ] || cp "$f" "$F/lib/$(basename "$f" | sed 's/^\(lib[a-z0-9]*\.so\.[0-9]*\).*/\1/')"
	done
done
{
	echo "Built from source by tools/build_ffmpeg.sh (Kiln OS $(git -C "$K" describe --tags --always 2>/dev/null))."
	echo "Licence: GPL-2.0-or-later (ffmpeg with --enable-gpl, x264)."
	echo "Source archives (attached to this repository's releases):"
	for p in ffmpeg x264; do
		d=$(ls -d "$O/build/$p"-* | head -1)
		echo "  $(basename "$d")  $(cat "$K/buildroot/src/package/$p/$p.mk" | sed -n "s/^$(echo $p | tr a-z A-Z)_SITE = //p")"
	done
	echo "Options: tools/ffmpeg.config"
} > "$F/SOURCES"
ls -la "$F/bin" "$F/lib"
