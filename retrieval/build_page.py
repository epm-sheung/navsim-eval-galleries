# -*- coding: utf-8 -*-
"""Build navsim_pages/retrieval/index.html from the retrieval run output.

Reads /scratch/eddie96/eddie/navsim_retrieval/out/retrieval.json, copies only the
thumbnails the page actually draws, and inlines a trimmed payload so the page is
self-contained (no fetch, works from file:// as well as GitHub Pages).
"""
import json, os, shutil, sys, time
from pathlib import Path

SRC = Path("/scratch/eddie96/eddie/navsim_retrieval/out")
DST = Path("/scratch/eddie96/eddie/navsim_pages/retrieval")
TABS = [("Findings", "../index.html"), ("Why peaks", "../why_peaks.html"),
        ("Scoreboard", "../session_scoreboard/index.html"),
        ("Scenes", "../scenes/index.html"),
        ("Distributions", "../distributions/index.html"),
        ("Figures", "../figures/index.html"),
        ("Retrieval", "index.html")]

TABCSS = """
#navsim-tabbar{position:sticky;top:0;z-index:99999;display:flex;gap:2px;flex-wrap:wrap;
  align-items:center;padding:8px 14px;margin:0;background:#fbfbfa;
  border-bottom:1px solid #dcdedb;font-family:"IBM Plex Sans",system-ui,sans-serif;}
#navsim-tabbar .nt-home{font-size:12px;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;color:#78828e;margin-right:12px;}
#navsim-tabbar a.nt{font-size:13.5px;font-weight:500;color:#4a535e;text-decoration:none;
  padding:7px 13px;border-radius:5px;border:1px solid transparent;white-space:nowrap;}
#navsim-tabbar a.nt:hover{background:#e9eae7;color:#1b2027;}
#navsim-tabbar a.nt[aria-current="page"]{background:#e2eeec;border-color:#1f6f6b;
  color:#1f6f6b;font-weight:600;}
@media (prefers-color-scheme:dark){
  #navsim-tabbar{background:#1b2025;border-bottom-color:#2c3238;}
  #navsim-tabbar a.nt{color:#a8b2b8;}
  #navsim-tabbar a.nt:hover{background:#242a2f;color:#e8ebe9;}
  #navsim-tabbar a.nt[aria-current="page"]{background:#1d3230;border-color:#5fbdb5;color:#5fbdb5;}
  #navsim-tabbar .nt-home{color:#78838b;}
}
"""

CSS = """
:root{--ground:#f4f5f3;--panel:#fbfbfa;--panel-2:#eceeea;--ink:#1b2027;--ink-2:#4a535e;
 --ink-3:#78828e;--rule:#dcdedb;--accent:#1f6f6b;--accent-soft:#e2eeec;
 --good:#2f7d4f;--warn:#b06a12;--crit:#a8322d;--good-bg:#e7f1ea;--crit-bg:#f6e6e5;}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
 --ground:#14181c;--panel:#1b2025;--panel-2:#242a2f;--ink:#e8ebe9;--ink-2:#a8b2b8;
 --ink-3:#78838b;--rule:#2c3238;--accent:#5fbdb5;--accent-soft:#1d3230;
 --good:#69c48d;--warn:#d69b44;--crit:#e08079;--good-bg:#17281e;--crit-bg:#2c1c1b;}}
*{box-sizing:border-box;}
body{margin:0;background:var(--ground);color:var(--ink);
 font-family:"IBM Plex Sans",system-ui,-apple-system,sans-serif;font-size:15.5px;line-height:1.65;}
.wrap{max-width:1420px;margin:0 auto;padding:36px 24px 90px;display:flex;
 flex-direction:column;gap:34px;}
.eyebrow{font-family:"IBM Plex Mono",ui-monospace,monospace;font-size:11.5px;
 letter-spacing:.13em;text-transform:uppercase;color:var(--ink-3);}
h1{font-family:"IBM Plex Serif",Georgia,serif;font-weight:600;font-size:33px;margin:0;
 letter-spacing:-.015em;}
h2{font-family:"IBM Plex Serif",Georgia,serif;font-weight:600;font-size:21px;margin:0 0 4px;}
header{display:flex;flex-direction:column;gap:10px;border-bottom:1px solid var(--rule);
 padding-bottom:22px;}
.standfirst{font-size:17px;color:var(--ink-2);margin:0;max-width:78ch;}
p{margin:0;} .measure{max-width:80ch;}
.note{font-size:13.5px;color:var(--ink-2);}
.mono{font-family:"IBM Plex Mono",ui-monospace,monospace;}
table{border-collapse:collapse;font-size:13.5px;background:var(--panel);
 border:1px solid var(--rule);border-radius:5px;}
th,td{padding:7px 12px;text-align:right;border-bottom:1px solid var(--rule);}
th:first-child,td:first-child{text-align:left;}
thead th{background:var(--panel-2);font-weight:600;font-size:12.5px;color:var(--ink-2);}
tbody tr:last-child td{border-bottom:none;}
td.win{color:var(--good);font-weight:600;}
.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap;
 position:sticky;top:45px;z-index:90;background:var(--ground);padding:10px 0;
 border-bottom:1px solid var(--rule);}
button.seg{font:inherit;font-size:13px;padding:6px 14px;border-radius:5px;cursor:pointer;
 border:1px solid var(--rule);background:var(--panel);color:var(--ink-2);}
button.seg[aria-pressed="true"]{background:var(--accent-soft);border-color:var(--accent);
 color:var(--accent);font-weight:600;}
.q{background:var(--panel);border:1px solid var(--rule);border-radius:6px;padding:14px 16px;
 display:flex;flex-direction:column;gap:12px;}
.qhead{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;font-size:13px;
 color:var(--ink-2);}
.qhead .n{font-family:"IBM Plex Mono",monospace;font-size:12px;color:var(--ink-3);}
.qhead .tok{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink);}
.chip{font-size:11.5px;padding:2px 8px;border-radius:99px;border:1px solid var(--rule);
 background:var(--panel-2);color:var(--ink-2);font-family:"IBM Plex Mono",monospace;}
.chip.cmd{background:var(--accent-soft);border-color:var(--accent);color:var(--accent);}
.body{display:flex;gap:16px;align-items:flex-start;}
.qimg{flex:0 0 300px;display:flex;flex-direction:column;gap:5px;}
.qimg img{width:300px;border-radius:4px;display:block;border:2px solid var(--accent);}
.rows{flex:1 1 auto;display:flex;flex-direction:column;gap:12px;min-width:0;}
.row{display:flex;flex-direction:column;gap:5px;}
.rowlab{font-size:12.5px;font-weight:600;color:var(--ink-2);display:flex;gap:8px;
 align-items:baseline;}
.rowlab .sub{font-weight:400;font-size:11.5px;color:var(--ink-3);
 font-family:"IBM Plex Mono",monospace;}
.strip{display:grid;grid-template-columns:repeat(10,1fr);gap:6px;}
.nb{display:flex;flex-direction:column;gap:2px;min-width:0;}
.nb img{width:100%;border-radius:3px;display:block;border:1px solid var(--rule);}
.nb.match img{border-color:var(--good);border-width:2px;}
.nb .cap{font-family:"IBM Plex Mono",monospace;font-size:9.5px;color:var(--ink-3);
 line-height:1.35;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.nb .cap b{color:var(--ink-2);font-weight:500;}

@media (max-width:1100px){.body{flex-direction:column;}.qimg{flex:0 0 auto;}
 .strip{grid-template-columns:repeat(5,1fr);}}
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main():
    data = json.load(open(SRC / "retrieval.json"))
    DST.mkdir(parents=True, exist_ok=True)
    tdir = DST / "thumbs"
    tdir.mkdir(exist_ok=True)

    # ---- trim: the page draws CLS rows only; patch-token lists stay as stats ----
    meta = json.load(open(SRC / "scene_meta.json"))["scenes"]
    drawn = set()
    for q in data["queries"]:
        drawn.add(q["token"])
        q["models"] = {k: v for k, v in q["models"].items() if k.endswith("_cls")}
        for v in q["models"].values():
            for mode in v.values():
                for n in mode:                      # captions need these client-side
                    n["cmd"] = meta[n["token"]]["cmd"]
                    n["speed"] = meta[n["token"]]["speed_mps"]
                drawn.update(n["token"] for n in mode)

    n_copy = 0
    for tok in sorted(drawn):
        src = SRC / "thumbs" / f"{tok}.jpg"
        if not src.is_file():
            raise SystemExit(f"missing thumbnail for {tok}")
        dst = tdir / f"{tok}.jpg"
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)
            n_copy += 1
    for f in tdir.glob("*.jpg"):                    # drop thumbs no longer referenced
        if f.stem not in drawn:
            f.unlink()
    print(f"[thumbs] {len(drawn)} referenced, {n_copy} copied -> {tdir}")

    data.pop("thumbs", None)
    payload = json.dumps(data, separators=(",", ":"))

    s, ch = data["summary"], data["summary"]["chance"]
    em = data["embed_meta"]

    def row(label, key, mode):
        a, b = s["stock_cls"][mode], s["ft_cls"][mode]
        return (a[key], b[key])

    def cell(v, other, higher_better, fmt="%.3f"):
        win = (v > other) if higher_better else (v < other)
        return '<td class="%s">%s</td>' % ("win" if win else "", fmt % v)

    rows = []
    for label, key, hb, fmt in (
            ("Same direction as query", "cmd_match", True, "%.1f%%"),
            ("Speed error vs query", "speed_mae", False, "%.2f m/s"),
            ("Mean cosine similarity", "sim", True, "%.3f"),
    ):
        a, b = row(label, key, "xlog")
        av, bv = (a * 100, b * 100) if key == "cmd_match" else (a, b)
        chv = ch[key] * 100 if key == "cmd_match" else ch.get(key)
        chs = ("&mdash;" if chv is None else (fmt % chv))
        rows.append("<tr><td>%s</td>%s%s<td class='mono'>%s</td></tr>" % (
            label, cell(av, bv, hb, fmt), cell(bv, av, hb, fmt), chs))

    ov = s["overlap_at_10"]
    tabbar = ('<nav id="navsim-tabbar" aria-label="Galleries">'
              '<span class="nt-home">NAVSIM eval</span>' +
              "".join('<a class="nt" href="%s"%s>%s</a>' %
                      (h, ' aria-current="page"' if h == "index.html" else "", l)
                      for l, h in TABS) + "</nav>")

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Scene retrieval</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style id="navsim-tabbar-css">{TABCSS}</style>
<style>{CSS}</style>
</head><body>
{tabbar}
<div class="wrap">
<header>
  <div class="eyebrow">navtest &middot; {data['n_corpus']:,} scenes &middot; {data['n_logs']} logs</div>
  <h1>What each DINO thinks &ldquo;a similar scene&rdquo; means</h1>
  <p class="standfirst">Thirty query scenes, each one&rsquo;s <b>t0 camera frame &mdash; the last
  frame of the past</b> &mdash; matched against the t0 frame of all {data['n_corpus']:,} navtest
  scenes. Once with stock DINOv2 ViT-S/14, once with the trunk our driving model fine-tuned.
  Same image, same preprocessing, same CLS descriptor: only the weights differ.</p>
</header>

<section class="measure">
  <h2>How it was built</h2>
  <p class="note">Descriptor is the <span class="mono">x_norm_clstoken</span> of
  <span class="mono">forward_features</span>, L2-normalised, compared by cosine. Images come
  from the converted navtest cache at their stored
  {em['stored_image_hw'][1]}&times;{em['stored_image_hw'][0]}, so the transform is
  {esc(em['transform'])} &mdash; identical to what the waypoint models saw at eval time.
  The fine-tuned trunk is the one carried inside
  <span class="mono">waypoint_navsim_ft/epoch013-best.ckpt</span>; it differs from stock in
  {em['ft_tensors_differing_from_stock']} of 175 tensors (blocks&nbsp;10&ndash;11 and the final
  norm). Queries were chosen from <b>metadata only</b> &mdash; three per driving-command &times;
  speed-tercile cell, plus the three lowest-PDMS scenes &mdash; so neither embedding had a hand
  in picking them.</p>
  <p class="note"><b>Why &ldquo;other logs only&rdquo; is the default view.</b> navtest scenes
  from one log are seconds apart, so the plain top&nbsp;1 is nearly always the same car a moment
  later: a correct answer and a useless picture. Stock fills
  {s['stock_cls']['raw']['same_log']*100:.0f}% of its raw top-10 that way, the fine-tuned trunk
  {s['ft_cls']['raw']['same_log']*100:.0f}%. Switch to <i>Raw top-10</i> to see it.</p>
</section>

<section>
  <h2>The two trunks do not agree</h2>
  <p class="note measure">&ldquo;Direction&rdquo; here is the NAVSIM driving command at t0
  &mdash; left, straight or right &mdash; the same field the chips on each query carry.</p>
  <table>
    <thead><tr><th>Across other logs, mean over 30 queries &times; 10 neighbours</th>
      <th>Stock DINOv2</th><th>Fine-tuned</th><th>Chance</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <p class="note measure">Neighbours shared by both models, out of 10:
  <b>{ov['xlog']:.1f}</b> across other logs, <b>{ov['raw']:.1f}</b> on the raw list &mdash;
  against {ch['overlap_at_10']:.4f} expected by chance. On the <i>same</i> image the two CLS
  vectors have cosine <b>{data['cosine_stock_vs_ft_same_image']:.3f}</b>: touching 30 tensors
  moved the representation to a largely unrelated direction, not a nudge.</p>
  <p class="note measure">The fine-tuned trunk retrieves scenes that match the query&rsquo;s
  driving command more often and are closer in speed, which is what a trunk trained through a
  waypoint head should do. It is a descriptive result on 30 queries, not a benchmark: no
  retrieval ground truth exists here, so command and speed agreement are stand-ins for
  &ldquo;driving-relevant&rdquo;, and they are exactly the quantities the training signal
  depended on.</p>
</section>

<div class="controls">
  <span class="note">Neighbours:</span>
  <button class="seg" id="b-xlog" aria-pressed="true">Other logs only</button>
  <button class="seg" id="b-raw" aria-pressed="false">Raw top-10</button>
  <span class="note" style="margin-left:auto">green border = same direction as the query</span>
</div>

<section id="queries"></section>

<p class="note">Generated {esc(data['generated_utc'])} &middot; embeddings
{esc(em['generated_utc'])} &middot; {data['topk']} neighbours per model per query.</p>
</div>

<script id="data" type="application/json">{payload}</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const CMD = {{left:'&#8592; left', straight:'&#8593; straight', right:'right &#8594;'}};
let MODE = 'xlog';

function strip(list, qcmd) {{
  return list.map(n => {{
    const cls = 'nb' + (n.cmd === qcmd ? ' match' : '');
    return `<div class="${{cls}}">
      <img loading="lazy" src="thumbs/${{n.token}}.jpg" alt="${{n.token}}">
      <div class="cap"><b>${{n.sim.toFixed(3)}}</b> ${{n.cmd[0]}} ${{n.speed.toFixed(1)}}m/s</div>
    </div>`;
  }}).join('');
}}

function render() {{
  const out = D.queries.map((q, i) => {{
    const m = q.meta;
    const pd = m.scores[D.headline_method];
    const rows = [['stock_cls', 'Stock DINOv2'], ['ft_cls', 'Fine-tuned DINOv2']].map(([k, lab]) => {{
      const list = q.models[k][MODE];
      const mean = list.reduce((a, b) => a + b.sim, 0) / list.length;
      const match = list.filter(n => n.cmd === m.cmd).length;
      return `<div class="row">
        <div class="rowlab">${{lab}}<span class="sub">mean cos ${{mean.toFixed(3)}}
          &middot; ${{match}}/10 same direction</span></div>
        <div class="strip">${{strip(list, m.cmd)}}</div></div>`;
    }}).join('');
    return `<div class="q">
      <div class="qhead"><span class="n">Q${{String(i + 1).padStart(2, '0')}}</span>
        <span class="tok">${{q.token}}</span>
        <span class="chip cmd">${{CMD[m.cmd] || m.cmd}}</span>
        <span class="chip">${{m.speed_mps.toFixed(1)}} m/s</span>
        <span class="chip">PDMS ${{pd === undefined ? '&mdash;' : pd.toFixed(3)}}</span>
        <span class="chip">${{m.log}}</span></div>
      <div class="body">
        <div class="qimg"><img src="thumbs/${{q.token}}.jpg" alt="query ${{q.token}}">
          <div class="note" style="font-size:12px">query &middot; t0 frame</div></div>
        <div class="rows">${{rows}}</div>
      </div></div>`;
  }}).join('');
  document.getElementById('queries').innerHTML = out;
}}

for (const [id, mode] of [['b-xlog', 'xlog'], ['b-raw', 'raw']]) {{
  document.getElementById(id).addEventListener('click', () => {{
    MODE = mode;
    document.getElementById('b-xlog').setAttribute('aria-pressed', String(mode === 'xlog'));
    document.getElementById('b-raw').setAttribute('aria-pressed', String(mode === 'raw'));
    render();
  }});
}}
render();
</script>
</body></html>
"""
    (DST / "index.html").write_text(html, encoding="utf-8")
    print(f"[page] wrote {DST / 'index.html'}  ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
