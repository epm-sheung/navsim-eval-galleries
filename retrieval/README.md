# Scene retrieval — stock vs fine-tuned DINOv2

Query = the **t0 camera frame (last frame of the past)** of a navtest scene.
Corpus = the t0 frame of all 12,146 navtest scenes. Descriptor = DINOv2 CLS token,
L2-normalised, cosine similarity, top-10.

Two trunks, identical in every other respect:

| | weights |
|---|---|
| stock | `torch.hub` `dinov2_vits14` |
| fine-tuned | trunk inside `dino-driving-clean/runs/waypoint_navsim_ft/20260720_065509/checkpoints/epoch013-best.ckpt` (30 of 175 tensors differ: blocks 10–11 + final norm) |

Both see the same tensor: images are stored at 504×280, the model's input size, so the
transform is ToTensor + ImageNet normalise only — the same one used at eval time.

Pipeline (all on compute nodes, `/scratch/eddie96/eddie/navsim_retrieval/scripts/`):

1. `build_meta.py` — per-scene speed / driving command / PDMS sidecar. Each model's
   mean over 12,146 rows reconciles to `scores_manifest.json` exactly.
2. `embed.py` (GPU, ~4 min) — both trunks over all 12,146 t0 frames in one pass.
3. `retrieve.py` (CPU) — query selection, top-10, statistics, thumbnails.
4. `build_page.py` (here) — writes `index.html` with the payload inlined.

Queries are picked from **metadata only** (3 per driving-command × speed-tercile cell,
plus the 3 lowest-PDMS scenes), so neither embedding influenced the selection.
