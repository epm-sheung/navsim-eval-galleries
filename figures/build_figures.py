# -*- coding: utf-8 -*-
"""Generate figures/index.html from the gated figdata.json.

Every number on the page comes from figdata.json, which was reconciled against the
official per-scene CSVs (8 models, n=12,146, max error 2.2e-16). Re-run to refresh.
"""
import json, os, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "figdata.json")))

SHORT = {
    "variant1_patch_tokens_film": "variant1 (patch)",
    "cmd_tokens_film":            "cmd_tokens_film ★",
    "cls_tokens_film":            "cls_tokens_film",
    "sae_armAp_control":          "SAE A′",
    "sae_armBp_static":           "SAE B′",
    "transfuser":                 "TransFuser",
    "human":                      "human",
    "constant_velocity":          "const-velocity",
}
LEARNED = ["cmd_tokens_film","variant1_patch_tokens_film","sae_armBp_static",
           "sae_armAp_control","cls_tokens_film"]
WITH_TF = ["cmd_tokens_film","transfuser","variant1_patch_tokens_film",
           "sae_armBp_static","sae_armAp_control","cls_tokens_film"]
REF = "cmd_tokens_film"
SEED_SPREAD = 2.33     # points, from the seed-43 replication (upper bound)

# ---------------------------------------------------------------- figure data
fig = {}

# F1 rank correlation (interior + full), learned models only
fig["corr"] = [{"m": SHORT[m],
                "loss_i": D["correlation"][m]["loss_vs_score"]["interior_rho"],
                "ade_i":  D["correlation"][m]["ade_vs_score"]["interior_rho"],
                "loss_f": D["correlation"][m]["loss_vs_score"]["full_rho"],
                "ade_f":  D["correlation"][m]["ade_vs_score"]["full_rho"]}
               for m in LEARNED]

# F2 ablation deltas against the reference, in PDMS points
ref = D["subscores"][REF]["score"]
fig["delta"] = {"ref": SHORT[REF], "ref_score": ref, "band": SEED_SPREAD,
                "rows": [{"m": SHORT[m], "d": round((D["subscores"][m]["score"]-ref)*100, 2),
                          "s": D["subscores"][m]["score"]}
                         for m in WITH_TF if m != REF]}

# F3 bin hardness
fig["bins"] = [{"lo": b["lo"], "n": b["n"], "margin": b["margin"], "agents": b["agents"]}
               for b in D["bin_hardness"]]

# F4 oracle vs K
ok = D["oracle_k"]
fig["oracle"] = {"k": ok["k"], "score": ok["score"], "ref": ok["vocab_only"]}

# F5 sub-scores + gate failures
fig["sub"] = [{"m": SHORT[m], **{k: D["subscores"][m][k] for k in
               ("nc","dac","ep","ttc","comfort","ddc")}} for m in WITH_TF + ["human"]]
fig["gate"] = [{"m": SHORT[m], **{k: round(D["gate_fail"][m][k]*100, 2) for k in
                ("nc_lt1","dac_lt1","ttc_lt1")}} for m in WITH_TF]

DATA = json.dumps(fig, separators=(",", ":"))
STAMP = datetime.date.today().isoformat()
print("inlined data: %.1f KB" % (len(DATA)/1024.0))
open(os.path.join(HERE, "_figdata_inline.js"), "w").write("window.FIG=" + DATA + ";")

# ------------------------------------------------------------------ emit page
import _page_template as T
html = T.HEAD + T.BODY.replace("__STAMP__", STAMP) + T.SCRIPT.replace("__DATA__", DATA)
out = os.path.join(HERE, "index.html")
open(out, "w").write(html)
print("wrote %s  (%.1f KB)" % (out, len(html)/1024.0))
