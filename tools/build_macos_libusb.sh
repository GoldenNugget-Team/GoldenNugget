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
# Source tarballs of the release sit behind GitHub's asset CDN, which
# intermittently answers 504 to anonymous downloads; the tag itself is
# fetched through plain git instead and pinned to its commit.
git clone --quiet --depth 1 --branch v1.0.30 \
  https://github.com/libusb/libusb.git "$build_root/libusb-1.0.30"
libusb_commit="87a55632db62c9bdc58cd31d3ccfa673f1bb017f"
if [[ "$(git -C "$build_root/libusb-1.0.30" rev-parse HEAD)" != "$libusb_commit" ]]; then
  echo "::error::libusb v1.0.30 moved: expected $libusb_commit"
  exit 1
fi
(
  cd "$build_root/libusb-1.0.30"
  # The git tree has no generated ./configure (that ships only in the
  # dist tarball); bootstrap it from configure.ac first. The runner has
  # no autotools preinstalled.
  command -v autoreconf >/dev/null || brew install autoconf automake libtool
  autoreconf --install --force
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
