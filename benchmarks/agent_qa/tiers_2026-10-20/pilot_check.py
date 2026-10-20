"""Pilot gate: every pilot run exited 0, was served the requested model, and
each tool arm was offered its tools and used them. Feasibility only; the
pilot's verdicts are not read."""

import json
import signal
import sys
from pathlib import Path

signal.alarm(30)
rows = [
    json.loads(ln) for ln in Path(sys.argv[1]).read_text().splitlines() if ln.strip()
]
want = sys.argv[2]
bad = []
for r in rows:
    t = f"{r['arm']} {r['qid']}"
    if r["exit"] != 0:
        bad.append(f"{t}: exit {r['exit']}")
    if not str(r.get("model")).startswith(want):
        bad.append(f"{t}: served {r.get('model')}")
    if r["arm"] == "alt" and "Bash" not in r["tools_available"]:
        bad.append(f"{t}: no Bash")
    if r["arm"] == "mcp" and not any(
        s.get("name") == "breedsim" and s.get("status") == "connected"
        for s in r["mcp_servers"] or []
    ):
        bad.append(f"{t}: server not connected")
    if r["arm"] != "bare" and not r["tool_calls"]:
        bad.append(f"{t}: no tool call")
for r in rows:
    print(
        f"pilot {r['arm']:4} {r['qid']} served={r.get('model')} {r['seconds']}s calls={len(r['tool_calls'])} ${r['cost_usd']}"
    )
print(f"pilot runs {len(rows)}, cost ${sum(r['cost_usd'] or 0 for r in rows):.4f}")
if bad or len(rows) != int(sys.argv[3]):
    print("PILOT FAILED:", bad or f"{len(rows)} rows")
    sys.exit(5)
print("pilot ok")
