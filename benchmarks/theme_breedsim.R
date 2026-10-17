# House ggplot2 theme + palette for breedsim-mcp figures.
#
# `grep -rn "theme_" --include=*.R .` (2026-10-16) found no R file in this
# repo, so this is the first; it is modelled on plant-genomics-mcp's
# examples/arf_family/theme_pgmcp.R so the two servers' benchmark figures read
# alike. Every plotting script sources this file and adds only the geoms and
# scales specific to one figure; restyle here, never inline.

theme_breedsim <- function(base_size = 12) {
  ggplot2::theme_minimal(base_size = base_size) +
    ggplot2::theme(
      panel.grid.minor = ggplot2::element_blank(),
      legend.position = "bottom",
      # Several legends stack in their own rows rather than one row that runs
      # off the right edge at a fixed figure width.
      legend.box = "vertical",
      legend.spacing.y = grid::unit(0, "pt"),
      legend.box.spacing = grid::unit(6, "pt"),
      legend.margin = ggplot2::margin(0, 0, 0, 0),
      plot.title.position = "plot",
      strip.text = ggplot2::element_text(hjust = 0, face = "bold")
    )
}

# Verdicts, the same colours in every figure: green right, red wrong, light
# grey declined, orange for a reply with no ANSWER line, dark grey for a run
# that failed the validity rule (benchmarks/agent_qa/analyse.py).
pal_verdict <- c(
  right = "#2E7D5B",
  wrong = "#C0392B",
  declined = "#BDBDBD",
  no_answer = "#E69F00",
  invalid = "#4D4D4D"
)
# Count labels: white on green, red, orange and dark grey; dark on the light grey.
verdict_label_colour <- c(
  right = "white", wrong = "white", declined = "grey15", no_answer = "grey15",
  invalid = "white"
)

# Per-run scatter (shape 21) over a box: thin white outline so overlapping
# points stay countable.
breedsim_point_size <- 1.8
breedsim_point_stroke <- 0.4
breedsim_point_outline <- "white"
breedsim_point_fill <- "grey35"

# Reference lines (the theory value, a band edge).
breedsim_refline_colour <- "grey40"
