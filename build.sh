#!/usr/bin/env bash
# Rebuild the flashable firmware image from web/ (see CLAUDE.md).
#
#   ./build.sh            -> build/GS108T-V3.0.4.10-newui-min.hex  (minified, the one to flash)
#                            build/GS108T-V3.0.4.10-newui.hex      (not minified, fallback)
#   ./build.sh --help-pages   also regenerate the help pop-ups from the stock firmware first
set -euo pipefail
cd "$(dirname "$0")"

STOCK=GS108T-V3.0.4.10.bin
OUT=build/GS108T-V3.0.4.10-newui
PY=python3

# The pack tool's addresses (file table, web pool) are only valid for this exact firmware.
STOCK_SHA256=bb1dd3e062891a923599f9575096904420e9fde3156c3426d54c2f2b6b5f8951
[[ -f "$STOCK" ]] || { echo "missing $STOCK (see README: Getting the stock firmware)"; exit 1; }
if [[ "$($PY -I -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" "$STOCK")" != "$STOCK_SHA256" ]]; then
  echo "FAIL: $STOCK is not the stock GS108T v1 3.0.4.10 firmware (SHA-256 mismatch)"; exit 1
fi

if [[ "${1:-}" == "--help-pages" ]]; then
  $PY -I tools/convert_help.py
fi

# Build stamp shown under System Information > Versions > Web interface
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  UI_VERSION="$(git rev-parse --short=8 HEAD 2>/dev/null || echo nocommit)"
  [[ -n "$(git status --porcelain -- web tools build.sh 2>/dev/null)" ]] && UI_VERSION="$UI_VERSION-dirty"
else
  UI_VERSION="nogit"
fi
UI_VERSION="$UI_VERSION · $(date +%Y-%m-%d)"
echo "== UI version: $UI_VERSION"

echo "== 1/3 stock round trip (proves the pack tool is sound)"
$PY -I tools/gs108t_web.py verify "$STOCK" | tail -1

echo "== 2/3 pack"
mkdir -p build
$PY -I tools/gs108t_web.py pack "$STOCK" web -o "$OUT-min.bin" --hex "$OUT-min.hex" --minify --ui-version "$UI_VERSION" | grep -E "packed|wrote"
$PY -I tools/gs108t_web.py pack "$STOCK" web -o "$OUT.bin" --hex "$OUT.hex" --ui-version "$UI_VERSION" | grep -E "wrote"

echo "== 3/3 checks"
$PY -I tools/gs108t_web.py checkhex "$OUT-min.hex" "$OUT.hex"
$PY -I - "$STOCK" "$OUT-min.bin" <<'EOF'
import sys
a = open(sys.argv[1], "rb").read(); b = open(sys.argv[2], "rb").read()
code = sum(1 for i in range(0x10bc, 0x258a04) if a[i] != b[i])   # .text, file offsets
if len(a) != len(b) or code:
    sys.exit("FAIL: firmware code changed (%d bytes) - do not flash" % code)
print("code unchanged: OK")
EOF
# keep every build: the devserver needs the image the switch is running to read its pages
TAG="$(echo "$UI_VERSION" | cut -d' ' -f1)"
mkdir -p build/archive
cp "$OUT-min.bin" "build/archive/$TAG-min.bin"
echo "archived: build/archive/$TAG-min.bin"
echo
echo "Flash: .venv/bin/python tools/flash.py $OUT-min.hex   (dry run; add --upload to flash)"
