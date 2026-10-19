#!/bin/sh
# 3D renders: front (sensor face), back (connector face, seen from behind, so mirrored left-right) and two iso views.
set -e
cd "$(dirname "$0")/.."
KC=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
mkdir -p renders
$KC pcb render -o renders/front.png --side top --width 1600 --height 1320 --zoom 1.0 --background opaque --quality high rabbit-tof.kicad_pcb >/dev/null
$KC pcb render -o renders/back.png --side bottom --width 1600 --height 1320 --zoom 1.0 --background opaque --quality high rabbit-tof.kicad_pcb >/dev/null
$KC pcb render -o renders/iso_front.png --rotate '-45,0,25' --width 1600 --height 1200 --zoom 0.9 --background opaque --quality high rabbit-tof.kicad_pcb >/dev/null
$KC pcb render -o renders/iso_back.png --rotate '135,0,-25' --width 1600 --height 1200 --zoom 0.9 --background opaque --quality high rabbit-tof.kicad_pcb >/dev/null
