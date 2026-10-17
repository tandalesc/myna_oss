#!/bin/sh
# Build the core: the native shared library (libdbcore.dylib / .so), the runners dbrun and dbreplay, and the WebAssembly module
# dbcore.wasm, into ${DBCORE_OUT:-<this folder>/build}. Needs rustc and cargo; nothing is downloaded.
#
#   DBCORE_OUT           output folder (default: build/ next to this script)
#   DBCORE_RUSTFLAGS     flags of the native build (default: -C target-cpu=native; set it empty for a portable library)
#   DBCORE_WASM_SYSROOT  a Rust sysroot that holds the wasm32-unknown-unknown standard library
#                        (<sysroot>/lib/rustlib/wasm32-unknown-unknown). Not needed when the toolchain has the target installed.
#   DBCORE_WASM_LINKER   the linker for WebAssembly (default: the toolchain's own rust-lld)
# The WebAssembly build is skipped with a message when no standard library for it is found.
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${DBCORE_OUT:-$HERE/build}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)

# native
RUSTFLAGS="${DBCORE_RUSTFLAGS--C target-cpu=native}" CARGO_TARGET_DIR="$OUT/target" \
    cargo build --release --offline --manifest-path "$HERE/Cargo.toml"
for f in libdbcore.dylib libdbcore.so dbcore.dll dbrun dbrun.exe dbreplay dbreplay.exe; do
    if [ -f "$OUT/target/release/$f" ]; then cp "$OUT/target/release/$f" "$OUT/$f"; fi
done

# WebAssembly
HOST=$(rustc -vV | sed -n 's/^host: //p')
TOOL=$(rustc --print sysroot)
SYS=${DBCORE_WASM_SYSROOT:-$TOOL}
LINKER=${DBCORE_WASM_LINKER:-$TOOL/lib/rustlib/$HOST/bin/rust-lld}
if [ ! -d "$SYS/lib/rustlib/wasm32-unknown-unknown/lib" ]; then
    echo "build.sh: no wasm32-unknown-unknown standard library under $SYS: WebAssembly build skipped (set DBCORE_WASM_SYSROOT)"
elif [ ! -x "$LINKER" ]; then
    echo "build.sh: no linker at $LINKER: WebAssembly build skipped (set DBCORE_WASM_LINKER)"
else
    rustc --edition 2021 --crate-name dbcore --crate-type cdylib --target wasm32-unknown-unknown --sysroot "$SYS" \
        -C linker="$LINKER" -C opt-level=3 -C panic=abort -C codegen-units=1 -C strip=symbols \
        "$HERE/src/lib.rs" -o "$OUT/dbcore.wasm"
fi
ls -l "$OUT" | grep -E 'dbcore|dbrun|dbreplay' || true
