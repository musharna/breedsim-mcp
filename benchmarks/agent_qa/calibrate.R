# Independent AlphaSimR runs of each benchmark design, for the answer key's BAND.
#
#   Rscript benchmarks/agent_qa/calibrate.R designs.json out.json
#
# The key's centre comes from theory.py. This script only measures how far a
# correct simulation of the same design lands from that centre, so the band
# can be wide enough to accept it. It is written against AlphaSimR directly
# and shares no code with breedsim_mcp.
#
# Each design is run on K founder sets (one quickHaplo draw per founder seed)
# times S replicate seeds per set, the layout a user of the server gets: one
# founder set per session, replicates differing in seed. Both variance
# components are reported, so the band can include the founder-set part that
# more replicates on one session cannot remove.
#
# A design with two arms (a paired comparison) runs both arms from the same
# replicate seed, as compare_programs does.

suppressMessages(library(AlphaSimR))
library(jsonlite)

args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
designs <- fromJSON(args[1], simplifyVector = FALSE)

run_arm <- function(founders, SP, seed, n_select, n_cross, cycles) {
  set.seed(seed)
  pop <- newPop(founders, simParam = SP)
  gain <- numeric(cycles)
  vg <- numeric(cycles)
  for (t in seq_len(cycles)) {
    sel <- selectInd(pop, nInd = n_select, use = "pheno", simParam = SP)
    pop <- randCross(sel, nCrosses = n_cross, simParam = SP)
    gain[t] <- meanG(pop)
    vg[t] <- varG(pop)
  }
  list(gain = gain, var = vg)
}

out <- lapply(designs, function(d) {
  arms <- d$arms
  res <- lapply(arms, function(a) list(gain = list(), var = list()))
  names(res) <- vapply(arms, function(a) a$label, "")
  for (k in seq_len(d$founder_sets)) {
    fseed <- d$founder_seed0 + k
    set.seed(fseed)
    founders <- quickHaplo(nInd = d$n_ind, nChr = d$n_chr, segSites = d$seg_sites)
    SP <- SimParam$new(founders)
    SP$addTraitA(nQtlPerChr = d$n_qtl_per_chr)
    SP$setVarE(h2 = d$h2)
    for (s in seq_len(d$seeds)) {
      seed <- d$seed0 + 1000 * k + s
      for (a in arms) {
        r <- run_arm(founders, SP, seed, a$n_select, a$n_cross, d$cycles)
        res[[a$label]]$gain[[length(res[[a$label]]$gain) + 1]] <- c(k, s, r$gain)
        res[[a$label]]$var[[length(res[[a$label]]$var) + 1]] <- c(k, s, r$var)
      }
    }
  }
  list(id = d$id, arms = res)
})
write(toJSON(out, digits = NA, auto_unbox = TRUE), args[2])
