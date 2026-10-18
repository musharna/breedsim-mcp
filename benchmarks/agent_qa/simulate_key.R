# The agent benchmark's answer key: each design simulated in AlphaSimR directly.
#
#   Rscript benchmarks/agent_qa/simulate_key.R designs.json out.json
#
# Written against AlphaSimR, sharing no code with breedsim_mcp. It does share
# the ENGINE, as plant-genomics-mcp's key shares Ensembl with that server: the
# benchmark measures whether an agent sets up and runs the stated simulation
# correctly, not whether AlphaSimR is right.
#
# Every question fixes its founders (one set.seed, then the calls below in
# this order, which is also the order breedsim-mcp's found_population uses), so
# the key is the expectation over replicate seeds for THAT founder set. Each
# replicate reseeds before newPop; a two-arm design runs both arms from the
# same replicate seed (paired, as compare_programs does).
#
# Genomic selection follows the steps the question states: fit RRBLUP on the
# current generation, select on the fitted EBVs, make progeny, predict the
# progeny with the same model, and score accuracy as cor(EBV, true genetic
# value) on the progeny (0 when undefined).

suppressMessages(library(AlphaSimR))
library(jsonlite)

args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 2)
designs <- fromJSON(args[1], simplifyVector = FALSE)

found <- function(d) {
  set.seed(d$founder_seed)
  founders <- quickHaplo(nInd = d$n_ind, nChr = d$n_chr, segSites = d$seg_sites)
  SP <- SimParam$new(founders)
  SP$addTraitA(nQtlPerChr = d$n_qtl_per_chr)
  if (d$n_snp_per_chr > 0) SP$addSnpChip(nSnpPerChr = d$n_snp_per_chr)
  SP$setVarE(h2 = d$h2)
  list(founders = founders, SP = SP)
}

run_arm <- function(f, seed, arm, cycles) {
  SP <- f$SP
  set.seed(seed)
  pop <- newPop(f$founders, simParam = SP)
  gain <- vg <- acc <- rep(NA_real_, cycles)
  for (t in seq_len(cycles)) {
    if (arm$method == "pheno") {
      sel <- selectInd(pop, nInd = arm$n_select, use = "pheno", simParam = SP)
      pop <- randCross(sel, nCrosses = arm$n_cross, simParam = SP)
    } else {
      sol <- RRBLUP(pop, traits = 1, simParam = SP)
      pop <- setEBV(pop, sol, simParam = SP)
      sel <- selectInd(pop, nInd = arm$n_select, use = "ebv", simParam = SP)
      pop <- randCross(sel, nCrosses = arm$n_cross, simParam = SP)
      pop <- setEBV(pop, sol, simParam = SP)
      a <- suppressWarnings(cor(as.numeric(ebv(pop)[, 1]), as.numeric(gv(pop)[, 1])))
      acc[t] <- if (is.na(a)) 0 else a
    }
    gain[t] <- meanG(pop)
    vg[t] <- varG(pop)
  }
  list(gain = gain, var = vg, acc = acc)
}

out <- lapply(designs, function(d) {
  f <- found(d)
  res <- list()
  for (arm in d$arms) res[[arm$label]] <- list(gain = list(), var = list(), acc = list())
  for (i in seq_len(d$replicates)) {
    seed <- d$seed0 + i - 1
    for (arm in d$arms) {
      r <- run_arm(f, seed, arm, d$cycles)
      res[[arm$label]]$gain[[i]] <- r$gain
      res[[arm$label]]$var[[i]] <- r$var
      res[[arm$label]]$acc[[i]] <- r$acc
    }
  }
  list(id = d$id, arms = res)
})
write(toJSON(out, digits = NA, auto_unbox = TRUE, na = "null"), args[2])
