#!/usr/bin/env bash
# One tier's confirmatory sweep (PREREG_2026-10-20_model-tiers.md): probe the
# usage windows on the tier's model, wait for five_hour < 0.50, stop at
# seven_day >= 0.90 or under 5 GB free, then take the sweep lock and sweep.
set -uo pipefail
M=$1
A=~/breedsim-mcp-artifacts/tiers_1020/$M
WT=~/breedsim-mcp/.claude/worktrees/model-tiers
SPEC=git+https://github.com/musharna/breedsim-mcp@6c095adc1df0c7634642edcccdfaa4823ed2f004
mkdir -p "$A"
probe() {
        local d
        d=$(mktemp -d "$A/probe.XXXX")
        echo '{"mcpServers": {}}' >"$d/e.json"
        (cd "$d" && timeout 300 claude -p "Reply with OK." --model "$M" --setting-sources "" \
                --tools "" --strict-mcp-config --mcp-config "$d/e.json" --output-format stream-json --verbose >"$d/t.jsonl" || true)
        timeout 30 python3 -I -c '
import json,sys
ev=[json.loads(l) for l in open(sys.argv[1]) if l.startswith("{")]
i=next((e["rate_limit_info"] for e in reversed(ev) if e.get("type")=="rate_limit_event"),{})
w=i.get("unifiedWindows") or {}
print((w.get("five_hour") or {}).get("utilization",1), (w.get("seven_day") or {}).get("utilization",1), int(float((w.get("five_hour") or {}).get("resetsAt") or i.get("resetsAt") or 0)))' "$d/t.jsonl"
}
sweep() {
        python3 benchmarks/agent_qa/run.py --model "$M" --arms bare,alt,mcp --reps 3 --workers 1 \
                --results "$A/results.jsonl" --runs "$A/runs" --work "$A/work" \
                --server-spec "$SPEC" --exclude-newer 2026-10-17
}
cd "$WT" || exit 1
while true; do
        read -r five seven reset < <(probe)
        echo "probe $(date +%H:%M) $M five_hour=$five seven_day=$seven resets=$(date -d @"$reset" +%H:%M)"
        if python3 -c "import sys; sys.exit(0 if float('$seven') >= 0.90 else 1)"; then
                echo "STOP: seven_day >= 0.90"
                exit 3
        fi
        if python3 -c "import sys; sys.exit(0 if float('$five') < 0.50 else 1)"; then break; fi
        now=$(date +%s)
        wait=$((reset > now ? reset - now + 120 : 600))
        echo "waiting ${wait}s for the five-hour window"
        sleep "$wait"
done
avail=$(df --output=avail -BG / | tail -1 | tr -dc 0-9)
echo "disk free ${avail}G"
if [ "$avail" -lt 5 ]; then
        echo "STOP: under 5 GB free"
        exit 4
fi
echo "pilot start $M $(date)"
python3 benchmarks/agent_qa/run.py --model "$M" --arms bare,alt,mcp --reps 1 --workers 1 --only q12,q36 \
        --results "$A/pilot/results.jsonl" --runs "$A/pilot/runs" --work "$A/pilot/work" \
        --server-spec "$SPEC" --exclude-newer 2026-10-17 || {
        echo "STOP: pilot run.py failed"
        exit 5
}
python3 -I ~/breedsim-mcp-artifacts/tiers_1020/pilot_check.py "$A/pilot/results.jsonl" "$M" 6 || exit 5
echo "sweep start $M $(date)"
sweep
rc=$?
echo "sweep exit $rc $(date)"
[ "$rc" -ne 0 ] && exit "$rc"
python3 benchmarks/agent_qa/run.py --model "$M" --drop-api-failures --results "$A/results.jsonl"
echo "resume (re-runs API-failure rows once) $(date)"
sweep
rc=$?
echo "resume exit $rc $(date)"
exit "$rc"
