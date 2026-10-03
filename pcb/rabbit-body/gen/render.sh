#!/bin/sh
# 3D renders for the report: top, bottom, iso (kicad-cli), then the labelled top view (gen/annotate.py, needs matplotlib)
set -e
cd "$(dirname "$0")/.."
KC=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
mkdir -p renders
$KC pcb render -o renders/top.png --side top --width 1400 --height 3000 --background opaque --quality high rabbit-body.kicad_pcb >/dev/null
$KC pcb render -o renders/bottom.png --side bottom --width 1400 --height 3000 --background opaque --quality high rabbit-body.kicad_pcb >/dev/null
$KC pcb render -o renders/iso.png --rotate '-55,0,35' --width 1800 --height 1400 --zoom 1.1 --background opaque --quality high rabbit-body.kicad_pcb >/dev/null
"${PLOTPY:-python3}" gen/annotate.py
