#!/usr/bin/env bash
# Re-measure the payload sizes in docs/v2.0-design.md §3.3.
#
# READ-ONLY. Every endpoint below reports state. Never add one that commands
# equipment — a rig may be imaging, and a wasted night is not recoverable.
#
#   scripts/measure_payloads.sh <host> [port]
set -euo pipefail

HOST="${1:?usage: measure_payloads.sh <host> [port]}"
PORT="${2:-1888}"
BASE="http://${HOST}:${PORT}/v2/api"

PATHS=(
  "/version"
  "/application-start"
  "/equipment/info"
  "/sequence/json"
  "/sequence/state"
  "/image-history?count=true"
  "/image-history"
  "/image-history?all=true"
  "/event-history"
  "/flats/status"
  "/livestack/status"
  "/equipment/focuser/last-af"
)

printf '%-34s %10s\n' "endpoint" "bytes"
for path in "${PATHS[@]}"; do
  bytes=$(curl -sS --max-time 30 "${BASE}${path}" | wc -c | tr -d ' ')
  printf '%-34s %10s\n' "$path" "$bytes"
done
