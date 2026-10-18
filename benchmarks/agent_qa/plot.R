# Figures for the agent benchmark, from results.jsonl, questions.json and
# analyse.py's analysis.json (validity) and baselines.tsv (no-LLM answers).
#
#   uv run python benchmarks/agent_qa/analyse.py && Rscript benchmarks/agent_qa/plot.R
#
# Writes summary.tsv (verdicts, cost and time per setup over the headline
# questions and over all; verdicts per setup x kind of question; the no-LLM
# baselines) and four figures:
#   agent_qa.png             right / wrong / declined per setup and baseline,
#                            headline questions only (the README one)
#   agent_qa_cost_time.png   cost and seconds per answer, every run
#   agent_qa_by_category.png right / wrong / declined per setup x kind of question
#   agent_qa_error.png       each numeric answer's miss, in units of its band
# Bars count answers, not questions: questions x runs per setup. Every number
# on the figures is computed here from the log; nothing is typed in by hand.

library(ggplot2)
library(jsonlite)

args <- commandArgs(trailingOnly = TRUE)
results_path <- if (length(args) >= 1) args[1] else "benchmarks/agent_qa/results.jsonl"
outdir <- if (length(args) >= 2) args[2] else "benchmarks/agent_qa"
source("benchmarks/theme_breedsim.R")

r <- jsonlite::stream_in(file(results_path), verbose = FALSE)
# A run that failed the validity rule (analyse.py) is shown as "invalid", never
# as its scored verdict.
an <- jsonlite::fromJSON(file.path(dirname(results_path), "analysis.json"))
run_id <- function(x) paste(x$arm, x$qid, x$rep)
valid <- setNames(an$rows$valid, run_id(an$rows))
stopifnot(setequal(names(valid), run_id(r)))
r$verdict[!valid[run_id(r)]] <- "invalid"
not_headline <- names(an$not_headline_categories)
stopifnot(all(r$verdict %in% names(pal_verdict)))
key <- jsonlite::fromJSON("benchmarks/agent_qa/questions.json")$questions
stopifnot(length(not_headline) >= 1, all(not_headline %in% key$category))
half <- setNames(key$truth$half_width, key$id)
truth <- setNames(key$truth$value, key$id)
stopifnot(all(r$qid %in% names(half)))

arm_labels <- c(
  bare = "Claude alone",
  alt = "Claude + Bash, R and web",
  mcp = "Claude + breedsim-mcp"
)
stopifnot(all(r$arm %in% names(arm_labels)))
arm_labels <- arm_labels[names(arm_labels) %in% unique(r$arm)]
r$arm_label <- factor(arm_labels[r$arm], levels = rev(arm_labels))
r$verdict <- factor(r$verdict, levels = names(pal_verdict))

cat_labels <- c(
  control_response = "Control: one-cycle response (textbook answer is right)",
  long_term_gain = "Gain after 5-10 cycles, small population",
  remaining_variance = "Genetic variance left after 5-10 cycles",
  scheme_difference = "Difference between two schemes, 5-15 cycles",
  prob_beats = "Probability scheme A beats scheme B",
  genomic_accuracy = "Genomic prediction accuracy after 4-6 cycles"
)
stopifnot(all(r$category %in% names(cat_labels)))
cat_labels <- cat_labels[names(cat_labels) %in% unique(r$category)]

n_per_arm <- table(r$arm)
stopifnot(length(unique(n_per_arm)) == 1)
n_ans <- as.numeric(n_per_arm[1])
n_q <- length(unique(r$qid))
n_rep <- length(unique(r$rep))

tally <- function(x) {
  data.frame(
    right = sum(x$verdict == "right"), wrong = sum(x$verdict == "wrong"),
    declined = sum(x$verdict == "declined"), no_answer = sum(x$verdict == "no_answer"),
    invalid = sum(x$verdict == "invalid"),
    # Repeats of one question are not independent: also count questions.
    questions_right_every_run = sum(tapply(x$verdict == "right", x$qid, all)),
    median_abs_error_in_bands = round(median(abs(x$number - truth[x$qid]) / half[x$qid],
      na.rm = TRUE
    ), 2)
  )
}
arm_row <- function(a, x, category) {
  cbind(
    level = "arm", arm = a, category = category, tally(x),
    cost_usd_mean = round(mean(x$cost_usd), 4),
    cost_usd_median = round(median(x$cost_usd), 4),
    cost_usd_total = round(sum(x$cost_usd), 2),
    seconds_mean = round(mean(x$seconds), 1),
    seconds_median = round(median(x$seconds), 1),
    seconds_max = max(x$seconds),
    tool_calls_mean = round(mean(lengths(x$tool_calls)), 2)
  )
}
headline_label <- sprintf("headline (all but %s)", paste(not_headline, collapse = ", "))
per_arm <- do.call(rbind, c(
  lapply(names(arm_labels), function(a) {
    arm_row(a, r[r$arm == a & !(r$category %in% not_headline), ], headline_label)
  }),
  lapply(names(arm_labels), function(a) arm_row(a, r[r$arm == a, ], "all"))
))
per_cat <- do.call(rbind, lapply(names(arm_labels), function(a) {
  do.call(rbind, lapply(names(cat_labels), function(k) {
    cbind(
      level = "arm_x_category", arm = a, category = k,
      tally(r[r$arm == a & r$category == k, ]),
      cost_usd_mean = NA, cost_usd_median = NA, cost_usd_total = NA,
      seconds_mean = NA, seconds_median = NA, seconds_max = NA, tool_calls_mean = NA
    )
  }))
}))
# No-LLM baselines, one answer per question, scored by analyse.py through
# score.py. Two go on figure 1: the best single constant per category, and
# the best named closed form per question (an upper bound for theory alone).
bl <- read.delim(file.path(dirname(results_path), "baselines.tsv"), check.names = FALSE)
stopifnot(all(bl$qid %in% key$id))
bl_row <- function(name, x, category) {
  data.frame(
    level = "baseline", arm = name, category = category,
    right = sum(x$right), wrong = sum(!x$right), declined = 0, no_answer = 0, invalid = 0,
    questions_right_every_run = sum(x$right), median_abs_error_in_bands = NA,
    cost_usd_mean = NA, cost_usd_median = NA, cost_usd_total = NA,
    seconds_mean = NA, seconds_median = NA, seconds_max = NA, tool_calls_mean = NA
  )
}
per_base <- do.call(rbind, lapply(unique(bl$setup), function(b) {
  x <- bl[bl$setup == b, ]
  rbind(
    bl_row(b, x[!(x$category %in% not_headline), ], headline_label),
    do.call(rbind, lapply(unique(x$category), function(k) bl_row(b, x[x$category == k, ], k)))
  )
}))
# na = "NA", not "": a line ending in tabs is trailing whitespace the
# pre-commit hook strips, which would drop those columns.
write.table(rbind(per_arm, per_cat, per_base), file.path(outdir, "summary.tsv"),
  sep = "\t", quote = FALSE, row.names = FALSE, na = "NA"
)

setup_note <- sprintf("Claude Opus 5.5 in Claude Code, %d questions × %d runs.", n_q, n_rep)
legend_counts <- function(v, d = r) {
  sprintf("%s (%s)", v, vapply(v, function(k) {
    paste(vapply(names(arm_labels), function(a) {
      as.character(sum(d$verdict == k & d$arm == a))
    }, ""), collapse = " / ")
  }, ""))
}

# Figure 1: headline questions only. One bar per setup (answers = questions x
# runs) and per no-LLM baseline (one answer per question); segments = verdict
# share, labelled with counts.
h <- r[!(r$category %in% not_headline), ]
counts <- as.data.frame(table(arm_label = h$arm_label, verdict = h$verdict))
counts <- counts[counts$Freq > 0, ]
counts$share <- counts$Freq / ave(counts$Freq, counts$arm_label, FUN = sum)
base_labels <- c(
  "best constant: the category median of the key" = "No LLM: one constant per kind of question",
  "any named closed form (the best one per question)" = "No LLM: best closed form per question"
)
stopifnot(all(names(base_labels) %in% bl$setup))
hb <- bl[bl$setup %in% names(base_labels) & !(bl$category %in% not_headline), ]
bc <- as.data.frame(table(
  arm_label = base_labels[hb$setup], verdict = ifelse(hb$right, "right", "wrong")
))
bc <- bc[bc$Freq > 0, ]
bc$share <- bc$Freq / ave(bc$Freq, bc$arm_label, FUN = sum)
counts <- rbind(counts, bc)
counts$arm_label <- factor(counts$arm_label, levels = c(rev(base_labels), levels(r$arm_label)))
counts$verdict <- factor(counts$verdict, levels = names(pal_verdict))
n_head <- length(unique(h$qid))
# Name only the verdicts a bar actually shows, so the title cannot list one
# (e.g. "declined") that no setup produced.
shown <- names(pal_verdict)[names(pal_verdict) %in% counts$verdict]
shown_text <- if (length(shown) == 1) shown else {
  paste(paste(head(shown, -1), collapse = ", "), "or", tail(shown, 1))
}
substr(shown_text, 1, 1) <- toupper(substr(shown_text, 1, 1))
# Short plain names for the legend title, in arm order (the counts follow it).
legend_arms <- c(bare = "alone", alt = "own scripts", mcp = "breedsim-mcp")
stopifnot(all(names(arm_labels) %in% names(legend_arms)))
p1 <- ggplot(counts, aes(x = share, y = arm_label, fill = verdict)) +
  geom_col(width = 0.62, position = position_stack(reverse = TRUE)) +
  geom_text(
    aes(label = ifelse(share >= 0.05, Freq, ""), colour = verdict),
    position = position_stack(vjust = 0.5, reverse = TRUE),
    fontface = "bold", size = 4.2, show.legend = FALSE
  ) +
  scale_colour_manual(values = verdict_label_colour, guide = "none") +
  # Slices too thin to hold a number are counted in the legend instead.
  scale_fill_manual(
    values = pal_verdict, labels = function(v) legend_counts(v, h), drop = TRUE,
    name = sprintf("Headline answers (%s):", paste(legend_arms[names(arm_labels)], collapse = " / "))
  ) +
  guides(fill = guide_legend(title.position = "top", title.hjust = 0.5)) +
  scale_x_continuous(labels = scales::percent, expand = c(0, 0)) +
  labs(
    x = sprintf(
      "Share of answers: %d per setup (%d × %d runs), %d per baseline",
      n_head * n_rep, n_head, n_rep, n_head
    ), y = NULL,
    title = sprintf("%s, %d headline breeding-simulation questions", shown_text, n_head),
    # One line: the README shows this figure at 780 px. The questions left out
    # of the headline, and the key's replicate counts, are in the benchmark
    # README and agent_qa_by_category.png.
    subtitle = "Claude Opus 5.5 in Claude Code; key: AlphaSimR run directly on the stated founders."
  ) +
  theme_breedsim(base_size = 13) +
  theme(
    panel.grid.major.y = element_blank(), plot.margin = margin(8, 24, 8, 8),
    # Right-aligned to the panel: centred, it overruns the right edge at this width.
    axis.title.x = element_text(hjust = 1)
  )
# 8.5 in wide so that at the README's 780 px display width the axis and legend
# text (0.8 x base_size = 10.4 pt) render at about 13 px.
ggsave(file.path(outdir, "agent_qa.png"), p1, width = 8.5, height = 4.8, dpi = 200, bg = "white")

# Figure 2: cost and seconds per answer, one point per run, box over them.
long <- rbind(
  data.frame(arm_label = r$arm_label, metric = "Cost per answer (US$, log scale)", value = r$cost_usd),
  data.frame(arm_label = r$arm_label, metric = "Seconds per answer (log scale)", value = r$seconds)
)
p2 <- ggplot(long, aes(x = value, y = arm_label)) +
  geom_boxplot(width = 0.55, outlier.shape = NA, fill = "white", colour = "grey20") +
  geom_point(
    position = position_jitter(height = 0.18, seed = 1),
    shape = 21, size = breedsim_point_size, stroke = breedsim_point_stroke,
    fill = breedsim_point_fill, colour = breedsim_point_outline, alpha = 0.55
  ) +
  facet_wrap(~metric, ncol = 2, scales = "free_x") +
  scale_x_log10(labels = scales::label_number(drop0trailing = TRUE)) +
  labs(
    x = NULL, y = NULL, title = "Cost and time per answer",
    subtitle = paste0(
      setup_note, "\nOne point per run; the box spans the middle half, the line in it is the median."
    )
  ) +
  theme_breedsim(base_size = 13) +
  theme(panel.grid.major.y = element_blank(), plot.margin = margin(8, 24, 8, 8))
ggsave(file.path(outdir, "agent_qa_cost_time.png"), p2, width = 12, height = 4.2, dpi = 200, bg = "white")

# Figure 3: verdicts per setup x kind of question; strips name the counts.
n_cat <- table(r$category[r$arm == names(arm_labels)[1]])
strip <- setNames(
  sprintf("%s (%d questions × %d runs)", cat_labels, n_cat[names(cat_labels)] / n_rep, n_rep),
  names(cat_labels)
)
r$cat_strip <- factor(strip[r$category], levels = strip)
cc <- as.data.frame(table(arm_label = r$arm_label, cat_strip = r$cat_strip, verdict = r$verdict))
cc <- cc[cc$Freq > 0, ]
p3 <- ggplot(cc, aes(x = Freq, y = arm_label, fill = verdict)) +
  geom_col(width = 0.62, position = position_stack(reverse = TRUE)) +
  geom_text(
    aes(label = Freq, colour = verdict),
    position = position_stack(vjust = 0.5, reverse = TRUE),
    fontface = "bold", size = 3.4, show.legend = FALSE
  ) +
  scale_colour_manual(values = verdict_label_colour, guide = "none") +
  facet_wrap(~cat_strip, ncol = 1, scales = "free_x") +
  scale_fill_manual(values = pal_verdict, name = NULL, drop = TRUE) +
  scale_x_continuous(expand = c(0, 0)) +
  labs(
    x = "Answers", y = NULL, title = "Right, wrong or declined, by kind of question",
    subtitle = setup_note
  ) +
  theme_breedsim(base_size = 12) +
  theme(panel.grid.major.y = element_blank(), plot.margin = margin(8, 24, 8, 8))
ggsave(file.path(outdir, "agent_qa_by_category.png"), p3,
  width = 9, height = 1.2 + 1.3 * length(cat_labels), dpi = 200, bg = "white"
)

# Figure 4: how far each numeric answer landed, in units of its own band
# (|x| <= 1 is right). Declined and unanswered runs have no number and are
# counted in figures 1 and 3 instead. Clipped at ±6 bands so one far miss does
# not flatten the rest; clipped points sit on the panel edge.
e <- r[!is.na(r$number), ]
e$miss <- pmax(pmin((e$number - truth[e$qid]) / half[e$qid], 6), -6)
e$cat_strip <- factor(strip[e$category], levels = strip)
p4 <- ggplot(e, aes(x = miss, y = arm_label)) +
  annotate("rect", xmin = -1, xmax = 1, ymin = -Inf, ymax = Inf, fill = pal_verdict[["right"]], alpha = 0.12) +
  geom_vline(xintercept = 0, colour = breedsim_refline_colour, linewidth = 0.4) +
  geom_point(
    aes(fill = verdict),
    position = position_jitter(height = 0.2, width = 0, seed = 1),
    shape = 21, size = breedsim_point_size, stroke = breedsim_point_stroke,
    colour = breedsim_point_outline
  ) +
  scale_fill_manual(values = pal_verdict, name = NULL, drop = TRUE) +
  facet_wrap(~cat_strip, ncol = 1) +
  scale_x_continuous(limits = c(-6, 6), breaks = seq(-6, 6, 2)) +
  labs(
    x = "Answer minus the key, in units of the question's band (shaded: within the band)",
    y = NULL, title = "How far each answer landed from the key", subtitle = setup_note
  ) +
  theme_breedsim(base_size = 12) +
  theme(panel.grid.major.y = element_blank(), plot.margin = margin(8, 24, 8, 8))
ggsave(file.path(outdir, "agent_qa_error.png"), p4,
  width = 9, height = 1.2 + 1.3 * length(cat_labels), dpi = 200, bg = "white"
)

print(per_arm)
