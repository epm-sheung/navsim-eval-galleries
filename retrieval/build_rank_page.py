# -*- coding: utf-8 -*-
"""Build navsim_pages/retrieval/rank.html -- every navtest scene as a query,
ranked by how much the SAE changes retrieval vs. the original backbone.

Payload: sae_retrieval/out/rank_payload.json (written by sae_retrieval/rank_disagree.py).
Template: rank_template.html, __TOKEN__ placeholders (not an f-string).

IMPORTANT: this page uses its OWN thumbnail directory (retrieval/rank_thumbs/),
never retrieval/thumbs/ -- build_page.py prunes thumbs/ to only what its own
page references, so sharing a directory would make the two builders fight
over which files may be deleted.
"""
import json, re, shutil
from pathlib import Path

S = Path("/scratch/eddie96/eddie/sae_retrieval/out")
THUMB_SRC = Path("/scratch/eddie96/eddie/navsim_retrieval/out/thumbs")
DST = Path("/scratch/eddie96/eddie/navsim_pages/retrieval")

TABS = [("Findings", "../index.html"), ("Why peaks", "../why_peaks.html"),
        ("Scoreboard", "../session_scoreboard/index.html"), ("Scenes", "../scenes/index.html"),
        ("Distributions", "../distributions/index.html"), ("Figures", "../figures/index.html"),
        ("Retrieval", "index.html"), ("Rank disagreement", "rank.html")]


def main():
    U = json.load(open(S / "rank_payload.json"))

    need = set(U["scenes"].keys())
    th = DST / "rank_thumbs"; th.mkdir(parents=True, exist_ok=True)
    cp = rm = 0
    for t in sorted(need):
        src = THUMB_SRC / f"{t}.jpg"
        if not src.is_file():
            raise SystemExit(f"missing thumbnail {t}")
        dst = th / f"{t}.jpg"
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst); cp += 1
    for f in th.glob("*.jpg"):
        if f.stem not in need:
            f.unlink(); rm += 1
    print(f"[thumbs] {len(need)} referenced, {cp} copied, {rm} removed (rank_thumbs/ only)")

    tabbar = ('<nav id="navsim-tabbar" aria-label="Galleries"><span class="nt-home">NAVSIM eval</span>'
              + "".join(f'<a class="nt" href="{h}"' + (' aria-current="page"' if h == "rank.html" else "")
                        + f'>{l}</a>' for l, h in TABS) + "</nav>")

    payload = json.dumps({"methods": U["methods"], "scenes": U["scenes"]},
                         separators=(",", ":")).replace("</", "<\\/")

    tmpl = open(Path(__file__).with_name("rank_template.html"), encoding="utf-8").read()
    page = (tmpl.replace("__TABBAR__", tabbar)
            .replace("__NC__", f'{U["n_corpus"]:,}')
            .replace("__TOPK__", str(U["topk"]))
            .replace("__GREEN_M__", str(U["green_m"]))
            .replace("__NSAMPLE__", str(U["n_sample"]))
            .replace("__GEN__", U["generated_utc"])
            .replace("__PAYLOAD__", payload))

    left = sorted(set(re.findall(r"__[A-Z_]+__", page)))
    if left:
        raise SystemExit(f"unfilled placeholders: {left}")

    (DST / "rank.html").write_text(page, encoding="utf-8")
    print(f"[page] wrote {DST / 'rank.html'} ({len(page) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
