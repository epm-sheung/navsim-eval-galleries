# NAVSIM evaluation galleries

- **Retrieval** — query a navtest CAM_F0 frame, retrieve the top-10 most similar scenes (own log excluded), and
  grade neighbours by how close their ground-truth 4 s future is to the query's. Same-method, different-backbone
  pairs (original backbone, our fine-tuned DINO, SAE, fine-tuned DINO + SAE).
- **Rank disagreement** — all 12,146 navtest queries ranked by (SAE green count − original-backbone green count),
  50 evenly spaced samples per method.
- **Green criterion** — which distance (ADE, FDE, speed latent, full training loss) and which threshold should
  define a correct neighbour.
- **Figures** — scene clips with trajectories and per-gate scores, plus analysis figures.

The Findings, Why peaks, Scoreboard, Scenes and Distributions pages were removed on 2026-10-02 to stay within the
GitHub Pages size limit; they remain in the git history.
