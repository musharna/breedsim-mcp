"""Regenerate the two JSON examples in README.md by calling the MCP tools.

Every call goes through `call_tool`, the layer a client uses, with the
parameters printed alongside the output, so the README examples can be checked
by re-running this rather than trusted.

    uv run python scripts/readme_examples.py

Needs AlphaSimR on R's library path; set R_LIBS_USER if it lives in a user
library. Both examples use `quickHaplo` founders, which are reproducible from a
seed, and the server pins OMP threads at import, so a re-run prints the same
numbers on the same engine versions. Takes a few seconds.
"""

import asyncio
import json

from breedsim_mcp.server import build_server

FOUND = {"generator": "quickHaplo", "seed": 1}  # every other argument at default
RUN = {"cycles": 2, "replicates": 10, "n_select": 10, "n_cross": 60, "base_seed": 1000}
COMPARE = {
    "a_n_select": 12,
    "b_n_select": 18,
    "a_n_cross": 100,
    "b_n_cross": 100,
    "cycles": 2,
    "replicates": 10,
}


def main() -> None:
    srv = build_server()

    def call(name: str, args: dict) -> dict:
        return asyncio.run(srv.call_tool(name, args)).structured_content

    methods = call("list_methods", {})
    print("package", srv.version)
    for key in ("r_version", "alphasimr_version", "rpy2_version", "reproducible"):
        print(key, methods[key])

    session = call("found_population", FOUND)["session_id"]
    print(f"\n## run_program — found_population({FOUND}), run_program({RUN})")
    print(json.dumps(call("run_program", {"session_id": session, **RUN}), indent=2))

    session = call("found_population", FOUND)["session_id"]
    print(
        f"\n## compare_programs — found_population({FOUND}), compare_programs({COMPARE})"
    )
    print(
        json.dumps(
            call("compare_programs", {"session_id": session, **COMPARE}), indent=2
        )
    )


if __name__ == "__main__":
    main()
