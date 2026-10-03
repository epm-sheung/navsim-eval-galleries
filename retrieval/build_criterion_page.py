"""Build retrieval/criterion.html from sae_retrieval/out/threshold_sweep/sweep.json.

Shows which distance + threshold should define a "green" (correct) neighbour:
matched-chance comparison of ADE / FDE / speed latent / full loss, plus the raw
ADE-in-metres and latent sweeps. Copies curves.png next to the page.
"""
import json, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SW = Path("/scratch/eddie96/eddie/sae_retrieval/out/threshold_sweep")
TABS = [("Retrieval", "index.html"), ("Rank disagreement", "rank.html"),
        ("Green criterion", "criterion.html"), ("Figures", "../figures/index.html")]
NAMES = {"ade": "ADE (m)", "fde": "FDE (m)", "latent": "Speed latent (L1)", "fullloss": "Full training loss"}
REC = ("latent", "10")       # our pick: simplest top performer, chance rate close to today's ADE<=2 m


def tabbar(cur):
    a = "".join(f'<a class="nt" href="{h}"' + (' aria-current="page"' if h == cur else "") + f">{l}</a>"
                for l, h in TABS)
    return f'<nav id="navsim-tabbar" aria-label="Galleries"><span class="nt-home">NAVSIM eval</span>{a}</nav>'


def f(x, d=2):
    return f"{x:.{d}f}"


def main():
    s = json.load(open(SW / "sweep.json")); C = s["criteria"]
    pcts = ["5", "10", "15", "20"]

    # matched-chance table: one row per criterion x chance rate
    rows = []
    for c in ["ade", "fde", "latent", "fullloss"]:
        for p in pcts:
            m = C[c]["matched_chance"][p]; d = m["discriminative"]
            best = (c, p) == REC
            rows.append(
                f'<tr class="{"rec" if best else ""}"><td>{NAMES[c]}</td><td>{p}%</td><td>{f(m["threshold"])}</td>'
                f'<td class="num"><b>{f(d["median_abs_z"], 1)}</b></td><td class="num">{d["n_sig"]}/{d["n_pairs"]}</td>'
                f'<td class="num">{f(m["fidelity"]["tau_same_criterion"], 3)}</td>'
                f'<td class="num">{f(m["validity"]["auc_retrieved"], 3)}</td>'
                f'<td class="num">{f(m["best_mean_green"])} / {f(m["worst_mean_green"])}</td></tr>')
    matched = "\n".join(rows)

    def raw(c, unit):
        out = []
        for k, m in C[c]["raw_grid"].items():
            d = m["discriminative"]; cur = (c == "ade" and float(k) == 2.0)
            out.append(f'<tr class="{"cur" if cur else ""}"><td>{f(float(k))}{unit}{" (current)" if cur else ""}</td>'
                       f'<td class="num">{100 * m["chance_rate_actual"]:.1f}%</td>'
                       f'<td class="num"><b>{f(d["median_abs_z"], 1)}</b></td><td class="num">{d["n_sig"]}/{d["n_pairs"]}</td>'
                       f'<td class="num">{f(m["fidelity"]["tau_same_criterion"], 3)}</td>'
                       f'<td class="num">{f(m["best_mean_green"])} / {f(m["worst_mean_green"])}</td></tr>')
        return "\n".join(out)

    head = []
    for p, v in s["latent_vs_ade_matched_chance"].items():
        head.append(f'<tr><td>{p}%</td><td class="num">{f(v["ade_median_abs_z"], 1)}</td>'
                    f'<td class="num"><b>{f(v["latent_median_abs_z"], 1)}</b></td>'
                    f'<td class="num">{v["latent_minus_ade_z"]:+.2f}</td>'
                    f'<td class="num">{f(v["ade_precision_retrieved"], 3)}</td><td class="num">{f(v["latent_precision_retrieved"], 3)}</td></tr>')

    rc = C[REC[0]]["matched_chance"][REC[1]]; ad = C["ade"]["raw_grid"]["2"]; sn = s["sanity"]
    html = (HERE / "criterion_template.html").read_text()
    fill = {
        "__TABBAR__": tabbar("criterion.html"),
        "__NQ__": f'{s["n_queries"]:,}', "__NC__": f'{s["n_corpus"]:,}',
        "__REC_THR__": f(rc["threshold"]), "__REC_Z__": f(rc["discriminative"]["median_abs_z"], 1),
        "__ADE_Z__": f(ad["discriminative"]["median_abs_z"], 1),
        "__ADE_CH__": f'{100 * ad["chance_rate_actual"]:.1f}',
        "__MATCHED__": matched, "__RAW_ADE__": raw("ade", " m"), "__RAW_LAT__": raw("latent", ""),
        "__HEAD__": "\n".join(head),
        "__SAN__": f'{sn["recon_ade_checkpoint_convention"]:.3f} vs {sn["ckpt_filename_ade"]:.3f}',
        "__HSCALE__": f(s["global_huber_scale"], 3),
    }
    for k, v in fill.items():
        html = html.replace(k, v)
    left = [t for t in fill if t in html]
    assert not left, f"unfilled placeholders: {left}"
    import re
    assert not re.search(r"__[A-Z_]+__", html), "unknown placeholder left in template"
    (HERE / "criterion.html").write_text(html)
    shutil.copy(SW / "curves.png", HERE / "criterion_curves.png")
    print(f"[page] wrote {HERE / 'criterion.html'} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
