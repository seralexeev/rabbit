#!/bin/sh
# Full board generation: model + footprints -> placement + pours -> autoroute -> cleanup -> fill -> DRC.
# Freerouting is deterministic for a given DSN: if a net stays unrouted, change the input (placement), not the seed.
set -e
cd "$(dirname "$0")/.."
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
../../model/.venv/bin/python gen/models.py
python3 gen/footprints.py
$PY gen/build_board.py 2>&1 | grep -v "traits\|leak"
$PY gen/autoroute.py ${PASSES:-30} 2>&1 | grep -v "traits\|leak"
gen/fill.sh
$PY gen/drc_summary.py >/dev/null 2>&1
$PY gen/cleanup.py 2>&1 | grep -v "traits\|leak"
gen/fill.sh
$PY gen/drc_summary.py 2>&1 | grep -v traits
