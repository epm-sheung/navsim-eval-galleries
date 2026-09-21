# NAVSIM evaluation galleries

Interactive evaluation of camera-only DINOv2 waypoint models on the NAVSIM benchmark.

- **Scoreboard** — published vs. our numbers, v1 PDMS (navtest) and v2 EPDMS (navhard two-stage).
- **Scenes** — 210 scenes (150 navtest ranked by v1 PDMS, 60 navhard by v2 EPDMS) with
  per-method trajectory overlays drawn client-side.
- **Distributions** — per-method score distributions; click a bin for an example scene.
- **Figures** — five worked examples of paper-ready analysis figures, each paired with the
  published precedent it follows (or a note that none exists). Built from a 3 KB data slice by
  `figures/build_figures.py`.

Metric convention: navtest is scored with **NAVSIM v1.1 PDMS** (2 gates, 5 subscores);
navhard_two_stage with **v2 EPDMS** (4 gates, 9 subscores). The two are not interconvertible.
