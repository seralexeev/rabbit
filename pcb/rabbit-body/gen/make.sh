#!/bin/sh
# Full board generation: footprints -> placement + power routing -> zone fill -> autoroute -> cleanup -> fill -> DRC.
# Freerouting is deterministic for a given DSN: if a net stays unrouted, change the input (placement, widths), not the seed.
# SES=path/to/board.ses reuses an earlier route instead of running Freerouting (same netlist and pours).
set -e
cd "$(dirname "$0")/.."
PY=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3
python3 gen/footprints.py
$PY gen/build_board.py 2>&1 | grep -v "traits\|leak"
gen/fill.sh
mkdir -p ../../data/pcb-route
cp rabbit-body.kicad_pcb ../../data/pcb-route/preroute.kicad_pcb
if [ -n "$SES" ]; then
  $PY gen/import_ses.py "$SES" 2>&1 | grep -v "traits\|leak"
  gen/fill.sh
else
  $PY gen/autoroute.py ${PASSES:-60} 2>&1 | grep -v "traits\|leak"
fi
$PY gen/drc_summary.py >/dev/null 2>&1
$PY gen/cleanup.py 2>&1 | grep -v "traits\|leak"
gen/fill.sh
if [ -z "$SES" ] && [ "${PASSES2:-10}" != 0 ]; then   # second Freerouting run from the routed board for the leftovers
  $PY gen/autoroute.py ${PASSES2:-10} 2>&1 | grep -v "traits\|leak"
  $PY gen/drc_summary.py >/dev/null 2>&1
  $PY gen/cleanup.py 2>&1 | grep -v "traits\|leak"
  gen/fill.sh
fi
$PY gen/drc_summary.py 2>&1 | grep -v traits
