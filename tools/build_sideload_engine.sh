#!/usr/bin/env bash
# Build the gn-sideload signing engine for packaging into the frozen app.
#
# Usage: tools/build_sideload_engine.sh [universal2 | native]
#
#   universal2 — macOS only: cargo builds the engine for BOTH
#     x86_64-apple-darwin and aarch64-apple-darwin and lipo merges the two
#     slices into target/release/gn-sideload (one universal binary —
#     compile.py bundles exactly that file into the Universal2 app, see the
#     "gn-sideload signing engine" block there).
#   native (default) — plain `cargo build --release` for the running host.
#
# The Python side resolves the product via mobile_helper.find_engine(), whose
# bundled-copy candidate is the PyInstaller bundle root — that is where
# compile.py --add-binary lands this binary.
set -euo pipefail

mode="${1:-native}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT/tools/sideload-engine"

# cargo from rustup still resolves rustc through PATH; a prior entry (e.g.
# /opt/local/bin/rustc from MacPorts) would be picked instead and it carries
# no rustup std for cross targets ("can't find crate for `core`"). Pin the
# rustup toolchain's bin directory ahead of everything else.
RUSTUP_BIN="$(dirname "$(rustup which rustc)")"
export PATH="$RUSTUP_BIN:$PATH"

if [ "$mode" = "universal2" ]; then
    if [ "$(uname -s)" != "Darwin" ]; then
        echo "error: universal2 engine build requires a macOS host" >&2
        exit 1
    fi
    for target in x86_64-apple-darwin aarch64-apple-darwin; do
        if ! rustup target list --installed | grep -q "^${target}\$"; then
            rustup target add "$target"
        fi
        cargo build --release --target "$target"
    done
    mkdir -p target/release
    lipo -create \
        target/x86_64-apple-darwin/release/gn-sideload \
        target/aarch64-apple-darwin/release/gn-sideload \
        -output target/release/gn-sideload
    echo "universal2 gn-sideload ready: $(lipo -info target/release/gn-sideload)"
elif [ "$mode" = "native" ]; then
    cargo build --release
    echo "native gn-sideload ready: target/release/gn-sideload$(uname -s | grep -q MINGW && echo .exe)"
else
    echo "usage: $0 [universal2 | native]" >&2
    exit 2
fi
