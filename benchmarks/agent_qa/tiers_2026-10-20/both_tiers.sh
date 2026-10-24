#!/usr/bin/env bash
# Haiku only (coordinator 10-20 22:50 EDT: seven_day 0.84; every server's Haiku
# sweep runs before any Sonnet; Sonnet waits for the coordinator's go).
set -uo pipefail
G=~/breedsim-mcp-artifacts/tiers_1020/gated_sweep.sh
echo "lock acquired $(date)"
"$G" claude-haiku-5-5
rc=$?
echo "haiku tier exit $rc $(date)"
exit "$rc"
