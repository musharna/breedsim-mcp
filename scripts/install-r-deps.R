# R packages the tests need, AlphaSimR pinned to the version the agent
# benchmark's key was built on (benchmarks/agent_qa/questions.json).
#
#   Rscript scripts/install-r-deps.R ~/R/library
#
# CRAN serves the current release from src/contrib and older ones from
# src/contrib/Archive, so both URLs are tried; the version is checked after.
ALPHASIMR <- "2.1.0"
args <- commandArgs(trailingOnly = TRUE)
lib <- path.expand(if (length(args)) args[1] else "~/R/library")
dir.create(lib, recursive = TRUE, showWarnings = FALSE)
repos <- "https://cloud.r-project.org"
have <- function(p) {
  tryCatch(as.character(packageVersion(p, lib.loc = c(lib, .libPaths()))),
           error = function(e) NA_character_)
}
need <- c("Rcpp", "RcppArmadillo", "BH", "R6", "Rdpack", "jsonlite")
missing <- need[is.na(vapply(need, have, ""))]
if (length(missing)) install.packages(missing, lib = lib, repos = repos, Ncpus = 4)
if (!identical(have("AlphaSimR"), ALPHASIMR)) {
  tarball <- sprintf("AlphaSimR_%s.tar.gz", ALPHASIMR)
  for (url in c(sprintf("%s/src/contrib/%s", repos, tarball),
                sprintf("%s/src/contrib/Archive/AlphaSimR/%s", repos, tarball))) {
    try(install.packages(url, lib = lib, repos = NULL, type = "source", Ncpus = 4))
    if (identical(have("AlphaSimR"), ALPHASIMR)) break
  }
}
got <- have("AlphaSimR")
if (!identical(got, ALPHASIMR)) stop("AlphaSimR ", ALPHASIMR, " not installed (have ", got, ")")
for (p in need) if (is.na(have(p))) stop(p, " not installed in ", lib)
cat("R deps OK: AlphaSimR", got, "in", lib, "\n")
