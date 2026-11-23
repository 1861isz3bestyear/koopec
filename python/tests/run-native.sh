#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python_path=${PYO3_PYTHON:-$(command -v python3)}
cd "$root"
PYO3_PYTHON="$python_path" cargo build --locked --release --manifest-path "$root/Cargo.toml"
mkdir -p "$root/target/python"
case "$(uname -s)" in
    Darwin) library="$root/target/release/libkoopec_calculus.dylib" ;;
    *) library="$root/target/release/libkoopec_calculus.so" ;;
esac
extension=$(mktemp "$root/target/python/.koopec_calculus.XXXXXX")
trap 'test ! -f "$extension" || unlink "$extension"' EXIT
cp "$library" "$extension"
mv -f "$extension" "$root/target/python/koopec_calculus.so"
PYTHONPATH="$root/target/python${PYTHONPATH:+:$PYTHONPATH}" "$python_path" -m pytest "$root/tests/test_native.py" -o addopts= -q
