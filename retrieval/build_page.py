# -*- coding: utf-8 -*-
"""Build navsim_pages/retrieval/index.html -- v3, same method / different backbone.

Each PIPELINE (sae_retrieval/pairs_spec.py) holds frames, resolution, preprocessing,
layer and pooling fixed and varies only the backbone weights, so rows inside one
pipeline table are directly comparable. Payload: sae_retrieval/out/pairs_payload.json.
Template: page_template.html, __TOKEN__ placeholders (not an f-string).
"""
import html, json, shutil
from pathlib import Path

S = Path("/scratch/eddie96/eddie/sae_retrieval/out")
THUMB_SRC = Path("/scratch/eddie96/eddie/navsim_retrieval/out/thumbs")
DST = Path("/scratch/eddie96/eddie/navsim_pages/retrieval")
TABS = [("Findings", "../index.html"), ("Why peaks", "../why_peaks.html"),
        ("Scoreboard", "../session_scoreboard/index.html"), ("Scenes", "../scenes/index.html"),
        ("Distributions", "../distributions/index.html"), ("Figures", "../figures/index.html"),
        ("Retrieval", "index.html")]
DEFAULT_ON = ["ours_readout", "drivor_cls", "jepa_bb"]
METHOD_NOTE = {
    "Our method": "Frozen DINOv2 trunk + trained aggregator. The trunk pair is the stock trunk vs "
                  "the PAV-fine-tuned one; the readout pair is the controlled trunk 2&times;2 "
                  "(cells C and D), where only the trunk differs.",
    "DrivoR": "LoRA r32 on DINOv2-S/14-reg4. DrivoR trains LoRA only: the base weights are "
              "bit-identical to timm&rsquo;s release (pos_embed is timm&rsquo;s own resample to "
              "1148&times;672), so &ldquo;original&rdquo; is exactly the pretrained backbone.",
    "Drive-JEPA": "V-JEPA ViT-L pretrained on driving video, then trained with the planner. "
                  "&ldquo;Original&rdquo; is the released pretraining checkpoint "
                  "(vitl_merge_3dataset_e50.pt).",
}
INVENTORY = [
    ("Worth comparing", [
        ("Backbone, within one pipeline", "original vs method-trained vs +SAE, everything else fixed",
         "yes, headline", "the only rows that are directly comparable"),
        ("Backbone-alone vs planner readout", "same backbone, two layers of the same model",
         "yes", "shows whether training changes the backbone or only what sits on it"),
        ("With vs without the SAE gate", "DrivoR and Drive-JEPA", "yes", "what a gate removes"),
    ]),
    ("Metrics", [
        ("Trajectory ADE", "query's 4 s future vs each neighbour's", "yes, headline",
         "separates every encoder; paired difference + 95% CI over the same 2,000 queries"),
        ("Win rate", "share of queries where this backbone's ADE is lower than the original's",
         "yes", "paired, so it ignores scene difficulty"),
        ("Speed error", "|speed difference| at t0", "yes", "tracks ADE, coarser"),
        ("Direction", "driving command matches", "weak", "saturates near 8-9 of 10"),
        ("Score gap", "|PDMS difference| to neighbours", "weak", "0.19-0.21 for all vs 0.24 chance"),
        ("Mean cosine", "similarity of the retrieved ten", "no", "each space has its own scale"),
    ]),
    ("Not directly comparable", [
        ("Rows across pipelines", "e.g. DrivoR CLS vs Drive-JEPA token mean", "no",
         "different frames, resolution, layer and pooling -- listed only as orientation"),
        ("Our shipped model's readout", "no matched backbone pair exists for it", "reference",
         "kept below the pairs, labelled as such"),
    ]),
    ("Available, not yet run", [
        ("navhard frames", "where both SAE papers report their gains", "yes, next", "navtest only here"),
        ("Neighbour gate failures", "does a neighbour fail the same PDMS gate", "yes", "sub-scores exist"),
    ]),
]


def esc(s):
    return html.escape(str(s), quote=True)


def fmt_ci(ci):
    return f'<span class="ci">[{ci[0]:.2f}, {ci[1]:.2f}]</span>'


def pipeline_table(P):
    rows = P["rows"]
    if not rows:
        return ""
    best = min(r["ade"] for r in rows)
    trs = []
    for i, r in enumerate(rows):
        if i == 0:
            d = '<td class="num ref">reference</td><td class="num ref">&mdash;</td>'
        else:
            dv, ci = r["d_ade"], r["d_ade_ci"]
            sig = "sig-better" if ci[1] < 0 else ("sig-worse" if ci[0] > 0 else "ns")
            d = (f'<td class="num {sig}"><b>{dv:+.2f}</b> m {fmt_ci(ci)}</td>'
                 f'<td class="num">{r["win_rate"]*100:.0f}%</td>')
        cls = "best" if abs(r["ade"] - best) < 1e-9 else ""
        trs.append(f'<tr class="{cls}"><td class="vn">{esc(r["label"])}</td>'
                   f'<td class="num"><b>{r["ade"]:.2f}</b> m {fmt_ci(r["ade_ci"])}</td>{d}'
                   f'<td class="num">{r["speed"]:.2f}</td><td class="num">{r["green"]:.2f}</td>'
                   f'<td class="num">{r["pdms_gap"]:.3f}</td></tr>')
    return (f'<div class="pipe" id="p-{P["id"]}"><div class="ptitle">{esc(P["what"])}</div>'
            f'<div class="pfixed">held fixed: {esc(P["fixed"])}</div>'
            '<table><thead><tr><th>backbone</th><th class="num">trajectory ADE [95% CI]</th>'
            '<th class="num">&Delta; ADE vs first row [95% CI]</th><th class="num">wins vs first row</th>'
            '<th class="num">speed err</th><th class="num">direction /10</th><th class="num">score gap</th>'
            f'</tr></thead><tbody>{"".join(trs)}</tbody></table></div>')


def main():
    U = json.load(open(S / "pairs_payload.json"))
    need = {q["token"] for q in U["queries"]}
    for q in U["queries"]:
        for l in q["nb"].values():
            need.update(n["t"] for n in l)
    th = DST / "thumbs"; th.mkdir(parents=True, exist_ok=True)
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
    print(f"[thumbs] {len(need)} referenced, {cp} copied, {rm} removed")

    methods = []
    for m in ("Our method", "DrivoR", "Drive-JEPA"):
        ps = [P for P in U["pipelines"] if P["method"] == m]
        methods.append(f'<div class="method"><h3>{esc(m)}</h3><p class="note measure">{METHOD_NOTE[m]}</p>'
                       + "".join(pipeline_table(P) for P in ps) + "</div>")
    ref = "".join(f'<tr><td class="vn">{esc(r["label"])}</td><td class="num"><b>{r["ade"]:.2f}</b> m</td>'
                  f'<td class="num">{r["speed"]:.2f}</td><td class="num">{r["green"]:.2f}</td>'
                  f'<td class="num">{(r.get("pdms_gap") or 0):.3f}</td></tr>' for r in U["reference"])
    inv = "".join(
        f'<h3>{esc(t)}</h3><table class="inv"><tbody>' +
        "".join(f'<tr><td><b>{esc(a)}</b><div class="sub">{esc(b)}</div></td>'
                f'<td><span class="w w-{esc(c.split(",")[0].split(" ")[0])}">{esc(c)}</span></td>'
                f'<td class="why">{esc(d)}</td></tr>' for a, b, c, d in items) + "</tbody></table>"
        for t, items in INVENTORY)
    tabbar = ('<nav id="navsim-tabbar" aria-label="Galleries"><span class="nt-home">NAVSIM eval</span>'
              + "".join(f'<a class="nt" href="{h}"' + (' aria-current="page"' if h == "index.html" else "")
                        + f'>{l}</a>' for l, h in TABS) + "</nav>")
    payload = json.dumps({"pipelines": [{k: P[k] for k in ("id", "method", "what", "fixed")}
                                        | {"rows": [{k: r[k] for k in ("key", "label", "ade")} for r in P["rows"]]}
                                        for P in U["pipelines"] if P["rows"]],
                          "queries": U["queries"], "scenes": U["scenes"], "default_on": DEFAULT_ON},
                         separators=(",", ":")).replace("</", "<\\/")
    page = (open(Path(__file__).with_name("page_template.html"), encoding="utf-8").read()
            .replace("__TABBAR__", tabbar).replace("__NQ__", f'{U["n_queries_bench"]:,}')
            .replace("__NC__", f'{U["n_corpus"]:,}').replace("__METHODS__", "\n".join(methods))
            .replace("__REF__", ref).replace("__INVENTORY__", inv)
            .replace("__GEN__", esc(U["generated_utc"])).replace("__PAYLOAD__", payload))
    left = sorted(set(__import__("re").findall(r"__[A-Z]+__", page)))
    if left:
        raise SystemExit(f"unfilled placeholders: {left}")
    (DST / "index.html").write_text(page, encoding="utf-8")
    print(f"[page] wrote {DST/'index.html'} ({len(page)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
