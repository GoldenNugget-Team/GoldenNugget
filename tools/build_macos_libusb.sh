#!/usr/bin/env bash
# Do not let PyInstaller collect the runner's native-only Homebrew libusb.
set -euo pipefail
build_root="${RUNNER_TEMP:?}/goldennugget-libusb"
output="$PWD/.macos-libusb"
mkdir -p "$build_root" "$output"
export MACOSX_DEPLOYMENT_TARGET=14.4
jobs="${GOLDENNUGGET_BUILD_JOBS:-$(sysctl -n hw.ncpu)}"
if ! [[ "$jobs" =~ ^[1-9][0-9]*$ ]]; then
  echo "::error::GOLDENNUGGET_BUILD_JOBS must be a positive integer"
  exit 1
fi
# --retry-all-errors: curled GitHub's release CDN sometimes drops the
# transfer mid-flight (exit 56 with a 504 from the redirect target), which
# plain --retry does not consider transient.
curl --fail --location --retry 5 --retry-all-errors --retry-delay 2 \
  --connect-timeout 30 --output "$build_root/libusb.tar.bz2" \
  https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.tar.bz2
echo "fea36f34f9156400209595e300840767ab1a385ede1dc7ee893015aea9c6dbaf  $build_root/libusb.tar.bz2" | shasum -a 256 -c -
tar -xjf "$build_root/libusb.tar.bz2" -C "$build_root"
(
  cd "$build_root/libusb-1.0.30"
  export CFLAGS="-arch arm64 -arch x86_64 -mmacosx-version-min=14.4"
  export LDFLAGS="$CFLAGS"
  ./configure --prefix="$build_root/install" --disable-static --disable-dependency-tracking
  make -j "$jobs"
  make install
)
cp "$build_root/install/lib/libusb-1.0.0.dylib" "$output/libusb-1.0.dylib"
cp "$build_root/libusb-1.0.30/COPYING" "$output/COPYING"
install_name_tool -id @rpath/libusb-1.0.dylib "$output/libusb-1.0.dylib"
codesign --force --sign - "$output/libusb-1.0.dylib"
python - "$output/libusb-1.0.dylib" <<'CHECK'
import ctypes
import re
import subprocess
import sys

binary = sys.argv[1]
arches = set(subprocess.check_output(['lipo', '-archs', binary], text=True).split())
assert arches == {'arm64', 'x86_64'}, arches
commands = subprocess.check_output(['otool', '-l', binary], text=True)
minimums = re.findall(r'\bminos (\d+\.\d+(?:\.\d+)?)', commands)
assert len(minimums) == 2 and all(tuple(map(int, v.split('.')[:2])) <= (14, 4) for v in minimums), minimums
library = ctypes.CDLL(binary)
library.libusb_get_version.restype = ctypes.c_void_p
assert library.libusb_get_version()
print(f'libusb Universal2 verified: {binary}, deployment targets: {minimums}')
CHECK
