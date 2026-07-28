# breedsim-mcp

**Breeding-scheme simulation over MCP — returns distributions, never a single stochastic run.**

Drives [AlphaSimR](https://github.com/gaynorr/AlphaSimR) so an agent can ask what a selection
programme would actually gain, with one structural rule: **a single simulation run is not a
result, and this API will not return one.**

Measured on AlphaSimR 2.1.0 — five seeds of an identical three-cycle programme gave mean
genetic gain `[1.151, 1.841, 1.424, 1.429, 1.473]`: **sd 0.247** on the very number being
reported. Quoting one run to three decimals reports noise with the authority of a measurement.
So `run_program` takes a replicate floor and returns per-cycle mean, sd and confidence
interval. There is no flag that collapses it to a point estimate.

> Unofficial. Not affiliated with, endorsed by, or sponsored by the AlphaSimR authors, the
> University of Edinburgh, or the R Foundation. See [NOTICE](NOTICE).

## Status

Under construction. See `docs/superpowers/plans/2026-07-28-breedsim-mcp.md`.

## Install tax — read this first

This is heavier than `uv pip install`, and the reasons are not negotiable:

- **R ≥ 4.3** with a shared library
- **AlphaSimR** — an Rcpp/RcppArmadillo compile, minutes not seconds
- **`libtirpc-dev`** — rpy2 fails to link without it (`cannot find -ltirpc`)
- **rpy2 pinned `<3.6`** — 3.6 binds `R_getVar`, which needs R ≥ 4.4

```bash
sudo apt-get install -y r-base libtirpc-dev
R -e 'install.packages("AlphaSimR", repos="https://cloud.r-project.org")'
uv add git+https://github.com/musharna/breedsim-mcp
```

## Reproducibility

Two independent things break it, and both were measured:

| source                | symptom                        | fix                                          |
| --------------------- | ------------------------------ | -------------------------------------------- |
| `runMacs` founder RNG | same seed → different founders | use `quickHaplo`, or persist founders once   |
| OpenMP in selection   | same seed → 2.397 vs 2.125     | `OMP_NUM_THREADS=1` **before R initialises** |

The server pins threads at import and reports whether it succeeded. With founders fixed and
threads pinned, seed 7 reproduces exactly: `meanG=2.01451853`, twice.

## Licence

**GPL-3.0-or-later** — because this imports rpy2, which is GPLv2+. AlphaSimR itself is MIT;
the licence here is about rpy2, not about AlphaSimR. See [NOTICE](NOTICE).
