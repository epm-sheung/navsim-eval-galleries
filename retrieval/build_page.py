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
TABS = [("Retrieval", "index.html"), ("Rank disagreement", "rank.html"),
        ("Green criterion", "criterion.html"), ("Figures", "../figures/index.html")]
DEFAULT_ON = ["ours_cls", "drivor_cls", "jepa_bb"]
METHOD_NOTE = {
    "Our method": "__OURS_NOTE__",
    "DrivoR": "DrivoR trains LoRA r32 on DINOv2-S/14-reg4; its base weights are bit-identical to "
              "timm&rsquo;s release, so &#9312; is exactly the pretrained backbone. &#9313; runs our "
              "fine-tuned DINO through DrivoR&rsquo;s own preprocessing. Our DINO has no register "
              "tokens, so the stock-DINOv2 reference row separates that architecture difference "
              "from the effect of our fine-tune.",
    "Drive-JEPA": "&#9312; is Drive-JEPA&rsquo;s released V-JEPA pretraining (vitl_merge_3dataset_e50.pt). "
                  "&#9313; is our fine-tuned DINO on the same two frames with the same crop, at "
                  "504&times;252 (DINOv2 needs multiples of 14) and with ImageNet normalisation, which "
                  "DINOv2 was trained with and V-JEPA was not.",
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
    mains = [r for r in rows if r.get("role", "main") == "main"]
    best = min(r["ade"] for r in mains)
    trs, divided = [], False
    for i, r in enumerate(rows):
        ref = r.get("role", "main") == "ref"
        if ref and not divided:
            trs.append('<tr class="divider"><td colspan="7">reference rows &mdash; to read the three above</td></tr>')
            divided = True
        if i == 0:
            d = '<td class="num ref">baseline</td><td class="num ref">&mdash;</td>'
        else:
            dv, ci = r["d_ade"], r["d_ade_ci"]
            sig = "sig-better" if ci[1] < 0 else ("sig-worse" if ci[0] > 0 else "ns")
            d = (f'<td class="num {sig}"><b>{dv:+.2f}</b> m {fmt_ci(ci)}</td>'
                 f'<td class="num">{r["win_rate"]*100:.0f}%</td>')
        cls = "refrow" if ref else ("best" if abs(r["ade"] - best) < 1e-9 else "")
        trs.append(f'<tr class="{cls}"><td class="vn">{esc(r["label"])}</td>'
                   f'<td class="num"><b>{r["ade"]:.2f}</b> m {fmt_ci(r["ade_ci"])}</td>{d}'
                   f'<td class="num">{r["speed"]:.2f}</td><td class="num">{r["green"]:.2f}</td>'
                   f'<td class="num">{r["pdms_gap"]:.3f}</td></tr>')
    return (f'<div class="pipe" id="p-{P["id"]}"><div class="ptitle">{esc(P["what"])}</div>'
            f'<div class="pfixed">held fixed: {esc(P["fixed"])}</div>'
            '<table><thead><tr><th>backbone</th><th class="num">trajectory ADE [95% CI]</th>'
            '<th class="num">&Delta; ADE vs &#9312; [95% CI]</th><th class="num">wins vs &#9312;</th>'
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

    ov = json.load(open(S / "arm4_planner_val.json")); ge = json.load(open(S / "arm4_gate_energy.json"))
    METHOD_NOTE["Our method"] = (
        "Four matched training runs in Mehdi&rsquo;s trainer and architecture (CLS + 4&times;6 pooled "
        "patch tokens), identical except trunk and SAE: &#9312; stock, &#9313; our fine-tuned DINO, "
        "&#9314; stock + his updated learned-gate SAE on block 11, &#9315; fine-tuned + the same SAE "
        "(trajectory teacher, keep budget 0.5, hard gate at half the run, 8 epochs). The trunk stays "
        "frozen; the gate is what trains. Planner validation ADE: "
        f"&#9312; {ov['stock']:.3f} &middot; &#9313; {ov['ft']:.3f} &middot; &#9314; {ov['stock_sae']:.3f} "
        f"&middot; &#9315; {ov['ft_sae']:.3f} m &mdash; the SAE costs the stock trunk "
        f"{ov['stock_sae']-ov['stock']:+.3f} but the fine-tuned trunk only {ov['ft_sae']-ov['ft']:+.3f}. "
        f"Unlike DrivoR&rsquo;s gate, these gates close live codes: {ge['stock_sae']['dropped']} and "
        f"{ge['ft_sae']['dropped']} of 3,072, carrying {ge['stock_sae']['dropped_mass_share']*100:.0f}% and "
        f"{ge['ft_sae']['dropped_mass_share']*100:.0f}% of code magnitude, with only "
        f"{ge['stock_sae']['top100_by_mass_kept']} and {ge['ft_sae']['top100_by_mass_kept']} of the 100 "
        "strongest codes kept &mdash; in 8 epochs the budget forced the cut before the teacher could "
        "choose it. The fine-tuned dictionary also reconstructs worse (FVU 0.150 vs 0.098).")
    methods, readouts = [], []
    for m in ("Our method", "DrivoR", "Drive-JEPA"):
        ps = [P for P in U["pipelines"] if P["method"] == m and P.get("main", True)]
        methods.append(f'<div class="method"><h3>{esc(m)}</h3><p class="note measure">{METHOD_NOTE[m]}</p>'
                       + "".join(pipeline_table(P) for P in ps) + "</div>")
        for P in U["pipelines"]:
            if P["method"] == m and not P.get("main", True):
                readouts.append(f'<div class="method"><h3>{esc(m)}</h3>{pipeline_table(P)}</div>')
    # ---- green tiles: how many of the top 10 drive within 2 m of the query ----------
    gtr = []
    for P in U["pipelines"]:
        if not P["rows"] or "green2" not in P["rows"][0]:
            continue
        gtr.append(f'<tr class="grp"><td colspan="3">{esc(P["method"])} &middot; {esc(P["what"])}</td></tr>')
        best = max(r["green2"] for r in P["rows"] if r.get("role", "main") == "main")
        for r in P["rows"]:
            cls = "refrow" if r.get("role") == "ref" else ("best" if abs(r["green2"] - best) < 1e-9 else "")
            ci = r.get("green2_ci", [float("nan")] * 2)
            gtr.append(f'<tr class="{cls}"><td class="vn">{esc(r["label"])}</td>'
                       f'<td class="num"><b>{r["green2"]:.2f}</b> / 10 {fmt_ci(ci)}</td>'
                       f'<td class="num">{r["any2"]*100:.0f}%</td></tr>')
    gtr.append('<tr class="grp"><td colspan="3">Reference &mdash; no backbone pair</td></tr>')
    for r in U["reference"]:
        if "green2" in r:
            gtr.append(f'<tr class="refrow"><td class="vn">{esc(r["label"])}</td>'
                       f'<td class="num"><b>{r["green2"]:.2f}</b> / 10 {fmt_ci(r["green2_ci"])}</td>'
                       f'<td class="num">{r["any2"]*100:.0f}%</td></tr>')
    if U.get("chance_green2") is not None:
        gtr.append(f'<tr class="chance"><td class="vn">chance &mdash; ten random scenes from other logs</td>'
                   f'<td class="num"><b>{U["chance_green2"]:.2f}</b> / 10</td>'
                   f'<td class="num">{U["chance_any2"]*100:.0f}%</td></tr>')
    green_html = "".join(gtr)

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
                                        | {"rows": [{k: r.get(k, "main") if k == "role" else r[k] for k in ("key", "label", "ade", "role")} for r in P["rows"]]}
                                        for P in U["pipelines"] if P["rows"]],
                          "queries": U["queries"], "scenes": U["scenes"], "default_on": DEFAULT_ON},
                         separators=(",", ":")).replace("</", "<\\/")
    page = (open(Path(__file__).with_name("page_template.html"), encoding="utf-8").read()
            .replace("__TABBAR__", tabbar).replace("__NQ__", f'{U["n_queries_bench"]:,}')
            .replace("__NC__", f'{U["n_corpus"]:,}').replace("__METHODS__", "\n".join(methods)).replace("__READOUTS__", "\n".join(readouts))
            .replace("__REF__", ref).replace("__GREEN__", green_html).replace("__INVENTORY__", inv)
            .replace("__GEN__", esc(U["generated_utc"])).replace("__PAYLOAD__", payload))
    left = sorted(set(__import__("re").findall(r"__[A-Z]+__", page)))
    if left:
        raise SystemExit(f"unfilled placeholders: {left}")
    (DST / "index.html").write_text(page, encoding="utf-8")
    print(f"[page] wrote {DST/'index.html'} ({len(page)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
