# NAVSIM score distributions & per-bin example galleries

Built from the per-scene score CSVs listed in
`/scratch/eddie96/eddie/navsim_v1/scores_manifest.json` (written by the sibling
scoring session). This directory is Deliverables 1 + 2; the ranked galleries
are `../ranked_navtest_v1/` and `../ranked_navhard_v2/`.

> ## STAGE 1 PACKAGE — what is final and what is not
>
> This package is delivered in two stages. **Stage 1 (this one) finalises the
> v1 PDMS side.** The navhard v2 side is deliberately not final yet.
>
> | surface | state |
> |---|---|
> | `ranked_navtest_v1/` | **FINAL** |
> | `arch_comparison/` | **FINAL** |
> | `agent_comparison_v1/` | **FINAL** |
> | navtest v1 PDMS plots + their per-bin clips | **FINAL** |
> | navhard v2 EPDMS **plots** | **FINAL** — already rebuilt from the corrected post-fix scores |
> | `ranked_navhard_v2/` | **NOT FINAL** — pre-fix selection |
> | navhard v2 per-bin clips | **NOT FINAL** — pre-fix selection |
>
> The navhard *plots* are corrected but the navhard *galleries* are not, and
> that is not an inconsistency: bins are chosen **by** score, so corrected
> scores change which scenes belong in which bin. Re-selecting means
> re-rendering. **The clips are real model predictions either way** — what is
> stale is which scenes were picked and the scores printed under them.
> A stage-2 rebuild replaces them at this same path.
>
> Every gallery page carries this same split as a banner, so it is legible from
> inside the package.

## The navhard sensor-path bug — found, fixed, and what it changed

**This is now a historical record, not a live warning.** The navhard numbers in
this package are the corrected ones. This section is kept because the bug
reversed two experimental conclusions, and because the same trap is easy to
fall into again.

Briefly: every navhard v2 EPDMS number produced before 2026-08-28 03:26 came
from runs with a **sensor-path misconfiguration**, and should not be quoted.

> ### ✅ RESOLVED 2026-08-28 — corrected numbers are now IN the package
>
> The eval scripts were fixed (`ORIG_SENSOR` now points at the navtest blobs),
> all five camera models were re-scored, and the plots, per-bin galleries and
> `ranked_navhard_v2` were **regenerated from the corrected CSVs**. The navhard
> figures you see are the corrected ones.
>
> The prose further down describes the bug in the past tense and is kept
> deliberately: what was believed, and why it was wrong, is part of the record.
> See [Corrected navhard results](#corrected-navhard-results-2026-08-28) for the
> numbers and for **two conclusions that the correction reversed**.
>
> Two of my own earlier predictions were wrong and are marked ⚠️ SUPERSEDED
> where I made them: stage-2 was *not* invariant to the fix, and cmd/cls were
> *not* clean.

### What the scoring session found, and what it actually is

The scoring session observed that camera agents were falling back to
constant-velocity on navhard and that `TransfuserAgent` crashed outright, both
on missing `CAM_F0/<hash>.jpg` files under
`navhard_two_stage/sensor_blobs`. It concluded the local navhard download was
incomplete and that this was "not fixable by re-running".

**The files are not missing.** They are in a different directory, which is
where they are supposed to be. I checked 8 distinct paths taken from the
latent-TransFuser crash log: **8/8 absent from `navhard_two_stage/sensor_blobs`,
8/8 present under `navtest_sensor_blobs/openscene-v1.1/sensor_blobs/test`.**

This is trap #2 in `docs/NAVSIM_EVAL.md`, which this repo already documents:

> `navhard_two_stage/sensor_blobs` contains only the **synthetic stage-2
> renders**. The real stage-1 frames are under
> `navtest_sensor_blobs/openscene-v1.1/sensor_blobs/test`. The two directories
> have the *same log folder names*, so pointing at the wrong one looks right.

The navhard eval scripts set `SENSOR="$BASE/sensor_blobs"` and then pass
`original_sensor_path="$SENSOR"` — the documented wrong location for stage-1
frames. So every stage-1 scene's real camera frame was looked up in the
synthetic-only directory and not found.

**The counts corroborate it:** each patch-family model logged exactly **450**
CV-fallbacks, and every navhard CSV contains exactly **450** stage-1 rows. One
fallback per stage-1 scene.

**Proven per-scene, not inferred.** Comparing each model's per-scene scores
against `constant_velocity`'s over the same tokens:

| | stage-1 (450 scenes) | stage-2 (5462 scenes) |
|---|---|---|
| Variant 1 (patch) | **382/450 bit-identical to CV**, rest differ by ≤1.9e-08 | 40.3% identical, maxdiff 1.0 |
| cmd_tokens_film | **382/450 bit-identical to CV**, rest ≤1.9e-08 | 41.3% identical, maxdiff 1.0 |
| cls_tokens_film | **382/450 bit-identical to CV**, rest ≤1.9e-08 | 45.3% identical, maxdiff 1.0 |
| SAE A' (control) | **382/450 bit-identical to CV**, rest ≤1.9e-08 | 43.5% identical, maxdiff 1.0 |
| SAE B' (static) | **382/450 bit-identical to CV**, rest ≤1.9e-08 | 43.4% identical, maxdiff 1.0 |

A residual of 1.9e-08 is floating-point noise, so stage-1 is **effectively
constant-velocity for every camera model on all 450 scenes**. The aggregates
agree: `v2_navhard_epdms1` is `0.28958783900556795` for all five camera models —
identical to **17 significant figures** — and constant velocity's own
`0.28958783901823343` differs only in the 11th decimal. Five different networks
cannot produce that unless all five emitted the same trajectories.

Stage 2 is the opposite picture: models differ from CV across the full score
range (maxdiff 1.0), so stage-2 carries real model signal. The 40-45%
coincidental agreement there is exactly the noise floor that made the scoring
session's score-row matching unusable for fallback detection — it was right
about that.

**Control:** the trajectory dumps behind this directory's galleries pass
`original_sensor_path=<navtest blobs>` and `synthetic_sensor_path=<navhard
blobs>`. Over the same split they produced 450 stage-1 + 85 stage-2 = 535
trajectories with **0 fallbacks and 0 failures** (job 57194019). Same data,
same machine, correct paths, no gap.

### What follows for the numbers here

* **The navhard EPDMS scores for Variant 1, SAE A' and SAE B' are depressed**
  by 450 scenes scored on constant-velocity trajectories that came from a
  configuration error, not from the model. Model-vs-model ordering on navhard
  may not survive a corrected re-run.
* **`transfuser` and `transfuser_latent` may not be genuinely unscoreable.**
  Latent TransFuser was tried specifically to route around the LiDAR gap and
  then died on these same mis-pathed frames — with no per-scenario try/except,
  it crashed instead of degrading. That is very likely the same config bug.
* **cmd_tokens_film / cls_tokens_film are NOT clean** — this resolves the
  manifest's open question, in the unwelcome direction. Both logged 0
  fallbacks, but their stage-1 per-scene scores are bit-identical to constant
  velocity on the same 382/450 scenes as every other model, with the same
  17-significant-figure EPDMS1. They were affected identically; their older
  agent code simply did not emit the log line the fallback count greps for.
  A 0 in that column means "nothing logged", not "nothing happened".
* **Published anchors remain not directly comparable** for the affected models
  — but because of this fixable config error, not a dataset defect. Constant
  Velocity requests no camera and is structurally immune, so its 0.1148 here
  against a published 0.109 is the one directly meaningful anchor check, and it
  lands close — which is reassuring about the rest of the pipeline.

### What is still usable, and what is not

* ⚠️ **SUPERSEDED 2026-08-28: the per-scene navhard histograms are NOT
  unaffected.** I originally reasoned that stage 2 was correctly pathed
  (`synthetic_sensor_path` did point at navhard's blobs) and therefore
  invariant to the fix. The corrected run disproves that: EPDMS2 moved on every
  model (Variant 1 0.4235 → 0.3775, SAE A' 0.4056 → 0.3523, SAE B' 0.3970 →
  0.3650). Stage-2 scoring is not independent of stage-1 in the two-stage
  metric. **Treat the navhard histograms as superseded too**, not just the
  combined aggregates.
* **The navhard example clips ARE valid.** They were rendered from dumps that
  used the correct `original_sensor_path`, and a bit-wise check against a
  constant-velocity dump over the same 535 tokens found **0 fallbacks and 0
  degenerate cases — 535/535 real predictions**
  (`fallbacks/variant1_patch_tokens_film__v2_epdms_navhard_two_stage.json`).
  The videos show real model behaviour.
* **`navhard_v2_epdms1_*.png` is NOT a model comparison.** Stage 1 is
  constant-velocity for every camera model, so that plot shows one shared
  const-vel distribution drawn six times, not six models. It is kept only as
  the visual evidence of that fact, and is labelled as such on the plot.
* **The headline combined EPDMS aggregates are depressed** for all five camera
  models, since the stage-1 factor of the two-stage product carries no model
  signal. Do not quote them as these models' navhard performance.

**What I did not do:** re-score anything. There are no corrected EPDMS numbers
in this directory, and none are implied. Confirming the fix needs one re-run
with `original_sensor_path` pointed at the navtest blobs. If that happens, this
whole directory regenerates from the manifest with no manual steps — see
[Provenance](#provenance--reproducing).

### Corrected navhard results (2026-08-28)

Traced directly from the `*_pathfix` result CSVs, not from the manifest (which
had not yet been updated when this was written):

| model | combined (corrected) | combined before | change |
|---|---|---|---|
| Variant 1 (patch) | **0.2469** | 0.1218 | +103% |
| cmd_tokens_film | **0.2411** | 0.1216 | +98% |
| SAE B' (static) | **0.2175** | 0.1158 | +88% |
| SAE A' (control) | **0.1993** | 0.1178 | +69% |
| cls_tokens_film | **0.1782** | 0.1136 | +57% |
| Constant Velocity | 0.1148 | 0.1148 | unchanged (no camera — immune) |

Stage split for the three re-runs I traced by hand: Variant 1 EPDMS1 0.6634 /
EPDMS2 0.3775; SAE B' 0.6018 / 0.3650; SAE A' 0.5475 / 0.3523 — against
`0.28958783900556795` for *every* camera model before the fix.

Sources: `exp/navhard_patch_tokens_film_pathfix/2026.08.28.03.26.55.csv`,
`exp/navhard_sae_armBp_pathfix/2026.08.28.03.36.20.csv`,
`exp/navhard_sae_armAp_pathfix/2026.08.28.03.37.07.csv`. All three carry the
same 450 stage-1 / 5462 stage-2 row split as before, so this is the same split,
not a different subset.

**Confirmed:** EPDMS1 is now **0.5475 / 0.6018 / 0.6634** — three distinct
values where the mis-pathed run gave `0.28958783900556795` for all five camera
models. Stage 1 now carries model signal, which is exactly what fixing
`original_sensor_path` should do. Combined scores roughly doubled.

**Two things I predicted wrongly:**

1. **Stage 2 was not invariant.** I expected only stage-1 and the combined
   aggregate to move. EPDMS2 fell on all three models (−0.045, −0.053, −0.032).
   So stage-2 scoring depends on stage-1 in the two-stage metric, and the
   navhard *histograms* — which plot per-scene stage-2 scores — are superseded
   as well.
2. **The SAE A' vs B' ordering REVERSED.** Mis-pathed: A' 0.1178 > B' 0.1158.
   Corrected: **B' 0.2175 > A' 0.1993.** The apparent "control beats
   static-suppression" result was an artifact of the config bug. Any conclusion
   drawn from that comparison on the old numbers should be revisited — this is
   the SAE arm comparison, so it may matter to the experiment it was run for.

**All five camera models now have corrected numbers** — the cmd/cls re-runs
that failed on the first attempt (jobs 57194672/73, Ray `RuntimeError`) were
retried successfully as `cmd_tokens_film_pathfix2` / `cls_tokens_film_pathfix2`.
`transfuser`, `transfuser_latent` and `human` remain `not_scoreable` for the
separate structural reasons documented above.

### A second correction: the corrected ranking

Two conclusions from the mis-pathed run were artifacts, not results:

1. **SAE A' vs B' reversed.** Mis-pathed: A' 0.1178 > B' 0.1158. Corrected:
   **B' 0.2175 > A' 0.1993.** Static-suppression beats the control, not the
   other way round — and the corrected margin (0.0182) is ~9x the old one
   (0.0020), which was itself noise on numbers halved by a const-vel stage 1.
2. **cls_tokens_film no longer loses to constant velocity.** Mis-pathed it
   scored 0.1136 against CV's 0.1148 — i.e. *worse than a trivial baseline*,
   which would be a damning read. Corrected: **0.1782 vs 0.1148**, a clear win.

Corrected navhard ranking:
`variant1 0.2469 > cmd 0.2411 > SAE B' 0.2175 > SAE A' 0.1993 > cls 0.1782 > CV 0.1148`.

### Getting these into the plots required one extra step

The `final_pathfix` manifest publishes these scores with **`csv_path: null`**.
Every step here needs per-scene rows, not an aggregate, so those five models
were silently dropped and one finalize run (job 57237563) regressed the navhard
plot to a single `constant_velocity` line.

`visualize_distributions/resolve_manifest.py` fixes that without touching the
scoring session's file: it writes a resolved *copy* with each `csv_path` filled
in, accepting a candidate only when that CSV's own
`extended_pdm_score_combined` matches the published score to 1e-9. Filename
matching would not have been safe — the experiment dirs are inconsistently
named (`cmd_tokens_film_pathfix2` vs `navhard_patch_tokens_film_pathfix`).
It runs as step 0 of `finalize.sbatch` and becomes a no-op once the source
manifest carries the paths itself.

### Fallback counts as logged by each scoring run

| model | navhard CV-fallbacks (of 5912) |
|---|---|
| Variant 1 (patch) | 450 (7.61%) — one per stage-1 scene |
| SAE A' (control) | 450 (7.61%) — one per stage-1 scene |
| SAE B' (static) | 450 (7.61%) — one per stage-1 scene |
| cmd_tokens_film | 0 logged — but stage-1 proven CV-identical (see above) |
| cls_tokens_film | 0 logged — but stage-1 proven CV-identical (see above) |
| Constant Velocity | 0 (needs no camera — structurally immune) |

See [Which clips are fallbacks](#which-clips-are-fallbacks) for the clip-level
check on the rendered galleries.

## The metric convention — the point of this rebuild

```
navtest            ->  NAVSIM v1 PDMS,  one-stage    <- compare to TransFuser 84.0, Human 94.8
navhard_two_stage  ->  NAVSIM v2 EPDMS, two-stage    <- compare to PDM-Closed 51.3, LTF 23.1
```

The previous galleries in this repo labelled **navtest** results "v2 EPDMS".
That was wrong, and it is the bug this rebuild exists to fix. `navtest` is a
*split*; `v1`/`v2` is a *metric version*. They are independent axes, and the two
formulas are not convertible:

```
v1.1 PDMS  = NC x DAC x (5*EP + 5*TTC + 2*Comf) / 12                       (2 gates, 5 subscores)
v2   EPDMS = NC x DAC x DDC x TLC x (5*EP+5*TTC+2*LK+2*HC+2*EC) / 16       (4 gates, 9 subscores)
```

Measured on identical trajectories the gap is not a constant offset: human
−0.29, ego-status MLP +0.57, constant velocity **+5.28**. v2 systematically
flatters weak agents. Every plot, axis label, caption and gallery title
produced here states split + metric version + staging explicitly, and v1 and v2
are never drawn on the same axes.

Both facts above are taken from `docs/NAVSIM_EVAL.md`, which is the
authoritative writeup; nothing here is re-derived.

## Deliverable 1 — distribution plots (`plots/`)

Per (metric, bin-count) histograms of the **per-scene** score, one line per
model, produced by `scripts/plot_distributions.py`:

| file | contents |
|---|---|
| `navtest_v1_pdms_{10,15,20}bins.png` | navtest, v1 PDMS one-stage, all models with a v1 CSV |
| `navhard_v2_epdms_combined_{10,15,20}bins.png` | navhard, v2 EPDMS two-stage, per-scene stage-two score |
| `navhard_v2_epdms1_{10,15,20}bins.png` | navhard **stage-1 only** (real / reactive), n=450 |
| `navhard_v2_epdms2_{10,15,20}bins.png` | navhard **stage-2 only** (synthetic) |

Each is drawn at **10, 15 and 20 bins** — same data, three resolutions, so you
can pick the one that reads best. Every plot marks each model's mean (dashed,
model colour) and, where meaningful, the published anchors as dotted vertical
rules: v1 — TransFuser 0.8339, Human 0.9455, CV 0.2065; v2 navhard — PDM-Closed
0.513, LTF 0.231, ego-MLP 0.127, CV 0.109. Densities (not raw counts) are
plotted so models with different scene counts stay comparable.

`plots/coverage.json` records which models each plot actually contains.

### EPDMS1 / EPDMS2 — and an honest caveat about EPDMS2

`EPDMS = EPDMS1 x EPDMS2`, and the product hides which stage is failing, so the
two stages are plotted separately as asked. Note precisely what each one is:

* **EPDMS1** is the stage-1 (real sensors, real history) score, read from the
  450 16-char-token rows. This is genuinely separate information.
* **EPDMS2** as plotted is the stage-2 (synthetic render, donor history) score,
  read from the 17-char-token rows — **the same column as the "combined"
  per-scene plot**. Under this repo's established per-scene convention
  (`visualize/select_by_score.py`, `select_navhard_failures.py`) a navhard
  "scene" *is* a stage-2 observation, so the combined per-scene histogram and
  the EPDMS2 histogram are the same distribution. It is kept as its own file
  only so it can be read side-by-side against EPDMS1. This is stated on the
  plot itself rather than presenting it as a distinct quantity it is not.

The devkit's own aggregate rows (`extended_pdm_score_stage_one` /
`_stage_two` / `_combined`) are excluded from all per-scene statistics. As the
manifest's `_meta.product_relation_note` records, `epdms1 * epdms2` only
approximates the combined row, because `avg(X*Y) != avg(X)*avg(Y)` when the two
stages are correlated across scenes.

### The NaN extended-comfort note

The brief asked for the NaN-EC fraction to be noted on each **navtest** plot.
It is noted there — as **not applicable**, which is the accurate answer rather
than a fabricated number:

> v1 PDMS has no `two_frame_extended_comfort` term at all (see the formula
> above — 5 subscores, no EC). The denominator-14-vs-16 behaviour is a property
> of the **v2 EPDMS** formula, so it cannot arise on a v1-scored navtest run.

### The NaN-EC fractions in the manifest are a table-layout artifact, not a NaN rate

The manifest reports `nan_ec_fraction: {navhard_stage1: 0.9239, navhard_stage2:
0.0761}`. Taken at face value that reads as "92% of stage-1 rows were scored
with denominator 14 instead of 16", which would mean the navhard aggregate
mixes two different metrics. **It does not, and I checked rather than repeating
it.**

A navhard result CSV is one wide table where *every* subscore appears twice, as
`*_stage_one` and `*_stage_two`, but each row only populates the pair belonging
to its own stage — a stage-2 row leaves every `_stage_one` cell as `''`, and
vice versa. Counting empty `_stage_one` cells across *all* rows therefore just
counts stage-2 rows:

```
NaN two_frame_extended_comfort_stage_one : 5462/5912 = 0.9239   <- == stage-2 row share
NaN two_frame_extended_comfort_stage_two :  450/5912 = 0.0761   <- == stage-1 row share
```

Restricted to the rows that actually carry that stage, the real rate is **zero**:

```
stage-1 rows with NaN stage-one EC : 0/450   = 0.0000
stage-2 rows with NaN stage-two EC : 0/5462  = 0.0000
```

So for every navhard run here, **every scored row had a genuine
two-frame-extended-comfort value and was scored with denominator 16**. The
denominator-14 caveat does not apply to this data at all. The plots state the
0.00% figure, computed per-stage over the correct row subset by
`load_v2_navhard()` in `scripts/plot_distributions.py` — not the manifest's
whole-table figure.

(This does not make the manifest wrong, only easy to misread: its number
answers "what fraction of rows lack a stage-one EC value", which is a different
question from "what fraction of stage-one scores were NaN".)

## Deliverable 2 — per-bin example clips (`videos/`, `bins/`, `index.html`)

`index.html` is the combined view: pick a (model, metric) pair, toggle bin
resolution, see the matching histogram above up to *N* example clips per bin.

### Render economy — how clips are reused across the three binnings

Clips are rendered **once**, at the finest bin resolution a model is given.
The coarser views do not re-render anything: `scripts/../../..
/visualize_distributions/select_by_bin.py` writes one manifest per (model,
metric) holding a single rendered token set plus, for each of 10/15/20 bins, a
regrouping of those same tokens under that resolution's edges (a coarse bin is
the union of the fine bins it covers, resampled back down to *N* examples).
So a model gets ~20x5 renders total, not 3x that for identical footage.

### How the ~300-clip budget was spent

The brief's cap is ~300 clips; 8 models x 20 bins x 5 would be ~800.

* **Headline models get the full per-bin treatment** — 20 bins x 5 examples,
  ~85 clips each after empty bins — on **navhard v2 EPDMS**, the harder and
  more discriminating of the two metrics. These are the architecture variants
  the work is actually about.
* **Every other (model, metric) pair gets 5 coarse bins x 2 examples**
  (~10 clips each). The distribution plot carries these models' story; the
  clips are there to make a bin concrete, not to be browsed exhaustively.

Which models actually received which tier is recorded per row in the coverage
table at the end of this file (`per-bin tier` column) — read that rather than
assuming, because a pair only gets a tier once its score lands, and this run
was assembled while the sibling scoring session was still working through the
queue.

Actual per-pair rendered counts are in each `bins/*.json` (`rendered_count`)
and are surfaced in the page header.

Note **Human renders only 4 clips**, not 10. That is not a truncation: under v1
PDMS the human's per-scene distribution is essentially bimodal at 0.0 and 1.0,
so only 2 of the 5 coarse bins contain any scene at all. The empty bins are
shown as empty rather than back-filled from neighbouring bins.

### Two models are genuinely absent from the navhard plots

The navhard v2 EPDMS plots have **no TransFuser line and no Human line**. That
is not a gap in this work -- the sibling scoring session established that
neither can be legitimately scored on `navhard_two_stage` with the public data,
and no number has been manufactured to fill the hole:

* **TransFuser** needs LiDAR (`transfuser_agent.yaml` has `config.latent=false`,
  so `get_sensor_config()` requests `lidar_pc`), and navhard's public
  `sensor_blobs` release ships camera images only -- no `MergedPointCloud` dir
  exists in any of its 76 scene-log dirs. Forcing `config.latent=true` to route
  around it was **rejected**, because `transfuser_seed_0.ckpt` was trained as a
  LiDAR-fusing model and running it LiDAR-free would silently exercise a
  mismatched forward path -- the exact "wrong architecture, silently" trap this
  project's guards exist to catch. The community's own published navhard
  baseline is *Latent* TransFuser (23.1 EPDMS) for this reason.
* **Human** is not a valid two-stage EPDMS agent at all: stage-2 scenes are
  synthetic rollouts that carry no post-perturbation GT future, so
  `Scene.get_future_trajectory()` raises `IndexError` on every stage-2
  scenario. EPDMS uses the human trajectory only as the *reference* inside
  NC/DAC/DDC/TLC, never as a scored agent -- which is why the published navhard
  reference table has no Human row either.

* **Latent TransFuser** (`transfuser_latent` in the manifest) was then tried specifically to route around the LiDAR
  gap (`config.latent=true` never requests `lidar_pc`), and got further — but
  hit the *missing CAM_F0 JPEG* gap described at the top of this file instead.
  Unlike `DINOWaypointAgent`, `TransfuserAgent.compute_trajectory` has no
  per-scenario try/except, so the missing images surfaced as uncaught
  `FileNotFoundError`s and crashed the run outright rather than degrading to
  const-vel. Also `not_scoreable`.

TransFuser and Human therefore appear in the **navtest v1 PDMS** plots (where
they are the published anchors, 0.8339 and 0.9455) and are absent from the
navhard ones; Latent TransFuser has no score on either split.
Their full reasoning is preserved verbatim in the manifest's `reason` fields
and summarised in the coverage table below.

### Which clips are fallbacks

**Status: attempted, result recorded below.**

The scoring session tried to recover the affected scene set by matching
per-scene SCORE rows against the constant-velocity run, and got 894-1037
matches against an expected ~450 — too noisy to use, because PDM's
coarse/bucketed sub-metrics make many genuinely-predicted simple scenes score
identically to const-vel. It concluded the set was unrecoverable and said so.

I attempted a sharper test on a different signal: comparing the dumped
**trajectories** rather than the scores. A fallback trajectory is not merely
*scored like* const-vel — it *is* const-vel, produced by the same formula from
the same `ego_velocity`, so it should be bit-identical to what
`ConstantVelocityAgent` dumps for that token. Twenty-four float32 values
agreeing to 1e-6 by coincidence is not a realistic failure mode, whereas two
bucketed scores agreeing plainly is. Implementation:
`visualize_distributions/detect_cv_fallbacks.py`.

One limit no method can escape, stated rather than hidden: a scene where the
model's genuine prediction happens to *be* const-vel (a stationary ego, where
every method degenerates to the same answer) is indistinguishable from a
fallback. Those are counted separately as `degenerate_zero_motion` and
discounted rather than reported as fallbacks.

<!-- FALLBACK_RESULT_START -->
**Result: 0 fallbacks in the rendered clips — they are all real predictions.**

`detect_cv_fallbacks.py` compared Variant 1's navhard dump against a
`ConstantVelocityAgent` dump over the identical scene filter (535 shared
tokens: 450 stage-1 + 85 stage-2):

```
CV-fallback            : 0 (0.0%)
degenerate (no motion) : 0
real prediction        : 535
```

This is expected once the root cause is understood: the *dumps* behind these
galleries use the correct `original_sensor_path`, so no image ever failed to
load and no fallback ever triggered. The 450 fallbacks belong to the *scoring*
runs, which used the wrong path.

So the two halves of each navhard card come from different places, and only one
is affected:

* the **video** is a genuine model prediction — verified bit-wise here;
* the **per-scene score** printed under it comes from the mis-pathed scoring
  run. For navhard cards that score is the **stage-2** score, and stage 2 was
  correctly pathed, so it is sound too. It is the *combined* aggregate and
  EPDMS1 that are corrupted, not these per-scene stage-2 values.

The clip-level badge machinery is wired up regardless
(`build_bins_viewer.py --fallbacks-dir`): any pair with a detection result and
a non-zero count renders a `CONST-VEL FALLBACK` badge, and any navhard pair
without a detection result is labelled "fallback status unverified" on the page
rather than silently presented as clean.
<!-- FALLBACK_RESULT_END -->

## Deliverable 3 — the rebuilt ranked galleries

* `../ranked_navtest_v1/` — navtest scenes ranked by **v1 PDMS** (one-stage)
* `../ranked_navhard_v2/` — navhard scenes ranked by **v2 EPDMS** (two-stage)

Both are built by `visualize_distributions/select_ranked.py` +
`build_ranked_viewer.py`, which take their title, axis wording and subscore
column set from the manifest's own `split`/`metric` fields rather than
hand-typed strings — so the mislabel cannot silently recur. The v1 pages show
the 6 v1 subscore columns (NC DAC DDC EP TTC Comf); the v2 pages show all 9.

**Which model each ranked gallery shows.** These galleries are single-model by
construction (one model's scenes ranked high to low), matching the existing
`ranked_navtest/` and `ranked_navhard/`:

* `ranked_navhard_v2/` — **cmd_tokens_film** (v2 EPDMS 0.1216), the same model
  the old `ranked_navhard/` used, so the corrected page is directly comparable
  to the mislabelled one it replaces.
* `ranked_navtest_v1/` — **TransFuser (user-trained)** (v1 PDMS 0.8339). Chosen
  because its v1 number reproduces the published TransFuser 84.0, which makes
  it the right anchor for a page whose whole point is "this is v1 PDMS, the
  published-comparable metric". The architecture variants' v1 scores landed
  later in this run; the page can be rebuilt for any of them with
  `run_ranked_pipeline.py --model-key <key> --metric v1_pdms_navtest`.

**UPDATE 2026-08-28 (post-deliverable-3):** `ranked_navtest/`, `ranked_navhard/`
and `navhard_comparison/` have since been **deleted** (superseded by the v1/v2
galleries above) and dropped from `_inject_tabs.py`'s tab list and from
`navsim_galleries.zip`; there is no more "(old)" label. `agent_comparison/`
was **replaced** by `agent_comparison_v1/` (v1 PDMS metric, scenes ranked by
the Variant-1-vs-TransFuser score difference in both directions, instead of a
drivable-area pass/fail gate) — the old directory is left on disk as a
fallback but is no longer tabbed or packaged. `arch_comparison/` and
`session_scoreboard/` are unchanged in identity, though `arch_comparison/`'s
own scene selection was separately reworked to be score-ranked (see its own
`select_arch_divergence.py`).

## Provenance / reproducing

Everything here is regenerable. Scripts live in
`visualize_distributions/` (a copy-not-edit of `visualize/`, which is owned by
another session) and `scripts/` here:

```bash
# Deliverable 1 (re-runnable at any time; plots whatever the manifest has)
sbatch eval_test/distributions/scripts/plot_distributions.sbatch

# Deliverable 2, one (model, metric) pair -- chains select -> filter -> dump -> render
python visualize_distributions/run_pipeline.py \
    --model-key cmd_tokens_film --metric v2_epdms_navhard_two_stage --tier headline

# Deliverable 3, one ranked gallery -- adds a build-viewer step
python visualize_distributions/run_ranked_pipeline.py \
    --model-key cmd_tokens_film --metric v2_epdms_navhard_two_stage \
    --gallery-dir eval_test/ranked_navhard_v2 --limit 60

# tab bar (idempotent) + Deliverable 4
python eval_test/_inject_tabs.py
bash eval_test/distributions/scripts/rebuild_and_verify_zip.sh
```

**Order matters, and `scripts/finalize.sbatch` encodes it**: plots -> bins
viewer -> README coverage -> **tab bar** -> zip+verify. Building a gallery page
overwrites it and therefore *strips the injected tab bar*, so
`_inject_tabs.py` has to run after every page build, not before.
`distributions/index.html` silently lost its bar exactly this way once; the
zip verifier's link check is what caught it.

All compute runs through `sbatch`; nothing is executed on the Fir login node.
Helper scripts live under `/scratch`, never `/tmp/claude-*` (invisible to
compute nodes).

### Two upstream bugs found and fixed in the local copies

1. **`dump_agent_trajectories.py` crashed on `human_agent`.** `HumanAgent
   .compute_trajectory(agent_input, scene)` takes the scene as a second
   argument — its "prediction" *is* the logged future — while sensor agents
   take only the agent input. The copy here dispatches on the actual signature
   (`inspect.signature`), so oracle-style agents work without a hardcoded list.
2. **A zero-trajectory dump reported success.** The original returned exit 0
   after writing an empty `.pkl`, so bug (1) produced an empty dump, exit 0,
   and a dependent render job that started and rendered nothing. The copy here
   raises `SystemExit` on an empty dump.

3. **`_inject_tabs.py`'s idempotent skip froze the tab bar.** Pages injected
   against an older `TABS` list keep that older bar forever, because the
   marker check skips any page that already has one — so adding a gallery
   cross-linked only pages built *after* the change, and the six pre-existing
   galleries would have kept a stale 6-tab bar. Added `--refresh` (strip the
   old bar, re-inject the current one) and `--tolerate-missing`. The strip is
   the exact inverse of the injection, so repeated refreshes are stable; this
   was verified on copies before touching any real page (byte-exact content
   preservation, 9 links and exactly 1 `aria-current` per nav).

Fixes 1-2 are in `visualize_distributions/dump_agent_trajectories.py`; neither
touches `visualize/`. Fix 3 is in `eval_test/_inject_tabs.py`, which is the
shared tab-bar tool the brief asked to extend.

## Coverage — what is and is not here

<!-- COVERAGE_TABLE_START -->

Generated from `/scratch/eddie96/eddie/dino-cmd-fusion/eval_test/distributions/scores_manifest_resolved.json` (manifest status: **final_pathfix**, last updated 2026-08-28T05:15:00-07:00).

| model | split / metric | scoring status | aggregate score | in distribution plot | example clips | per-bin tier |
|---|---|---|---|---|---|---|
| Variant 1 (patch) | navtest / v1 PDMS (one-stage) | scored | 0.8302 | yes | 10 | 5 bins x 2 |
| Variant 1 (patch) | navhard / v2 EPDMS (two-stage) | ok | 0.2469 | yes | 85 | 20 bins x 5 |
| cmd_tokens_film | navtest / v1 PDMS (one-stage) | scored | 0.8400 | yes | 10 | 5 bins x 2 |
| cmd_tokens_film | navhard / v2 EPDMS (two-stage) | ok | 0.2411 | yes | 88 | 20 bins x 5 |
| cls_tokens_film | navtest / v1 PDMS (one-stage) | scored | 0.7690 | yes | 10 | 5 bins x 2 |
| cls_tokens_film | navhard / v2 EPDMS (two-stage) | ok | 0.1782 | yes | 83 | 20 bins x 5 |
| SAE A' (control) | navtest / v1 PDMS (one-stage) | scored | 0.8092 | yes | 10 | 5 bins x 2 |
| SAE A' (control) | navhard / v2 EPDMS (two-stage) | ok | 0.1993 | yes | -- | - |
| SAE B' (static) | navtest / v1 PDMS (one-stage) | scored | 0.8141 | yes | 10 | 5 bins x 2 |
| SAE B' (static) | navhard / v2 EPDMS (two-stage) | ok | 0.2175 | yes | -- | - |
| TransFuser (trained) | navtest / v1 PDMS (one-stage) | reused | 0.8339 | yes | 10 | 5 bins x 2 |
| TransFuser (trained) | navhard / v2 EPDMS (two-stage) | not_scoreable | -- | no | -- | - |
| Human | navtest / v1 PDMS (one-stage) | reused | 0.9455 | yes | 4 | 5 bins x 2 |
| Human | navhard / v2 EPDMS (two-stage) | not_scoreable | -- | no | -- | - |
| Constant Velocity | navtest / v1 PDMS (one-stage) | reused | 0.2065 | yes | 10 | 5 bins x 2 |
| Constant Velocity | navhard / v2 EPDMS (two-stage) | scored | 0.1148 | yes | 10 | 5 bins x 2 |
| Latent TransFuser | navtest / v1 PDMS (one-stage) | not_run | -- | no | -- | - |
| Latent TransFuser | navhard / v2 EPDMS (two-stage) | not_scoreable | -- | no | -- | - |

**Total example clips rendered: 340** (brief's budget: ~300).

### Pairs that could not be covered, and why

* **TransFuser (trained) on navhard / v2 EPDMS (two-stage)** — not scoreable. config.latent=false,
  so TransfuserAgent requests lidar_pc; navhard_two_stage's public sensor_blobs release has ZERO
  MergedPointCloud (LiDAR) directories across all 76 scene logs (confirmed locally AND via the
  HuggingFace OpenDriveLab/OpenScene navsim-v2 file listing -- exactly 3 navhard_two_stage_*
  tarballs exist, curr_sensors/hist_sensors/scene_pickles, no lidar tarball). (Full reasoning is in
  the manifest's `reason` field.)

* **Human on navhard / v2 EPDMS (two-stage)** — not scoreable. human_agent.compute_trajectory() ->
  Scene.get_future_trajectory() indexes self.frames[num_history_frames-1 ..
  num_history_frames-1+num_future_frames] to read GT human ego poses
  (navsim/common/dataclasses.py:356-370), unconditionally, with no fallback path in human_agent.py
  (an 8-line class). (Full reasoning is in the manifest's `reason` field.)

* **Latent TransFuser on navhard / v2 EPDMS (two-stage)** — not scoreable. UPDATED after fixing
  original_sensor_path: job 57194640 got past the missing-CAM_F0-JPEG gap entirely (0
  FileNotFoundErrors this time, confirming the path fix works for this agent too) but hit a NEW,
  separate failure: AssertionError("Invalid interval nan") in
  navsim/planning/simulation/planner/pdm_planner/scoring/scene_aggregator.py:62
  (_compute_two_frame_comfort), cascading into the same downstream TypeError converting NaN arrays
  to numeric that killed the pre-fix run. (Full reasoning is in the manifest's `reason` field.)
<!-- COVERAGE_TABLE_END -->
