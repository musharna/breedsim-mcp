#!/usr/bin/env bash
# System prerequisites for the guardrails jobs (run before `uv sync`).
# Mirrors .github/workflows/ci.yml: rpy2 needs R headers (r-base-dev) and
# libtirpc-dev to link ("cannot find -ltirpc"); the tests need AlphaSimR.
set -euo pipefail
if ! command -v R >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq r-base r-base-dev libtirpc-dev
fi
mkdir -p ~/R/library
export R_LIBS_USER=~/R/library
Rscript -e 'if (!requireNamespace("AlphaSimR", quietly = TRUE)) install.packages("AlphaSimR", lib = Sys.getenv("R_LIBS_USER"), repos = "https://cloud.r-project.org", Ncpus = 4)'
