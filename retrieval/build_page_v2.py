# -*- coding: utf-8 -*-
"""Build navsim_pages/retrieval/index.html -- ONE page, ONE ranked scoreboard, ONE gallery.

v2 (2026-09-27) replaces the earlier layout, which showed the same 30 queries twice
(once for the DINOv2 rows, once for the SAE rows) plus three overlapping stats
tables. Everything now comes from a single payload, sae_retrieval/out/unified.json:

  * scoreboard  every descriptor over 2,000 queries, identical results merged into
                one row, ranked by trajectory ADE (the metric that separates them)
  * gallery     the 30 display queries, each with a top-10 per descriptor; a picker
                chooses which descriptors are drawn, rows follow the scoreboard rank,
                and every tile carries its 4 s future so trajectories can be compared

The template is a plain string with __TOKEN__ placeholders, NOT an f-string, so the
page's CSS/JS braces never need escaping.
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
DEFAULT_ON = ["stock_cls", "ours_visual", "ours_repr", "drivor_codes_kept", "jepa_gated"]

# what is worth comparing, and what is not -- rendered as its own section
INVENTORY = [
    ("On this page", [
        ("Encoder family", "stock DINOv2, fine-tuned trunk, our model, DrivoR, Drive-JEPA",
         "yes", "the main axis; ADE separates them cleanly"),
        ("Model representation vs trunk", "our model's readout vs the frozen trunk it sits on",
         "yes", "this is what explains why the trunk alone looked no better than stock"),
        ("Image vs non-image inputs", "readout with / without motion + command, and no-image controls",
         "yes", "the controls show how much of a score is handed in rather than seen"),
        ("Before vs after an SAE gate", "DrivoR and Drive-JEPA, same image",
         "yes", "the direct measure of what a gate removes"),
        ("Compressed vs uncompressed codes", "kept codes vs all codes",
         "yes", "tests whether compression costs retrieval"),
        ("CLS vs patch mean", "same trunk, two poolings",
         "marginal", "within 0.1 on direction and 0.4 m on ADE for every trunk"),
    ]),
    ("Metrics", [
        ("Trajectory ADE", "query's 4 s future vs each neighbour's, own ego frames",
         "yes, headline", "the only metric that separates all encoders"),
        ("Speed error", "|speed difference| at t0", "yes", "tracks ADE, coarser"),
        ("Same direction", "driving command matches", "weak",
         "saturates near 8-9 of 10, and is trivially 10/10 for anything fed the command"),
        ("Score gap", "|PDMS difference| to neighbours", "weak",
         "every encoder sits at 0.19-0.21 against 0.24 by chance: none groups scenes by difficulty"),
        ("Mean cosine", "similarity of the retrieved ten", "no",
         "each descriptor lives in its own space; values cannot be compared across rows"),
    ]),
    ("Available, not yet run", [
        ("navhard frames", "the split where both SAE papers report their gains", "yes, next",
         "the gate diagnostics here are navtest-only; the dropped codes may activate there"),
        ("Neighbour gate failures", "does a neighbour fail the same PDMS gate", "yes",
         "per-scene sub-scores exist for 8 methods"),
        ("Map / agent context", "drivable-area margin, agent count", "maybe",
         "needs the metric cache; would test scene-structure similarity directly"),
        ("Same-log neighbours", "raw top-10 without the log filter", "no",
         "they are the same drive seconds apart, median 1.5 s from the query"),
    ]),
]


def esc(s):
    return html.escape(str(s), quote=True)


def main():
    U = json.load(open(S / "unified.json"))
    need = {q["token"] for q in U["queries"]}
    for q in U["queries"]:
        for lst in q["nb"].values():
            need.update(n["t"] for n in lst)
    thumbs = DST / "thumbs"; thumbs.mkdir(parents=True, exist_ok=True)
    copied = 0
    for t in sorted(need):
        src = THUMB_SRC / f"{t}.jpg"
        if not src.is_file():
            raise SystemExit(f"missing thumbnail {t}")
        dst = thumbs / f"{t}.jpg"
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst); copied += 1
    removed = 0
    for f in thumbs.glob("*.jpg"):
        if f.stem not in need:
            f.unlink(); removed += 1
    print(f"[thumbs] {len(need)} referenced, {copied} copied, {removed} removed")

    rows, ch = U["rows"], U["chance"]
    best_ade = min(r["ade"] for r in rows)
    worst = ch["ade"]
    grp_cls = {"image only": "g-img", "image + motion + command": "g-full",
               "no image (control)": "g-ctrl"}
    body = []
    for r in rows:
        w = max(2, min(100, (worst - r["ade"]) / (worst - best_ade) * 100))
        merged = (f'<div class="merged">identical to: {esc(", ".join(r["merged"]))}</div>'
                  if r["merged"] else "")
        body.append(
            f'<tr class="{grp_cls.get(r["group"], "")}">'
            f'<td class="rk">{r["rank"]}</td>'
            f'<td><div class="dn">{esc(r["label"])}</div>{merged}</td>'
            f'<td><span class="gchip">{esc(r["group"])}</span></td>'
            f'<td class="num ade"><div class="bar"><i style="width:{w:.0f}%"></i></div>'
            f'<b>{r["ade"]:.2f}</b> m</td>'
            f'<td class="num">{r["speed"]:.2f}</td>'
            f'<td class="num">{r["green"]:.2f}</td>'
            f'<td class="num">{r["pdms_gap"]:.3f}</td></tr>')
    body.append(
        f'<tr class="chance"><td class="rk">&mdash;</td><td><div class="dn">ten random scenes'
        f' from other logs</div></td><td><span class="gchip">chance</span></td>'
        f'<td class="num ade"><b>{ch["ade"]:.2f}</b> m</td><td class="num">{ch["speed"]:.2f}</td>'
        f'<td class="num">{ch["green"]:.2f}</td><td class="num">{ch["pdms_gap"]:.3f}</td></tr>')
    scoreboard = "\n".join(body)

    inv = []
    for title, items in INVENTORY:
        trs = "".join(
            f'<tr><td><b>{esc(a)}</b><div class="sub">{esc(b)}</div></td>'
            f'<td><span class="w w-{esc(c.split(",")[0].split(" ")[0])}">{esc(c)}</span></td>'
            f'<td class="why">{esc(d)}</td></tr>' for a, b, c, d in items)
        inv.append(f'<h3>{esc(title)}</h3><table class="inv"><tbody>{trs}</tbody></table>')
    inventory = "\n".join(inv)

    d = U.get("diag", {})
    diag_rows = ""
    for fam, lab in (("drivor", "DrivoR"), ("jepa", "Drive-JEPA")):
        if fam in d:
            x = d[fam]
            diag_rows += (f'<tr><td>{lab}</td><td class="num">{x["m"]}</td>'
                          f'<td class="num">{x["dropped"]}</td>'
                          f'<td class="num"><b>{x["dropped_share"]*100:.1f}%</b></td>'
                          f'<td class="num">{x["near_dead"]}</td>'
                          f'<td class="num">{x["cos_median"]:.4f}</td></tr>')

    tabbar = ('<nav id="navsim-tabbar" aria-label="Galleries"><span class="nt-home">NAVSIM eval</span>'
              + "".join(f'<a class="nt" href="{h}"{" aria-current=&quot;page&quot;" if h == "index.html" else ""}>{l}</a>'
                        for l, h in TABS) + "</nav>").replace("&quot;", '"')

    ours_full = next(r for r in rows if r["key"] == "ours_repr")
    ours_img = next(r for r in rows if r["key"] == "ours_visual")
    stock = next(r for r in rows if r["key"] == "stock_cls")
    ft = next(r for r in rows if r["key"] == "ft_cls")
    ctrl = next(r for r in rows if r["key"] == "ctrl_motion_cmd")

    payload = json.dumps({"rows": rows, "queries": U["queries"], "scenes": U["scenes"],
                          "default_on": DEFAULT_ON}, separators=(",", ":"))
    page = (TEMPLATE
            .replace("__TABBAR__", tabbar)
            .replace("__NQ__", f'{U["n_queries_bench"]:,}')
            .replace("__NC__", f'{U["n_corpus"]:,}')
            .replace("__SCOREBOARD__", scoreboard)
            .replace("__INVENTORY__", inventory)
            .replace("__DIAG__", diag_rows)
            .replace("__STOCK_ADE__", f'{stock["ade"]:.2f}')
            .replace("__FT_ADE__", f'{ft["ade"]:.2f}')
            .replace("__IMG_ADE__", f'{ours_img["ade"]:.2f}')
            .replace("__FULL_ADE__", f'{ours_full["ade"]:.2f}')
            .replace("__CTRL_ADE__", f'{ctrl["ade"]:.2f}')
            .replace("__FULL_GAIN__", f'{(1 - ours_full["ade"] / stock["ade"]) * 100:.0f}')
            .replace("__GEN__", esc(U["generated_utc"]))
            .replace("__PAYLOAD__", payload.replace("</", "<\\/")))
    (DST / "index.html").write_text(page, encoding="utf-8")
    print(f"[page] wrote {DST/'index.html'} ({len(page)/1024:.0f} KB), {len(rows)} ranked rows")


TEMPLATE = open(Path(__file__).with_name("page_template.html"), encoding="utf-8").read() \
    if Path(__file__).with_name("page_template.html").is_file() else ""

if __name__ == "__main__":
    if not TEMPLATE:
        raise SystemExit("page_template.html missing")
    main()
