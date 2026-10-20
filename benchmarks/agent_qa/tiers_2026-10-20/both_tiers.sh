#!/usr/bin/env bash
# Haiku, then Sonnet right after (amendment 10-20), inside one hold of the sweep lock.
set -uo pipefail
G=~/breedsim-mcp-artifacts/tiers_1020/gated_sweep.sh
echo "lock acquired $(date)"
"$G" claude-haiku-5-5; rc=$?; echo "haiku tier exit $rc $(date)"
[ "$rc" -ne 0 ] && exit "$rc"
"$G" claude-sonnet-5-5; rc=$?; echo "sonnet tier exit $rc $(date)"
exit "$rc"
