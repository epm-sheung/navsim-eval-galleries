#!/usr/bin/env python3
"""
Publication-quality BEV scene renderer for NAVSIM figures.

Pure raster rendering with Pillow (+ numpy, optional cv2 for a blur pass).
NO html/svg/matplotlib. Draws at 3x supersample and downsamples with LANCZOS.

Run only inside an sbatch job on a Fir compute node (see render_bev.sbatch).
"""
import json
import math
import re
import sys
import textwrap
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter

try:
    import cv2  # noqa: F401
    HAVE_CV2 = True
except Exception:
    HAVE_CV2 = False

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
SCENES = Path("/scratch/eddie96/eddie/navsim_pages/scenes")
EVENTS_DIR = SCENES / "events"
TRAJ_DIR = SCENES / "traj"
INDEX_PATH = SCENES / "index.json"
OUT_DIR = Path("/scratch/eddie96/eddie/navsim_pages/figures/bev")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Geometry constants
#
# All bev pixel coordinates in events/*.json and traj/*.json share ONE
# per-scene affine transform, given by traj/<token>.json's "bev_bounds":
#     px = (x_m - xmin) * scale               (x_m: forward metres, ego frame)
#     py = (ymax - y_m) * scale + oy           (y_m: lateral metres, ego frame)
# Verified empirically: at x_m=0,y_m=0 (the ego pose) this reproduces
# events methods.<m>.sim_path_bev[0] to within rounding, across many scenes.
# Inverse:
#     x_m = xmin + px/scale
#     y_m = ymax - (py-oy)/scale
# `scale` is metres->pixels and is IDENTICAL for x and y (isotropic), but it
# is DIFFERENT PER SCENE (auto-fit to that scene's trajectory extent), so
# "540x540 pixel space" is not a shared/global frame across scenes -- see the
# E-panel consistency check in build_density_panel().
# --------------------------------------------------------------------------
NATIVE = 540           # native data coordinate span
SS = 3                 # supersample factor (relative to NATIVE)
FINAL_SCALE = 1080.0 / NATIVE   # 2.0 -> "540x540 -> 1080x1080"
DS_RATIO = SS / FINAL_SCALE     # 1.5 : internal->final downsample ratio


def n2i(v):
    """native units -> internal (supersampled) px"""
    return v * SS


def internal_size(w_native, h_native):
    return (int(round(w_native * SS)), int(round(h_native * SS)))


def final_size(w_native, h_native):
    return (int(round(w_native * FINAL_SCALE)), int(round(h_native * FINAL_SCALE)))


def ego_px(bb):
    """Ego (x_m=0, y_m=0) position in NATIVE pixel space for this scene."""
    return (-bb["xmin"] * bb["scale"], bb["ymax"] * bb["scale"] + bb["oy"])


def m_to_px(x_m, y_m, bb):
    return ((x_m - bb["xmin"]) * bb["scale"], (bb["ymax"] - y_m) * bb["scale"] + bb["oy"])


def px_to_m(px, py, bb):
    return (bb["xmin"] + px / bb["scale"], bb["ymax"] - (py - bb["oy"]) / bb["scale"])


# --------------------------------------------------------------------------
# Palette (dark-on-light, restrained, muted)
# --------------------------------------------------------------------------
BG = (250, 249, 245, 255)
INK = (35, 36, 40, 255)
INK_SOFT = (95, 97, 103, 255)
RULE = (210, 207, 198, 255)

DRIVABLE_FILL = (210, 221, 230, 235)
DRIVABLE_FILL_SUBDUED = (222, 229, 233, 130)
DRIVABLE_EDGE = (136, 156, 174, 255)
NONDRIVABLE_TINT = (196, 60, 55, 60)
NONDRIVABLE_HATCH = (196, 60, 55, 110)

TYPE_COLORS = {
    "VEHICLE": (66, 99, 148, 235),
    "PEDESTRIAN": (198, 120, 40, 235),
    "TRAFFIC_CONE": (176, 84, 58, 235),
    "GENERIC_OBJECT": (128, 116, 142, 235),
}
TYPE_EDGE = {k: tuple(max(0, c - 45) for c in v[:3]) + (255,) for k, v in TYPE_COLORS.items()}

EGO_FILL = (40, 43, 51, 255)
EGO_EDGE = (10, 11, 14, 255)

HUMAN_COLOR = (20, 128, 108, 255)
OURS_COLOR = (178, 40, 46, 255)
WARNING_COLOR = (214, 34, 34, 255)
INFERRED_COLOR = (206, 138, 16, 255)
CONFLICT_MARK = (214, 34, 34, 255)

GATE_PASS = (86, 140, 92, 255)
GATE_PARTIAL = (206, 150, 40, 255)
GATE_FAIL = (196, 58, 50, 255)

METHOD_PALETTE = [
    ("human", (25, 25, 25)),
    ("cmd_tokens_film", (178, 40, 46)),
    ("variant1_patch_tokens_film", (40, 96, 168)),
    ("cls_tokens_film", (54, 148, 96)),
    ("cmd_tokens_film_stockdino", (150, 96, 186)),
    ("transfuser", (198, 140, 24)),
    ("sae_armAp_control", (30, 150, 160)),
    ("sae_armBp_static", (108, 108, 190)),
    ("ego_status_mlp", (200, 90, 140)),
    ("constant_velocity", (140, 140, 140)),
]
METHOD_COLOR = {k: v for k, v in METHOD_PALETTE}

GATE_KEYS = ["nc", "dac", "ttc", "c", "ddc"]

# --------------------------------------------------------------------------
# Fonts
# --------------------------------------------------------------------------
_FONT_CACHE = {}


def find_font_file(bold=False):
    names = ["DejaVuSans-Bold.ttf", "DejaVuSans-bold.ttf"] if bold else ["DejaVuSans.ttf"]
    roots = ["/usr/share/fonts", "/usr/local/share/fonts", str(Path.home() / ".fonts"),
             "/cvmfs/soft.computecanada.ca"]
    for root in roots:
        p = Path(root)
        if not p.exists():
            continue
        try:
            for name in names:
                hits = list(p.rglob(name))
                if hits:
                    return str(hits[0])
        except Exception:
            continue
    # PIL's own bundled test fonts (rare, but check)
    try:
        import PIL
        p = Path(PIL.__file__).parent
        for name in names:
            hits = list(p.rglob(name))
            if hits:
                return str(hits[0])
    except Exception:
        pass
    return None


def load_font(size, bold=False):
    key = (int(size), bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    path = find_font_file(bold)
    font = None
    if path:
        try:
            font = ImageFont.truetype(path, size)
        except Exception:
            font = None
    if font is None:
        try:
            font = ImageFont.load_default(size=size)
        except Exception:
            font = ImageFont.load_default()
    _FONT_CACHE[key] = font
    return font


# --------------------------------------------------------------------------
# Low level drawing helpers (all operate in INTERNAL pixel space)
# --------------------------------------------------------------------------

def new_canvas(w_native, h_native):
    w, h = internal_size(w_native, h_native)
    img = Image.new("RGBA", (w, h), BG)
    return img


def to_c(pt, ox=0, oy=0):
    return (pt[0] * SS + ox, pt[1] * SS + oy)


def pts_to_c(pts, ox=0, oy=0):
    return [(p[0] * SS + ox, p[1] * SS + oy) for p in pts if p is not None]


def composite_layer(base, draw_fn):
    """Draw onto a fresh transparent layer via draw_fn(draw, layer) then alpha_composite it."""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    draw_fn(d, layer)
    base.alpha_composite(layer)


def build_drivable_mask(size, polys, ox=0, oy=0):
    """Union of (shell minus holes) for each polygon. Returns an 'L' mask image."""
    combined = Image.new("L", size, 0)
    for p in polys or []:
        shell = p.get("shell") or []
        if len(shell) < 3:
            continue
        sub = Image.new("L", size, 0)
        sd = ImageDraw.Draw(sub)
        sd.polygon(pts_to_c(shell, ox, oy), fill=255)
        for h in (p.get("holes") or []):
            if len(h) >= 3:
                sd.polygon(pts_to_c(h, ox, oy), fill=0)
        combined = ImageChops.lighter(combined, sub)
    return combined


def draw_drivable_area(img, polys, ox=0, oy=0, fill=DRIVABLE_FILL, edge=DRIVABLE_EDGE,
                        edge_w=4, draw_edge=True):
    mask = build_drivable_mask(img.size, polys, ox, oy)
    color_layer = Image.new("RGBA", img.size, fill)
    img.paste(color_layer, (0, 0), mask)
    if draw_edge:
        d = ImageDraw.Draw(img)
        for p in polys or []:
            shell = p.get("shell") or []
            if len(shell) >= 3:
                pts = pts_to_c(shell, ox, oy)
                d.line(pts + [pts[0]], fill=edge, width=edge_w, joint="curve")
            for h in (p.get("holes") or []):
                if len(h) >= 3:
                    hpts = pts_to_c(h, ox, oy)
                    d.line(hpts + [hpts[0]], fill=edge, width=max(2, edge_w - 1), joint="curve")
    return mask


def tint_nondrivable(img, drivable_mask, ox=0, oy=0, alpha_flat=55, hatch=True):
    inv = ImageChops.invert(drivable_mask)

    def _draw(d, layer):
        d.rectangle([0, 0, layer.size[0], layer.size[1]],
                    fill=(NONDRIVABLE_TINT[0], NONDRIVABLE_TINT[1], NONDRIVABLE_TINT[2], alpha_flat))
        if hatch:
            spacing = n2i(10)
            w, h = layer.size
            for x in range(-h, w, int(spacing)):
                d.line([(x, 0), (x + h, h)], fill=NONDRIVABLE_HATCH, width=max(2, int(n2i(0.6))))

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    _draw(d, layer)
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), inv))
    img.alpha_composite(layer)


def draw_box(img, corners, fill, outline, outline_w, ox=0, oy=0):
    if not corners or any(c is None for c in corners):
        return None
    pts = pts_to_c(corners, ox, oy)
    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=fill, outline=outline, width=outline_w)
    return pts


def box_center(corners):
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def ego_corners(bb, length_m=4.7, width_m=2.0):
    ex, ey = ego_px(bb)
    hl = (length_m / 2.0) * bb["scale"]
    hw = (width_m / 2.0) * bb["scale"]
    return [(ex - hl, ey - hw), (ex + hl, ey - hw), (ex + hl, ey + hw), (ex - hl, ey + hw)], (ex, ey, hl, hw)


def draw_ego(img, bb):
    corners, (ex, ey, hl, hw) = ego_corners(bb)
    draw_box(img, corners, EGO_FILL, EGO_EDGE, max(2, int(n2i(0.8))))
    d = ImageDraw.Draw(img)
    tip = to_c((ex + hl + 3.0 / 2.0 * 0, ey))  # placeholder, replaced below
    # heading arrow, points +x (forward), a small triangle ahead of the nose
    nose = to_c((ex + hl, ey))
    back_l = to_c((ex + hl - hw * 0.9, ey - hw * 0.6))
    back_r = to_c((ex + hl - hw * 0.9, ey + hw * 0.6))
    d.polygon([nose, back_l, back_r], fill=(255, 214, 90, 255), outline=EGO_EDGE)


def draw_polyline(img, pts, color, width, dashed=False, dash=16, gap=11, ox=0, oy=0):
    cpts = pts_to_c(pts, ox, oy)
    if len(cpts) < 2:
        return
    d = ImageDraw.Draw(img)
    if not dashed:
        d.line(cpts, fill=color, width=width, joint="curve")
        return
    for i in range(len(cpts) - 1):
        x0, y0 = cpts[i]
        x1, y1 = cpts[i + 1]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg < 1e-6:
            continue
        ux, uy = (x1 - x0) / seg, (y1 - y0) / seg
        dist = 0.0
        while dist < seg:
            sx, sy = x0 + ux * dist, y0 + uy * dist
            edist = min(dist + dash, seg)
            ex_, ey_ = x0 + ux * edist, y0 + uy * edist
            d.line([(sx, sy), (ex_, ey_)], fill=color, width=width)
            dist += dash + gap


def draw_dots(img, pts, color, r, ox=0, oy=0):
    d = ImageDraw.Draw(img)
    for x, y in pts_to_c(pts, ox, oy):
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def lerp_color(c0, c1, t):
    return tuple(int(round(c0[i] + (c1[i] - c0[i]) * t)) for i in range(4 if len(c0) == 4 else 3))


TIME_RAMP_STOPS = [(64, 74, 168, 255), (44, 140, 150, 255), (214, 170, 40, 255), (200, 60, 46, 255)]


def time_ramp_color(t):
    """t in [0,1] -> RGBA along a cool->warm ramp, used for time-coloured paths."""
    t = min(1.0, max(0.0, t))
    n = len(TIME_RAMP_STOPS) - 1
    seg = min(n - 1, int(t * n))
    local_t = t * n - seg
    return lerp_color(TIME_RAMP_STOPS[seg], TIME_RAMP_STOPS[seg + 1], local_t)


def draw_time_colored_path(img, pts, width, ox=0, oy=0):
    cpts = pts_to_c(pts, ox, oy)
    n = len(cpts)
    if n < 2:
        return
    d = ImageDraw.Draw(img)
    for i in range(n - 1):
        t = i / (n - 1)
        col = time_ramp_color(t)
        d.line([cpts[i], cpts[i + 1]], fill=col, width=width, joint="curve")
        r = width * 0.55
        d.ellipse([cpts[i][0] - r, cpts[i][1] - r, cpts[i][0] + r, cpts[i][1] + r], fill=col)
    r = width * 0.55
    lastcol = time_ramp_color(1.0)
    d.ellipse([cpts[-1][0] - r, cpts[-1][1] - r, cpts[-1][0] + r, cpts[-1][1] + r], fill=lastcol)


def wrap_text_px(draw, text, font, max_width):
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if cur == "" or draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def choose_scale_bar_m(bb, target_px=(60, 170)):
    for m in [1, 2, 5, 10, 20, 50]:
        px = m * bb["scale"]
        if target_px[0] <= px <= target_px[1]:
            return m
    # fall back to closest
    best = min([1, 2, 5, 10, 20, 50], key=lambda m: abs(m * bb["scale"] - 110))
    return best


def draw_scale_bar(img, bb, x0_native, y0_native, font):
    m = choose_scale_bar_m(bb)
    length_native = m * bb["scale"]
    x0 = n2i(x0_native)
    y0 = n2i(y0_native)
    x1 = x0 + n2i(length_native)
    d = ImageDraw.Draw(img)
    d.line([(x0, y0), (x1, y0)], fill=INK, width=max(3, int(n2i(0.55))))
    tick = n2i(4)
    d.line([(x0, y0 - tick), (x0, y0 + tick)], fill=INK, width=max(2, int(n2i(0.4))))
    d.line([(x1, y0 - tick), (x1, y0 + tick)], fill=INK, width=max(2, int(n2i(0.4))))
    label = f"{m} m"
    tw = d.textlength(label, font=font)
    d.text(((x0 + x1) / 2 - tw / 2, y0 - n2i(9)), label, font=font, fill=INK)
    return m


def panel_footer_bg(img, y0_native, h_native, native_w):
    d = ImageDraw.Draw(img)
    y0 = n2i(y0_native)
    d.rectangle([0, y0, n2i(native_w), y0 + n2i(h_native)], fill=(244, 242, 236, 255))
    d.line([(0, y0), (n2i(native_w), y0)], fill=RULE, width=max(2, int(n2i(0.3))))


def draw_legend_box(img, x_native, y_native, items, font, title=None, sw=15, row_h=24, pad=10):
    """items: list of (color_rgba, label_str). Draws a translucent card."""
    d = ImageDraw.Draw(img)
    max_w = 0
    for _, label in items:
        max_w = max(max_w, d.textlength(label, font=font))
    title_h = 0
    if title:
        title_h = row_h
    box_w = n2i(pad) * 2 + n2i(sw) + n2i(6) + max_w
    box_h = n2i(pad) * 2 + n2i(row_h) * len(items) + n2i(title_h)
    x0, y0 = n2i(x_native), n2i(y_native)

    def _bg(d2, layer):
        d2.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=n2i(6),
                              fill=(255, 255, 255, 222), outline=(190, 188, 180, 255),
                              width=max(1, int(n2i(0.3))))

    composite_layer(img, _bg)
    d = ImageDraw.Draw(img)
    ty = y0 + n2i(pad)
    if title:
        d.text((x0 + n2i(pad), ty), title, font=font, fill=INK)
        ty += n2i(title_h)
    for color, label in items:
        cy = ty + n2i(row_h) / 2
        d.ellipse([x0 + n2i(pad), cy - n2i(sw) / 2, x0 + n2i(pad) + n2i(sw), cy + n2i(sw) / 2],
                  fill=color)
        d.text((x0 + n2i(pad) + n2i(sw) + n2i(6), ty + n2i(2)), label, font=font, fill=INK)
        ty += n2i(row_h)
    return box_w / SS, box_h / SS  # native size used


def finalize(img, w_native, h_native, path):
    fw, fh = final_size(w_native, h_native)
    out = img.convert("RGB").resize((fw, fh), Image.LANCZOS)
    out.save(path, "PNG")
    return path, out.size


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_index():
    return load_json(INDEX_PATH)


def load_scene(token):
    e = load_json(EVENTS_DIR / f"{token}.json")
    t = load_json(TRAJ_DIR / f"{token}.json")
    return e, t


def diagnosed_method(events):
    """cmd_tokens_film if it has captions, else fall back to variant1_patch_tokens_film."""
    methods = events.get("methods", {})
    m = methods.get("cmd_tokens_film")
    caps = (m.get("captions") if m else None) or []
    name = "cmd_tokens_film"
    used_fallback = False
    if not caps:
        m2 = methods.get("variant1_patch_tokens_film")
        caps2 = (m2.get("captions") if m2 else None) or []
        if caps2:
            name, caps, used_fallback = "variant1_patch_tokens_film", caps2, True
    return name, caps, used_fallback


# --------------------------------------------------------------------------
# Deterministic scene selection
# --------------------------------------------------------------------------

def select_scenes(log):
    idx = load_index()
    token_split = {s["token"]: s["split"] for s in idx["scenes"]}
    navtest_tokens = sorted(t for t, sp in token_split.items() if sp == "navtest")
    log(f"[select] {len(navtest_tokens)} navtest tokens in index.json")

    s1, s2, s3, s4 = [], [], [], []
    pdms_all = []
    n_missing = 0

    for tok in navtest_tokens:
        ep = EVENTS_DIR / f"{tok}.json"
        tp = TRAJ_DIR / f"{tok}.json"
        if not ep.exists() or not tp.exists():
            n_missing += 1
            continue
        e = load_json(ep)
        t = load_json(tp)
        pdms = t.get("scores", {}).get("cmd_tokens_film", {}).get("pdms")
        if pdms is not None:
            pdms_all.append((tok, pdms))
        if e.get("any_failure") is False and pdms is not None and pdms >= 0.95:
            s1.append(tok)
        _, caps, _ = diagnosed_method(e)
        kinds = set(c.get("kind") for c in caps)
        if "ttc" in kinds:
            s2.append(tok)
        if "dac" in kinds:
            s3.append(tok)
        if "nc" in kinds:
            s4.append(tok)

    s1.sort(); s2.sort(); s3.sort(); s4.sort()
    pdms_all.sort(key=lambda x: x[1])
    log(f"[select] missing events/traj pairs skipped: {n_missing}")
    log(f"[select] S1 (clean, any_failure=False & cmd pdms>=0.95) candidates: {len(s1)}")
    log(f"[select] S2 (ttc caption on diagnosed method) candidates: {len(s2)}")
    log(f"[select] S3 (dac caption on diagnosed method) candidates: {len(s3)}")
    log(f"[select] S4 (nc caption on diagnosed method) candidates: {len(s4)}")

    chosen, reasons = {}, {}
    if s1:
        chosen["S1"] = s1[0]
        reasons["S1"] = (f"lexicographically-first of {len(s1)} navtest scenes with "
                          f"any_failure=False and cmd_tokens_film pdms>=0.95")
    else:
        raise RuntimeError("No S1 (clean) candidate found")

    if s2:
        chosen["S2"] = s2[0]
        reasons["S2"] = (f"lexicographically-first of {len(s2)} navtest scenes whose "
                          f"diagnosed method (cmd_tokens_film, or variant1_patch_tokens_film "
                          f"if cmd_tokens_film has no captions) has a 'ttc' caption")
    else:
        raise RuntimeError("No S2 (ttc) candidate found")

    if s3:
        chosen["S3"] = s3[0]
        reasons["S3"] = (f"lexicographically-first of {len(s3)} navtest scenes whose "
                          f"diagnosed method has a 'dac' caption")
    else:
        raise RuntimeError("No S3 (dac) candidate found")

    if s4:
        chosen["S4"] = s4[0]
        reasons["S4"] = (f"lexicographically-first of {len(s4)} navtest scenes whose "
                          f"diagnosed method has an 'nc' (at-fault collision) caption")
    else:
        tok, val = pdms_all[0]
        chosen["S4"] = tok
        reasons["S4"] = (f"NO navtest scene had an 'nc' caption on its diagnosed method; "
                          f"fell back to the LOWEST cmd_tokens_film pdms scene (pdms={val:.4f})")

    for k in ["S1", "S2", "S3", "S4"]:
        log(f"[select] {k} = {chosen[k]}  ({reasons[k]})")
    return chosen, reasons, pdms_all, navtest_tokens


# --------------------------------------------------------------------------
# Shared scene-drawing primitives used by A/B/C/D
# --------------------------------------------------------------------------

def frame0_bev(traj_json, method):
    m = traj_json.get("methods", {}).get(method)
    if not m:
        return []
    bev = m.get("bev")
    if not bev:
        return []
    return [p for p in bev[0] if p is not None]


def draw_base_map(img, events, bb, drivable_alpha_fill=DRIVABLE_FILL, edge_w=4, draw_edge=True):
    polys = events.get("drivable_area", {}).get("bev", [])
    mask = draw_drivable_area(img, polys, fill=drivable_alpha_fill, edge_w=edge_w, draw_edge=draw_edge)
    return mask


def draw_agents_t0(img, events):
    for o in events.get("agents", {}).get("objects", []):
        bevs = o.get("bev") or []
        if not bevs or bevs[0] is None:
            continue
        typ = o.get("type", "GENERIC_OBJECT")
        fill = TYPE_COLORS.get(typ, TYPE_COLORS["GENERIC_OBJECT"])
        edge = TYPE_EDGE.get(typ, TYPE_EDGE["GENERIC_OBJECT"])
        draw_box(img, bevs[0], fill, edge, max(2, int(n2i(0.5))))


TYPE_LABELS = {
    "VEHICLE": "vehicle",
    "PEDESTRIAN": "pedestrian",
    "TRAFFIC_CONE": "traffic cone",
    "GENERIC_OBJECT": "generic object",
}


# ==========================================================================
# FIGURE A -- publication BEV
# ==========================================================================

def build_clean_panel(token, events, traj, out_path, log):
    CAP_H = 74
    W, H = NATIVE, NATIVE + CAP_H
    img = new_canvas(W, H)

    bb = traj["bev_bounds"]
    draw_base_map(img, events)
    draw_agents_t0(img, events)
    draw_ego(img, bb)

    human_pts = frame0_bev(traj, "human")
    ours_pts = frame0_bev(traj, "cmd_tokens_film")
    if human_pts:
        draw_polyline(img, human_pts, HUMAN_COLOR, max(3, int(n2i(0.6))), dashed=True)
        draw_dots(img, human_pts, HUMAN_COLOR, n2i(2.6))
    if ours_pts:
        draw_polyline(img, ours_pts, OURS_COLOR, max(3, int(n2i(0.7))), dashed=False)
        draw_dots(img, ours_pts, OURS_COLOR, n2i(2.6))

    font = load_font(int(n2i(6.2)))
    font_small = load_font(int(n2i(5.0)))
    scale_m = draw_scale_bar(img, bb, 16, NATIVE - 14, font_small)

    legend_items = [
        (TYPE_COLORS["VEHICLE"], "vehicle"),
        (TYPE_COLORS["PEDESTRIAN"], "pedestrian"),
        (TYPE_COLORS["TRAFFIC_CONE"], "traffic cone"),
        (TYPE_COLORS["GENERIC_OBJECT"], "generic object"),
        (EGO_FILL, "ego"),
        (OURS_COLOR, "cmd_tokens_film (ours)"),
        (HUMAN_COLOR, "human (dashed)"),
    ]
    draw_legend_box(img, 12, 12, legend_items, font_small, title="Legend")

    panel_footer_bg(img, NATIVE, CAP_H, NATIVE)
    pdms = traj.get("scores", {}).get("cmd_tokens_film", {}).get("pdms")
    pdms_s = f"{pdms:.3f}" if pdms is not None else "n/a"
    d = ImageDraw.Draw(img)
    d.text((n2i(14), n2i(NATIVE + 12)), f"token {token}", font=font, fill=INK)
    d.text((n2i(14), n2i(NATIVE + 12 + 22)), f"cmd_tokens_film PDMS = {pdms_s}   "
           f"(scale bar = {scale_m} m, {1.0/bb['scale']:.3f} m/px this scene)",
           font=font_small, fill=INK_SOFT)

    path, size = finalize(img, W, H, out_path)
    log(f"  wrote {out_path.name}  {size}")
    return {"file": out_path.name, "token": token, "kind": "A_clean",
            "desc": "Publication BEV: drivable area, agents @ t=0, ego, human (dashed) vs "
                    "cmd_tokens_film (solid) trajectories, scale bar, legend, caption strip.",
            "pdms_cmd": pdms}


# ==========================================================================
# FIGURE B -- temporal / motion BEV
# ==========================================================================

def build_motion_panel(token, events, traj, out_path, log):
    FOOT_H = 40
    W, H = NATIVE, NATIVE + FOOT_H
    img = new_canvas(W, H)
    bb = traj["bev_bounds"]

    draw_base_map(img, events, drivable_alpha_fill=DRIVABLE_FILL_SUBDUED, edge_w=2)

    time_idcs = events.get("agents", {}).get("time_idcs", [])
    n_t = len(time_idcs)
    objects = events.get("agents", {}).get("objects", [])

    for ti in range(n_t):
        alpha_t = 0.12 + 0.88 * (ti / max(1, n_t - 1))

        def _draw(d, layer, ti=ti, alpha_t=alpha_t):
            for o in objects:
                bevs = o.get("bev") or []
                if ti >= len(bevs) or bevs[ti] is None:
                    continue
                typ = o.get("type", "GENERIC_OBJECT")
                base = TYPE_COLORS.get(typ, TYPE_COLORS["GENERIC_OBJECT"])
                fill = (base[0], base[1], base[2], int(base[3] * alpha_t))
                pts = pts_to_c(bevs[ti])
                if len(pts) >= 3:
                    d.polygon(pts, fill=fill)
        composite_layer(img, _draw)

    draw_ego(img, bb)
    ours_pts = frame0_bev(traj, "cmd_tokens_film")
    if ours_pts:
        draw_time_colored_path(img, ours_pts, max(4, int(n2i(0.9))))

    font_small = load_font(int(n2i(4.6)))
    # small time legend: a short colour ramp with 0 and 4s labels
    lx, ly = NATIVE - 118, 14
    d = ImageDraw.Draw(img)
    ramp_w, ramp_h = n2i(96), n2i(8)
    x0, y0 = n2i(lx), n2i(ly)
    for i in range(int(ramp_w)):
        t = i / ramp_w
        col = time_ramp_color(t)
        d.line([(x0 + i, y0), (x0 + i, y0 + ramp_h)], fill=col)
    d.rectangle([x0, y0, x0 + ramp_w, y0 + ramp_h], outline=(255, 255, 255, 255), width=1)
    d.text((x0 - n2i(2), y0 + ramp_h + n2i(3)), "t=0s", font=font_small, fill=INK)
    tw = d.textlength("t=4.0s", font=font_small)
    d.text((x0 + ramp_w - tw + n2i(2), y0 + ramp_h + n2i(3)), "t=4.0s", font=font_small, fill=INK)
    d.text((x0, y0 - n2i(11)), "agents t=0..4.0s / ego path time", font=font_small, fill=INK_SOFT)

    panel_footer_bg(img, NATIVE, FOOT_H, NATIVE)
    font = load_font(int(n2i(5.4)))
    d = ImageDraw.Draw(img)
    d.text((n2i(14), n2i(NATIVE + 10)),
           f"token {token} - temporal / motion BEV (ghost trail, faint=t0 -> solid=t+4.0s)",
           font=font, fill=INK)

    path, size = finalize(img, W, H, out_path)
    log(f"  wrote {out_path.name}  {size}")
    return {"file": out_path.name, "token": token, "kind": "B_motion",
            "desc": "Temporal BEV: every agent at all 9 sampled time indices (alpha ramp "
                    "t=0 faint -> t=+4.0s solid), ego path colour-ramped by time.",
            "pdms_cmd": traj.get("scores", {}).get("cmd_tokens_film", {}).get("pdms")}


# ==========================================================================
# FIGURE C -- failure-diagnostic BEV
# ==========================================================================

def parse_conflict(text):
    times = [float(x) for x in re.findall(r"at t=([\d.]+)\s*s", text)]
    t_conflict = times[-1] if times else None
    typ = None
    m = re.search(r"(vehicle|pedestrian|traffic cone|generic object)\s+at t=", text, re.I)
    if m:
        word = m.group(1).lower()
        typ = {"vehicle": "VEHICLE", "pedestrian": "PEDESTRIAN",
               "traffic cone": "TRAFFIC_CONE", "generic object": "GENERIC_OBJECT"}[word]
    return t_conflict, typ


def nearest_time_idx_pos(t_conflict, time_idcs):
    """time_idcs like [0,5,10,...,40] at 10Hz -> seconds; return position (0..len-1)."""
    if t_conflict is None:
        return 0
    secs = [ti / 10.0 for ti in time_idcs]
    diffs = [abs(s - t_conflict) for s in secs]
    return int(np.argmin(diffs))


def find_nearest_agent(events, pos, ego_pt, type_filter=None):
    objects = events.get("agents", {}).get("objects", [])
    best = None
    best_d = None
    for o in objects:
        bevs = o.get("bev") or []
        if pos >= len(bevs) or bevs[pos] is None:
            continue
        if type_filter and o.get("type") != type_filter:
            continue
        c = box_center(bevs[pos])
        dd = math.hypot(c[0] - ego_pt[0], c[1] - ego_pt[1])
        if best_d is None or dd < best_d:
            best_d, best = dd, o
    if best is None and type_filter is not None:
        return find_nearest_agent(events, pos, ego_pt, type_filter=None)
    return best, best_d


def segment_outside_mask(mask, p0, p1, n=14):
    """Sample a native-space segment; return list of native-space sub-points outside `mask`."""
    w, h = mask.size
    outside_pts = []
    for i in range(n + 1):
        t = i / n
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t
        cx, cy = int(x * SS), int(y * SS)
        v = 0
        if 0 <= cx < w and 0 <= cy < h:
            v = mask.getpixel((cx, cy))
        outside_pts.append((x, y, v <= 127))
    return outside_pts


def build_failure_panel(token, events, traj, out_path, log):
    GATE_H, CAP_H = 44, 150
    W, H = NATIVE, NATIVE + GATE_H + CAP_H
    img = new_canvas(W, H)
    bb = traj["bev_bounds"]

    method, caps, used_fallback = diagnosed_method(events)
    scores = events.get("methods", {}).get(method, {}).get("scores", {})
    sim_path = events.get("methods", {}).get(method, {}).get("sim_path_bev", [])
    time_idcs = events.get("agents", {}).get("time_idcs", [])

    mask = draw_base_map(img, events)
    draw_agents_t0(img, events)

    kinds_present = set(c.get("kind") for c in caps)
    infer_note = None

    if "dac" in kinds_present:
        tint_nondrivable(img, mask)
        ours_pts = frame0_bev(traj, method) or frame0_bev(traj, "cmd_tokens_film")
        if len(ours_pts) >= 2:
            d = ImageDraw.Draw(img)
            for i in range(len(ours_pts) - 1):
                p0, p1 = ours_pts[i], ours_pts[i + 1]
                samples = segment_outside_mask(mask, p0, p1)
                for j in range(len(samples) - 1):
                    x0, y0, out0 = samples[j]
                    x1, y1, out1 = samples[j + 1]
                    col = WARNING_COLOR if (out0 or out1) else OURS_COLOR
                    w_ = max(5, int(n2i(1.0))) if (out0 or out1) else max(3, int(n2i(0.6)))
                    d.line([to_c((x0, y0)), to_c((x1, y1))], fill=col, width=w_)
            draw_dots(img, ours_pts, OURS_COLOR, n2i(2.6))
        infer_note = "DAC: trajectory segments leaving the drivable polygon are highlighted in red; " \
                      "the non-drivable region is tinted/hatched."
    elif "nc" in kinds_present or "ttc" in kinds_present:
        kind = "nc" if "nc" in kinds_present else "ttc"
        cap = next(c for c in caps if c.get("kind") == kind)
        t_conflict, typ = parse_conflict(cap.get("text", ""))
        pos = nearest_time_idx_pos(t_conflict, time_idcs) if time_idcs else 0
        ego_pt = sim_path[pos] if pos < len(sim_path) else ego_px(bb)
        agent, dist = find_nearest_agent(events, pos, ego_pt, type_filter=typ)

        ours_pts = frame0_bev(traj, method) or frame0_bev(traj, "cmd_tokens_film")
        if ours_pts:
            draw_polyline(img, ours_pts, OURS_COLOR, max(3, int(n2i(0.6))))
            draw_dots(img, ours_pts, OURS_COLOR, n2i(2.4))

        if agent is not None:
            bevs = agent.get("bev") or []
            corners = bevs[pos] if pos < len(bevs) else None
            if corners:
                d = ImageDraw.Draw(img)
                pts = pts_to_c(corners)
                d.line(pts + [pts[0]], fill=INFERRED_COLOR, width=max(6, int(n2i(1.1))))
                c = box_center(corners)
                cc = to_c(c)
                d.text((cc[0] + n2i(6), cc[1] - n2i(6)), "INFERRED",
                       font=load_font(int(n2i(4.6)), bold=True), fill=INFERRED_COLOR)
            infer_note = (f"{kind.upper()}: highlighted agent is the nearest "
                          f"{TYPE_LABELS.get(agent.get('type'), 'agent')} to the {method} path at "
                          f"t={(t_conflict if t_conflict is not None else pos*0.5):.1f}s "
                          f"(distance {dist:.1f}px) -- INFERRED, not ground-truth fault attribution.")
        else:
            infer_note = f"{kind.upper()}: no agent present near the estimated conflict time " \
                          f"t={t_conflict}; conflict marker shown on the path only."

        cpt = to_c(ego_pt)
        d = ImageDraw.Draw(img)
        r = n2i(5)
        d.line([(cpt[0] - r, cpt[1] - r), (cpt[0] + r, cpt[1] + r)], fill=CONFLICT_MARK, width=max(4, int(n2i(0.8))))
        d.line([(cpt[0] - r, cpt[1] + r), (cpt[0] + r, cpt[1] - r)], fill=CONFLICT_MARK, width=max(4, int(n2i(0.8))))
        d.ellipse([cpt[0] - r * 1.6, cpt[1] - r * 1.6, cpt[0] + r * 1.6, cpt[1] + r * 1.6],
                  outline=CONFLICT_MARK, width=max(3, int(n2i(0.6))))
    else:
        ours_pts = frame0_bev(traj, method) or frame0_bev(traj, "cmd_tokens_film")
        if ours_pts:
            draw_polyline(img, ours_pts, OURS_COLOR, max(3, int(n2i(0.6))))
        infer_note = "No captioned gate failure found on the diagnosed method for this scene."

    draw_ego(img, bb)

    # gate score strip
    font_small = load_font(int(n2i(4.6)))
    font_small_b = load_font(int(n2i(4.6)), bold=True)
    gy = NATIVE
    panel_footer_bg(img, gy, GATE_H, NATIVE)
    d = ImageDraw.Draw(img)
    chip_w = NATIVE / len(GATE_KEYS)
    for i, k in enumerate(GATE_KEYS):
        v = scores.get(k)
        if v is None:
            col = (190, 190, 190, 255)
            vs = "n/a"
        elif v >= 1.0:
            col, vs = GATE_PASS, "1.0"
        elif v <= 0.0:
            col, vs = GATE_FAIL, "0.0"
        else:
            col, vs = GATE_PARTIAL, f"{v:.2g}"
        cx0 = n2i(i * chip_w + 4)
        cx1 = n2i((i + 1) * chip_w - 4)
        cy0 = n2i(gy + 6)
        cy1 = n2i(gy + GATE_H - 6)
        d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=n2i(4), fill=col)
        label = f"{k}={vs}"
        tw = d.textlength(label, font=font_small_b)
        d.text(((cx0 + cx1) / 2 - tw / 2, (cy0 + cy1) / 2 - n2i(3)), label,
               font=font_small_b, fill=(255, 255, 255, 255))

    # caption footer
    cap_y = NATIVE + GATE_H
    panel_footer_bg(img, cap_y, CAP_H, NATIVE)
    d = ImageDraw.Draw(img)
    font = load_font(int(n2i(5.0)))
    ty = cap_y + 8
    d.text((n2i(14), n2i(ty)), f"token {token}  |  diagnosed method: {method}"
           f"{'  (fallback from cmd_tokens_film)' if used_fallback else ''}", font=font, fill=INK)
    ty += 22
    for c in caps:
        line = f"[{c.get('kind')}] {c.get('text')}"
        for wline in wrap_text_px(d, line, font_small, n2i(NATIVE - 28)):
            d.text((n2i(14), n2i(ty)), wline, font=font_small, fill=INK)
            ty += 15
        ty += 4
    if infer_note:
        for wline in wrap_text_px(d, infer_note, font_small, n2i(NATIVE - 28)):
            d.text((n2i(14), n2i(ty)), wline, font=font_small, fill=INFERRED_COLOR)
            ty += 15

    path, size = finalize(img, W, H, out_path)
    log(f"  wrote {out_path.name}  {size}")
    return {"file": out_path.name, "token": token, "kind": "C_failure",
            "desc": f"Failure-diagnostic BEV for {method}: gate strip, highlighted failure "
                    f"geometry/agent, full caption text.",
            "pdms_cmd": traj.get("scores", {}).get("cmd_tokens_film", {}).get("pdms"),
            "diagnosed_method": method, "gate_scores": scores}


# ==========================================================================
# FIGURE D -- multi-method overlay
# ==========================================================================

def build_methods_panel(token, events, traj, out_path, log):
    LEGEND_W = 230
    TOP_H = 26
    W, H = NATIVE + LEGEND_W, NATIVE + TOP_H
    img = new_canvas(W, H)
    bb = traj["bev_bounds"]

    draw_base_map(img, events, drivable_alpha_fill=DRIVABLE_FILL_SUBDUED, edge_w=2)
    draw_agents_t0(img, events)
    draw_ego(img, bb)

    scores = traj.get("scores", {})
    methods_here = list(traj.get("methods", {}).keys())
    ranked = sorted(methods_here, key=lambda m: (scores.get(m, {}).get("pdms") is None,
                                                  -(scores.get(m, {}).get("pdms") or 0)))

    for m in methods_here:
        if m == "human":
            continue
        pts = frame0_bev(traj, m)
        if len(pts) < 2:
            continue
        col = METHOD_COLOR.get(m, (120, 120, 120)) + (215,)
        draw_polyline(img, pts, col, max(3, int(n2i(0.45))))
    human_pts = frame0_bev(traj, "human")
    if len(human_pts) >= 2:
        draw_polyline(img, human_pts, METHOD_COLOR["human"] + (255,), max(6, int(n2i(1.0))))

    font_small = load_font(int(n2i(4.6)))
    legend_items = []
    for m in ranked:
        pdms = scores.get(m, {}).get("pdms")
        label = f"{m}  ({pdms:.3f})" if pdms is not None else f"{m}  (n/a)"
        legend_items.append((METHOD_COLOR.get(m, (120, 120, 120)) + (255,), label))
    draw_legend_box(img, NATIVE + 10, TOP_H + 8, legend_items, font_small,
                     title="methods, sorted by PDMS")

    d = ImageDraw.Draw(img)
    font = load_font(int(n2i(5.6)))
    d.text((n2i(10), n2i(4)), f"token {token} - all methods, frame 0", font=font, fill=INK)

    path, size = finalize(img, W, H, out_path)
    log(f"  wrote {out_path.name}  {size}")
    return {"file": out_path.name, "token": token, "kind": "D_methods",
            "desc": "Multi-method trajectory overlay (all 10 methods incl. human) with a "
                    "PDMS-sorted legend.",
            "pdms_cmd": scores.get("cmd_tokens_film", {}).get("pdms")}


# ==========================================================================
# FIGURE E -- aggregate trajectory-distribution BEV over navtest
# ==========================================================================

def check_pixel_consistency(navtest_tokens, log, n_sample=30):
    sample = navtest_tokens[:n_sample]
    pts = []
    for tok in sample:
        tp = TRAJ_DIR / f"{tok}.json"
        if not tp.exists():
            continue
        t = load_json(tp)
        fb = frame0_bev(t, "cmd_tokens_film")
        if fb:
            pts.append(fb[0])
    if len(pts) < 3:
        log("[E] pixel-consistency check: insufficient samples")
        return False, {}
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    stats = {
        "n": len(pts), "x_mean": float(xs.mean()), "x_std": float(xs.std()),
        "y_mean": float(ys.mean()), "y_std": float(ys.std()),
        "x_min": float(xs.min()), "x_max": float(xs.max()),
        "y_min": float(ys.min()), "y_max": float(ys.max()),
    }
    log(f"[E] pixel-consistency check over first {stats['n']} navtest tokens "
        f"(frame-0 first waypoint of cmd_tokens_film, raw pixel space):")
    log(f"[E]   x: mean={stats['x_mean']:.1f} std={stats['x_std']:.1f} "
        f"range=[{stats['x_min']:.1f},{stats['x_max']:.1f}]")
    log(f"[E]   y: mean={stats['y_mean']:.1f} std={stats['y_std']:.1f} "
        f"range=[{stats['y_min']:.1f},{stats['y_max']:.1f}]")
    # Consistent iff both stds are small relative to the 540px panel (< ~1% i.e. <5.4px)
    consistent = stats["x_std"] < 5.0 and stats["y_std"] < 5.0
    log(f"[E]   => {'CONSISTENT' if consistent else 'NOT consistent'} pixel space; "
        f"{'accumulating raw pixel coords' if consistent else 'falling back to per-scene metre normalisation via bev_bounds'}")
    return consistent, stats


def colormap_warm(t):
    """t in [0,1] -> RGB, dark ink -> teal -> amber -> cream (perceptual-ish, hand tuned)."""
    stops = [(24, 26, 40), (18, 92, 110), (60, 160, 130), (232, 186, 60), (250, 240, 210)]
    t = min(1.0, max(0.0, t))
    n = len(stops) - 1
    seg = min(n - 1, int(t * n))
    lt = t * n - seg
    c0, c1 = stops[seg], stops[seg + 1]
    return tuple(int(round(c0[i] + (c1[i] - c0[i]) * lt)) for i in range(3))


def build_density_panel(navtest_tokens, out_path, log):
    consistent, stats = check_pixel_consistency(navtest_tokens, log)

    xs_cmd, ys_cmd, xs_hum, ys_hum = [], [], [], []
    n_ok = 0
    for tok in navtest_tokens:
        tp = TRAJ_DIR / f"{tok}.json"
        if not tp.exists():
            continue
        t = load_json(tp)
        bb = t.get("bev_bounds")
        if not bb:
            continue
        cmd = frame0_bev(t, "cmd_tokens_film")
        hum = frame0_bev(t, "human")
        if not cmd and not hum:
            continue
        n_ok += 1
        for p in cmd:
            if consistent:
                xs_cmd.append(p[0]); ys_cmd.append(p[1])
            else:
                xm, ym = px_to_m(p[0], p[1], bb)
                xs_cmd.append(xm); ys_cmd.append(ym)
        for p in hum:
            if consistent:
                xs_hum.append(p[0]); ys_hum.append(p[1])
            else:
                xm, ym = px_to_m(p[0], p[1], bb)
                xs_hum.append(xm); ys_hum.append(ym)
    log(f"[E] accumulated waypoints from {n_ok} navtest scenes: "
        f"{len(xs_cmd)} cmd_tokens_film pts, {len(xs_hum)} human pts")

    xs_cmd = np.array(xs_cmd); ys_cmd = np.array(ys_cmd)
    xs_hum = np.array(xs_hum); ys_hum = np.array(ys_hum)

    if consistent:
        xr = (0, NATIVE); yr = (0, NATIVE)
        xlabel, ylabel = "panel px (fwd)", "panel px (lateral)"
    else:
        xlo, xhi = np.percentile(xs_cmd, [0.5, 99.5])
        ylo, yhi = np.percentile(ys_cmd, [0.5, 99.5])
        pad_x = 0.08 * (xhi - xlo); pad_y = 0.3 * (yhi - ylo)
        xr = (xlo - pad_x, xhi + pad_x)
        yr = (min(ylo - pad_y, -1.0), max(yhi + pad_y, 1.0))
        xlabel, ylabel = "forward, m (ego frame)", "lateral, m (ego frame)"
    log(f"[E] grid range: x={xr}, y={yr} ({'pixel' if consistent else 'metres'})")

    NB_X, NB_Y = 220, 160
    hist_cmd, xedges, yedges = np.histogram2d(xs_cmd, ys_cmd, bins=[NB_X, NB_Y], range=[xr, yr])
    hist_hum, _, _ = np.histogram2d(xs_hum, ys_hum, bins=[NB_X, NB_Y], range=[xr, yr])

    log_cmd = np.log1p(hist_cmd)
    norm_cmd = log_cmd / max(1e-9, log_cmd.max())
    log_hum = np.log1p(hist_hum)
    norm_hum = log_hum / max(1e-9, log_hum.max())

    # build RGB grid image: base heatmap + a cyan "human" channel blended on top (2nd channel overlay)
    grid = np.zeros((NB_Y, NB_X, 3), dtype=np.uint8)
    for ix in range(NB_X):
        for iy in range(NB_Y):
            grid[iy, ix] = colormap_warm(norm_cmd[ix, iy])
    heat_img = Image.fromarray(grid, mode="RGB").transpose(Image.FLIP_TOP_BOTTOM)

    hum_alpha = (norm_hum.T * 255).astype(np.uint8)
    hum_alpha_img = Image.fromarray(hum_alpha, mode="L").transpose(Image.FLIP_TOP_BOTTOM)
    hum_layer = Image.new("RGBA", heat_img.size, (0, 235, 235, 0))
    hum_layer.putalpha(hum_alpha_img)

    # compose final canvas: margins for axes + bottom caption
    MARGIN_L, MARGIN_B, CAP_H = 46, 34, 78
    W, H = NATIVE + MARGIN_L, NATIVE + MARGIN_B + CAP_H
    img = new_canvas(W, H)

    plot_w_native, plot_h_native = NATIVE, NATIVE
    heat_resized = heat_img.resize(internal_size(plot_w_native, plot_h_native), Image.NEAREST)
    hum_resized = hum_layer.resize(internal_size(plot_w_native, plot_h_native), Image.NEAREST)
    heat_resized = heat_resized.filter(ImageFilter.GaussianBlur(radius=SS))
    hum_resized = hum_resized.filter(ImageFilter.GaussianBlur(radius=SS))

    px0, py0 = n2i(MARGIN_L), n2i(4)
    img.paste(heat_resized.convert("RGBA"), (int(px0), int(py0)))
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    layer.paste(hum_resized, (int(px0), int(py0)), hum_resized)
    img.alpha_composite(layer)

    d = ImageDraw.Draw(img)
    font_small = load_font(int(n2i(4.4)))
    font = load_font(int(n2i(5.6)))
    # axis ticks (4 each)
    for i in range(5):
        fx = xr[0] + (xr[1] - xr[0]) * i / 4
        gx = px0 + n2i(plot_w_native) * i / 4
        d.line([(gx, py0 + n2i(plot_h_native)), (gx, py0 + n2i(plot_h_native) + n2i(4))], fill=INK)
        lbl = f"{fx:.0f}"
        tw = d.textlength(lbl, font=font_small)
        d.text((gx - tw / 2, py0 + n2i(plot_h_native) + n2i(6)), lbl, font=font_small, fill=INK_SOFT)
    for i in range(5):
        fy = yr[1] - (yr[1] - yr[0]) * i / 4
        gy = py0 + n2i(plot_h_native) * i / 4
        d.line([(px0 - n2i(4), gy), (px0, gy)], fill=INK)
        lbl = f"{fy:.0f}"
        tw = d.textlength(lbl, font=font_small)
        d.text((px0 - n2i(6) - tw, gy - n2i(4)), lbl, font=font_small, fill=INK_SOFT)
    d.text((n2i(2), n2i(2)), ylabel, font=font_small, fill=INK_SOFT)
    xl_w = d.textlength(xlabel, font=font_small)
    d.text((px0 + n2i(plot_w_native) / 2 - xl_w / 2, py0 + n2i(plot_h_native) + n2i(18)),
           xlabel, font=font_small, fill=INK_SOFT)

    if not consistent:
        ex, ey = 0.0, 0.0
        gx = px0 + n2i(plot_w_native) * (ex - xr[0]) / (xr[1] - xr[0])
        gy = py0 + n2i(plot_h_native) * (1 - (ey - yr[0]) / (yr[1] - yr[0]))
        r = n2i(3.2)
        d.ellipse([gx - r, gy - r, gx + r, gy + r], outline=(255, 255, 255, 255), width=max(2, int(n2i(0.5))))
        d.text((gx + r + n2i(2), gy - n2i(6)), "ego", font=font_small, fill=(255, 255, 255, 255))

    legend_items = [((232, 186, 60, 255), "cmd_tokens_film density (log count)"),
                    ((0, 235, 235, 255), "human density (cyan overlay)")]
    draw_legend_box(img, 8, NATIVE + MARGIN_B - 34, legend_items, font_small)

    panel_footer_bg(img, NATIVE + MARGIN_B, CAP_H, W)
    ty = NATIVE + MARGIN_B + 10
    d = ImageDraw.Draw(img)
    d.text((n2i(14), n2i(ty)), f"Aggregate trajectory density over navtest (n={n_ok} scenes)",
           font=font, fill=INK)
    ty += 20
    mode_txt = ("pixel-space accumulation (frame-0 first waypoint was consistent across scenes)"
                if consistent else
                "metre-space accumulation via per-scene bev_bounds (frame-0 first waypoint was "
                f"NOT pixel-consistent: std x={stats.get('x_std', 0):.1f}px, "
                f"y={stats.get('y_std', 0):.1f}px)")
    for wline in wrap_text_px(d, mode_txt, font_small, n2i(W - 28)):
        d.text((n2i(14), n2i(ty)), wline, font=font_small, fill=INK_SOFT)
        ty += 14
    ty += 4
    note = ("Single panel: no driving-command field exists anywhere in events/, traj/ or "
            "index.json for this dataset, so no per-command split was produced.")
    for wline in wrap_text_px(d, note, font_small, n2i(W - 28)):
        d.text((n2i(14), n2i(ty)), wline, font=font_small, fill=INK_SOFT)
        ty += 14

    path, size = finalize(img, W, H, out_path)
    log(f"  wrote {out_path.name}  {size}")
    return {"file": out_path.name, "token": "ALL_NAVTEST", "kind": "E_density",
            "desc": f"Aggregate density of cmd_tokens_film frame-0 waypoints over {n_ok} "
                    f"navtest scenes (log-scaled), human overlaid as a cyan channel; "
                    f"{'pixel-space' if consistent else 'metre-space (bev_bounds-normalised)'} "
                    f"accumulation.",
            "pdms_cmd": None, "consistency_stats": stats, "consistent": consistent, "n_scenes": n_ok}

