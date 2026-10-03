#!/bin/sh
# Refill all zones with kicad-cli (the pcbnew Python filler ignores hole and edge clearances) and save.
cd "$(dirname "$0")/.."
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb drc --refill-zones --save-board -o /tmp/rabbit-body-fill.rpt rabbit-body.kicad_pcb >/dev/null
sed -i '' 's/(paper "A4")/(paper "A3" portrait)/' rabbit-body.kicad_pcb
