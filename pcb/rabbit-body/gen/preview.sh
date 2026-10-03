#!/bin/sh
# Plot board layers to PNG for review: gen/preview.sh <out.png> [layers]
set -e
cd "$(dirname "$0")/.."
OUT=${1:-/tmp/preview.png}
LAYERS=${2:-Edge.Cuts,F.Cu,F.SilkS,F.Fab,F.CrtYd,User.Drawings}
KC=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
TMP=$(mktemp -d)
$KC pcb export pdf --mode-single -o "$TMP/p.pdf" -l "$LAYERS" --scale 1 rabbit-body.kicad_pcb >/dev/null
"${PDFPY:-python3}" - "$TMP/p.pdf" "$OUT" <<'PY'
import sys, pymupdf
d = pymupdf.open(sys.argv[1]); p = d[0]
k = 72 / 25.4
clip = pymupdf.Rect(85 * k, 10 * k, 215 * k, 290 * k)
pix = p.get_pixmap(dpi=int(__import__('os').environ.get('DPI', '150')), clip=clip)
pix.save(sys.argv[2])
print(sys.argv[2], pix.width, pix.height)
PY
