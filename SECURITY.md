# Security Policy

## Supported versions

`breedsim-mcp` ships fixes against the latest released version only. The current
release is **v0.4.1**. Please reproduce any issue on the latest release
(`uvx breedsim-mcp` always pulls it) before reporting.

| Version         | Supported          |
| --------------- | ------------------ |
| latest (0.4.x) | :white_check_mark: |
| < latest        | :x:                |

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.**

Report privately, either way:

- Preferred: use GitHub's **"Report a vulnerability"** button under the repo's
  **Security** tab (private security advisories), or
- Email **mjarnold1998@gmail.com**.

Please include a description of the issue, the affected version, and a minimal
reproduction. You can expect an initial acknowledgement within a few days. Once a
fix ships, you'll be credited in the release notes unless you ask otherwise.

## Security model

This server runs **R code in the same process**, through `rpy2`. That is the part
of the surface worth understanding before you deploy it.

- **Caller-supplied strings do not reach R.** R statements are assembled by
  interpolating two things: numeric parameters that pydantic has already validated
  and range-checked, and R identifiers the server generates itself
  (`.bs_<uuid4 hex>`, `session.py`). A `session_id` from a caller is used only as a
  dictionary key — an unknown one raises `UnknownSession` rather than being
  substituted into a statement. There is no path by which a caller composes R.
- **The R session is shared and long-lived.** Objects for every session live in one
  interpreter, namespaced by the generated prefix. Sessions are evicted LRU. A
  process running this server holds simulation state in memory until it exits.
- **No network access.** The server performs no outbound requests. It needs R,
  AlphaSimR and `libtirpc-dev` present on the host, and it fails loudly at import
  naming whichever is missing.
- **No filesystem reads or writes** are performed on caller-supplied paths; the
  tools take numeric parameters and identifiers only.

The realistic risk here is resource exhaustion, not code execution: a large
`n_founders` x `n_chr` x `cycles` request is CPU- and memory-expensive, and nothing
in the server caps how much work a caller may ask for. Run it where that is
acceptable.
