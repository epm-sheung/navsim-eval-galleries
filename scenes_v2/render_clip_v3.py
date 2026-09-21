#!/usr/bin/env python3
"""
render_clip_v2.py -- upgraded NAVSIM scene-clip renderer.

Decodes the existing 2fps/7-frame camera-only clips at
scenes/clips/<token>.mp4 (no dataset re-access), and composites a much
richer 1920x1080 @ 20fps MP4: a cross-faded camera history phase, then a
held-camera future-rollout phase with a hand-drawn, supersampled BEV panel
(drivable area, moving agents, growing predicted trajectory, dashed human
reference, live per-gate score strip, clock, scale bar, legend, and failure
call-outs).

Must be run inside an sbatch job (compute node) -- see render_clip_v2.sbatch.
"""
import os
import sys
import io
import json
import glob
import math
import time
import traceback

ROOT = "/scratch/eddie96/eddie/navsim_pages/scenes"
OUT_ROOT = "/scratch/eddie96/eddie/navsim_pages/scenes_v2"
EVENTS_DIR = os.path.join(ROOT, "events")
TRAJ_DIR = os.path.join(ROOT, "traj")
CLIPS_DIR = os.path.join(ROOT, "clips")
OUT_CLIPS = os.path.join(OUT_ROOT, "clips")
OUT_STILLS = os.path.join(OUT_ROOT, "stills")
OUT_LOGS = os.path.join(OUT_ROOT, "logs")

METHOD = "cmd_tokens_film"
HUMAN_METHOD = "human"

FPS = 20
W, H = 1920, 1080
PHASE1_S = 2.0   # video seconds, real history span -1.5..0.0s
PHASE2_S = 6.6   # video seconds, real future span 0.0..4.0s
N1 = int(round(PHASE1_S * FPS))
N2 = int(round(PHASE2_S * FPS))

FONT_BOLD = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"

PALETTE = {
    "bg": (247, 245, 240),          # off-white BEV background (RGB)
    "drivable": (226, 230, 234),
    "drivable_edge": (150, 190, 205),
    "vehicle": (70, 110, 165),
    "pedestrian": (200, 95, 55),
    "cone": (215, 160, 40),
    "generic": (140, 140, 150),
    "ego": (25, 140, 90),
    "ego_trail": (25, 140, 90),
    "pred": (25, 105, 200),
    "human": (120, 120, 130),
    "nc": (215, 40, 40),
    "dac": (150, 60, 195),
    "ttc": (220, 155, 15),
    "text": (35, 35, 40),
    "subtext": (100, 100, 108),
    "panel_bg": (18, 20, 26),
    "on_dark": (214, 219, 226),
    "on_dark_dim": (150, 157, 168),
    "footer_bg": (250, 248, 244),
    "gate_pass": (60, 150, 95),
    "gate_fail": (205, 55, 55),
}

TYPE_KEY = {
    "VEHICLE": "vehicle",
    "PEDESTRIAN": "pedestrian",
    "TRAFFIC_CONE": "cone",
    "GENERIC_OBJECT": "generic",
}

GATES = ["nc", "dac", "ttc", "c", "ddc"]

# caption `kind` values ("nc","dac","ttc") vs the events sidecar dict keys
# that actually carry the failure geometry ("collision","dac","ttc") --
# the exporter names the NC sidecar "collision", everything else matches.
KIND_TO_SIDECAR = {"nc": "collision", "dac": "dac", "ttc": "ttc"}


def log(*a):
    print(*a, flush=True)


# --------------------------------------------------------------------- #
# environment probe
# --------------------------------------------------------------------- #
def probe_env():
    log("=== ENV PROBE ===")
    log("python:", sys.executable, sys.version.replace("\n", " "))
    try:
        import numpy
        log("numpy:", numpy.__version__)
    except Exception as e:
        log("numpy: FAILED", e)
    try:
        import PIL
        log("PIL/Pillow:", PIL.__version__)
    except Exception as e:
        log("PIL: FAILED", e)
    try:
        import cv2
        log("cv2:", cv2.__version__)
    except Exception as e:
        log("cv2: FAILED", e)
    try:
        import imageio
        log("imageio:", imageio.__version__)
    except Exception as e:
        log("imageio: not available (", e, ") -- ok if cv2 mp4v works")
    log("=== END ENV PROBE ===")


def transcode_h264(src, dst):
    """cv2 writes mp4v (MPEG-4 Part 2); no browser decodes that in <video>.
    Re-encode to H.264 + yuv420p with faststart so it streams and plays on the web."""
    import subprocess, shutil
    ff = shutil.which("ffmpeg")
    if not ff:
        log("  !! ffmpeg not found -- leaving mp4v file, it will NOT play in a browser")
        shutil.move(src, dst); return False
    cmd = [ff, "-y", "-loglevel", "error", "-i", src,
           "-c:v", "libx264", "-preset", "slow", "-crf", "19",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.0",
           "-movflags", "+faststart", "-an", dst]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        log("  !! ffmpeg failed rc=%s %s" % (r.returncode, (r.stderr or "")[:300]))
        shutil.move(src, dst); return False
    os.remove(src)
    return True


def selftest_video():
    """Write a tiny 5-frame mp4 and read it back. Raises on failure."""
    import numpy as np
    import cv2
    test_path = os.path.join(OUT_LOGS, "_selftest.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(test_path, fourcc, 5.0, (64, 48))
    if not vw.isOpened():
        raise RuntimeError("cv2.VideoWriter failed to open (mp4v)")
    for i in range(5):
        frame = np.full((48, 64, 3), i * 40, dtype=np.uint8)
        vw.write(frame)
    vw.release()
    size = os.path.getsize(test_path)
    cap = cv2.VideoCapture(test_path)
    n = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        n += 1
    cap.release()
    log("SELFTEST: wrote %d bytes, read back %d frames" % (size, n))
    if n < 3 or size < 200:
        raise RuntimeError("selftest video looks broken (frames=%d size=%d)" % (n, size))
    os.remove(test_path)
    log("SELFTEST OK")


# --------------------------------------------------------------------- #
# scene selection
# --------------------------------------------------------------------- #
def select_scenes():
    events_files = sorted(glob.glob(os.path.join(EVENTS_DIR, "*.json")))
    clean, ttc, dac, lowest = [], [], [], []
    meta = {}
    for ef in events_files:
        tok = os.path.basename(ef)[:-5]
        ed = json.load(open(ef))
        if ed.get("split") != "navtest":
            continue
        tf = os.path.join(TRAJ_DIR, tok + ".json")
        if not os.path.exists(tf):
            continue
        td = json.load(open(tf))
        sc = td.get("scores", {}).get(METHOD)
        if not sc or "pdms" not in sc:
            continue
        pdms = sc["pdms"]
        meta[tok] = pdms
        lowest.append((pdms, tok))
        if (not ed.get("any_failure")) and pdms >= 0.95:
            clean.append(tok)
        caps = (ed.get("methods", {}).get(METHOD, {}) or {}).get("captions") or []
        kinds = set(c.get("kind") for c in caps)
        if "ttc" in kinds:
            ttc.append(tok)
        if "dac" in kinds:
            dac.append(tok)

    clean.sort()
    ttc.sort()
    dac.sort()
    lowest.sort()

    used = set()
    chosen = []

    def take(pool, n, label, is_pairs=False):
        picked = []
        for item in pool:
            tok = item[1] if is_pairs else item
            if tok in used:
                continue
            used.add(tok)
            picked.append(tok)
            chosen.append((tok, label))
            if len(picked) >= n:
                break
        if len(picked) < n:
            log("WARNING: group '%s' only yielded %d/%d (pool size %d)" %
                (label, len(picked), n, len(pool)))
        return picked

    take(clean, 2, "clean")
    take(ttc, 2, "ttc")
    take(dac, 2, "dac")

    # backfill any short groups from the lowest-pdms pool
    n_short = 8 - len(chosen)
    if n_short > 0:
        take(lowest, n_short, "lowest(backfill)", is_pairs=True)
    else:
        take(lowest, 2, "lowest", is_pairs=True)

    log("=== SCENE SELECTION (%d tokens) ===" % len(chosen))
    for tok, label in chosen:
        log("  %s  %-8s  pdms(cmd_tokens_film)=%.4f" % (tok, label, meta[tok]))
    return chosen, meta


# --------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------- #
def lerp(a, b, t):
    return a + (b - a) * t


def lerp_pt(p, q, t):
    return (lerp(p[0], q[0], t), lerp(p[1], q[1], t))


def lerp_poly(a, b, t):
    return [lerp_pt(a[i], b[i], t) for i in range(min(len(a), len(b)))]


def poly_centroid(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def sample_track(series, time_idcs, real_t):
    """series: list aligned with time_idcs (0,5,...,40 -> 0.0..4.0s), entries
    are 4-corner boxes or None. Returns interpolated box at real_t (seconds)
    or None if untracked there (gap of >1 step, or off both ends)."""
    times = [ti * 0.1 for ti in time_idcs]
    if real_t <= times[0]:
        return series[0]
    if real_t >= times[-1]:
        return series[-1]
    for i in range(len(times) - 1):
        t0, t1 = times[i], times[i + 1]
        if t0 <= real_t <= t1:
            b0, b1 = series[i], series[i + 1]
            if b0 is None or b1 is None:
                return None
            tt = (real_t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return lerp_poly(b0, b1, tt)
    return None


def sample_path(anchor, waypoints, wp_times, real_t):
    """anchor at t=0, waypoints (8 pts) at wp_times (seconds). Returns
    interpolated (x,y) at real_t, plus a local heading vector (dx,dy)."""
    pts = [anchor] + list(waypoints)
    times = [0.0] + list(wp_times)
    if real_t <= times[0]:
        p = pts[0]
        q = pts[1]
        return p, (q[0] - p[0], q[1] - p[1])
    if real_t >= times[-1]:
        p = pts[-2]
        q = pts[-1]
        return q, (q[0] - p[0], q[1] - p[1])
    for i in range(len(times) - 1):
        t0, t1 = times[i], times[i + 1]
        if t0 <= real_t <= t1:
            tt = (real_t - t0) / (t1 - t0) if t1 > t0 else 0.0
            p = lerp_pt(pts[i], pts[i + 1], tt)
            d = (pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
            return p, d
    return pts[-1], (0, 0)


def ego_box_from_center(center, heading, length_px, width_px):
    dx, dy = heading
    n = math.hypot(dx, dy)
    if n < 1e-6:
        dx, dy = 0.0, -1.0
        n = 1.0
    ux, uy = dx / n, dy / n     # forward unit vector
    px, py = -uy, ux            # left-perpendicular unit vector
    hl, hw = length_px / 2.0, width_px / 2.0
    cx, cy = center
    corners = [
        (cx + ux * hl + px * hw, cy + uy * hl + py * hw),
        (cx - ux * hl + px * hw, cy - uy * hl + py * hw),
        (cx - ux * hl - px * hw, cy - uy * hl - py * hw),
        (cx + ux * hl - px * hw, cy + uy * hl - py * hw),
    ]
    return corners


# --------------------------------------------------------------------- #
# scene bundle
# --------------------------------------------------------------------- #
class Scene:
    def __init__(self, token, reason, pdms):
        self.token = token
        self.reason = reason
        self.pdms = pdms
        self.events = json.load(open(os.path.join(EVENTS_DIR, token + ".json")))
        self.traj = json.load(open(os.path.join(TRAJ_DIR, token + ".json")))
        self.split = self.events.get("split", "navtest")
        self.panels = self.events.get("panels", {"cam": {"w": 960, "h": 540},
                                                   "bev": {"w": 540, "h": 540}})
        bb = self.traj.get("bev_bounds", {})
        self.scale_px_per_m = bb.get("scale", 40.0)
        self.mpp = 1.0 / self.scale_px_per_m if self.scale_px_per_m else 0.025
        self._bb = bb; self._view = None

        mv = self.events.get("methods", {}).get(METHOD, {}) or {}
        self.scores = mv.get("scores", {})
        self.captions = mv.get("captions", []) or []
        self.sim_path_bev = mv.get("sim_path_bev") or []
        # failure sidecar geometry, if present (kind -> dict)
        self.failures = {}
        for kind in ("ttc", "dac", "collision"):
            if kind in mv:
                self.failures[kind] = mv[kind]

        tm = self.traj.get("methods", {}).get(METHOD, {}) or {}
        self.pred_bev_frames = tm.get("bev") or []   # 7 x 8 pts (all identical)
        self.pred_bev = self.pred_bev_frames[-1] if self.pred_bev_frames else []
        hm = self.traj.get("methods", {}).get(HUMAN_METHOD, {}) or {}
        self.human_bev_frames = hm.get("bev") or []
        self.human_bev = self.human_bev_frames[-1] if self.human_bev_frames else []

        # ego anchor at t=0: first point of the LQR-simulated path (events),
        # which is one step earlier than the raw predicted waypoint list.
        # APPROXIMATION: sim_path_bev[0] is the scorer's simulated t=0 ego
        # position, used here as the ego anchor for both predicted and human
        # (human has no sim_path of its own -- both trajectories share the
        # same starting ego state, so reusing this anchor is reasonable).
        if self.sim_path_bev:
            self.ego_anchor = tuple(self.sim_path_bev[0])
        elif self.pred_bev:
            # fallback: extrapolate one step back from the first waypoint
            p0, p1 = self.pred_bev[0], self.pred_bev[1]
            self.ego_anchor = (p0[0] - (p1[0] - p0[0]), p0[1] - (p1[1] - p0[1]))
        else:
            self.ego_anchor = (270.0, 400.0)

        # waypoint times: 8 predicted points at 0.5..4.0s (0.5s spacing)
        self.wp_times = [0.5 * (i + 1) for i in range(8)]

        # agents
        ag = self.events.get("agents", {})
        self.agent_time_idcs = ag.get("time_idcs", [0, 5, 10, 15, 20, 25, 30, 35, 40])
        self.agent_objects = ag.get("objects", [])

        # drivable area
        da = self.events.get("drivable_area", {})
        self.drivable_shells = da.get("bev", [])

        self.cam_frames_idx = self.events.get("cam_frames", [3, 4, 5, 6])
        self.n_frames = self.events.get("n_frames", 7)


# --------------------------------------------------------------------- #
# camera frame decode
# --------------------------------------------------------------------- #
def decode_history_frames(token):
    """Return list of up to 4 distinct RGB (H,W,3) uint8 camera frames
    (left 960x540 crop) decoded from the existing clip, in playback order."""
    import cv2
    import numpy as np
    clip_path = os.path.join(CLIPS_DIR, token + ".mp4")
    cap = cv2.VideoCapture(clip_path)
    frames = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        frames.append(fr)
    cap.release()
    if not frames:
        raise RuntimeError("could not decode any frames from %s" % clip_path)
    cam_w = 960
    cam_h = frames[0].shape[0]
    crops = []
    for fr in frames[:4]:
        crop = fr[:, :cam_w, :]
        crop = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        crops.append(crop)
    while len(crops) < 4:
        crops.append(crops[-1].copy())
    return crops, len(frames), frames[0].shape


# --------------------------------------------------------------------- #
# BEV rendering (supersampled)
# --------------------------------------------------------------------- #
BEV_OUT = 620          # final square size in the composite
BEV_SS = 3             # supersample factor
BEV_SRC = 540.0        # native panel is 540x540 pixel-space


def bev_scale_factor():
    return (BEV_OUT * BEV_SS) / BEV_SRC


def native_to_metric(bb):
    """Invert the gallery's bev_to_px. Without this the panel inherits the gallery's
    PER-SCENE fit, which zooms a slow scene to ~16 m and fills the frame with the ego."""
    sc = bb.get("scale", 40.0) or 40.0
    ox = bb.get("ox", 0.0); oy = bb.get("oy", 0.0)
    xmn = bb.get("xmin", 0.0); ymn = bb.get("ymin", 0.0)
    def f(pt):
        return ((pt[0] - ox) / sc + xmn, (BEV_SRC - pt[1] - oy) / sc + ymn)
    return f


def build_bev_view(scene):
    """Ego-centric metric window fitted to the DRIVING, with a clamped scale."""
    if scene._view:
        return scene._view
    T = native_to_metric(scene._bb)
    pts = [(0.0, 0.0), (4.0, 0.0)]
    for pt in (scene.pred_bev or []):
        pts.append(T(pt))
    hm = (scene.traj.get("methods", {}).get("human", {}) or {}).get("bev") or []
    if hm and hm[-1]:
        pts += [T(pt) for pt in hm[-1] if pt]
    xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    for o in scene.events.get("agents", {}).get("objects", []):
        for bx in (o.get("bev") or []):
            if not bx: continue
            for pt in bx:
                q = T(pt)
                if x0 - 14 <= q[0] <= x1 + 14 and y0 - 11 <= q[1] <= y1 + 11:
                    pts.append(q)
    xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
    pad = 5.0
    x0 = min(min(xs) - pad, -5.0); x1 = max(max(xs) + pad, 14.0)
    y0 = min(min(ys) - pad, -9.0); y1 = max(max(ys) + pad, 9.0)
    S = BEV_OUT * BEV_SS
    sc = min(S / max(x1 - x0, 1e-6), S / max(y1 - y0, 1e-6))
    sc = max(8.0 * BEV_SS, min(sc, 24.0 * BEV_SS))
    scene._view = (T, sc, (x0 + x1) / 2.0, (y0 + y1) / 2.0)
    scene.view_mpp = 1.0 / (sc / float(BEV_SS))
    return scene._view


def render_bev_frame(scene, phase, real_t, phase1_t=None, caption_active=None):
    """Returns a PIL RGB Image of size BEV_OUT x BEV_OUT."""
    from PIL import Image, ImageDraw
    S = BEV_OUT * BEV_SS
    # Original gallery mapping: the native 540 panel scaled straight up. Keeps the
    # trajectory geometry exactly as the shipped gallery draws it.
    sf = bev_scale_factor()
    img = Image.new("RGB", (S, S), PALETTE["bg"])
    d = ImageDraw.Draw(img, "RGBA")

    def px(pt):
        return (pt[0] * sf, pt[1] * sf)

    def poly_px(pts):
        return [px(p) for p in pts]

    # -- drivable area --------------------------------------------------
    da_alpha = 1.0
    if phase == 1:
        da_alpha = min(1.0, max(0.0, (phase1_t + 1.5) / 1.5))  # fade in over history
    for shell in scene.drivable_shells:
        ring = shell.get("shell") or []
        if len(ring) >= 3:
            d.polygon(poly_px(ring),
                      fill=PALETTE["drivable"] + (int(255 * da_alpha),), outline=None)
            d.line(poly_px(ring + [ring[0]]),
                   fill=PALETTE["drivable_edge"] + (int(210 * da_alpha),),
                   width=max(1, int(2 * BEV_SS * 0.6)))
        for hole in (shell.get("holes") or []):
            if len(hole) >= 3:
                d.polygon(poly_px(hole), fill=PALETTE["bg"] + (int(235 * da_alpha),))
                d.line(poly_px(hole + [hole[0]]),
                       fill=PALETTE["drivable_edge"] + (int(210 * da_alpha),),
                       width=max(1, int(2 * BEV_SS * 0.6)))

    # -- agents -----------------------------------------------------------
    agent_alpha = 1.0 if phase == 2 else min(1.0, max(0.0, (phase1_t + 0.9) / 0.9))
    trail_w = max(1, int(1.6 * BEV_SS))
    box_w = max(1, int(2.0 * BEV_SS))
    for obj in scene.agent_objects:
        series = obj.get("bev") or []
        typ = TYPE_KEY.get(obj.get("type"), "generic")
        col = PALETTE[typ]
        if phase == 1:
            box0 = series[0] if series else None
            if box0:
                d.polygon(poly_px(box0), outline=col + (int(235 * agent_alpha),),
                          width=box_w)
            continue
        # phase 2: interpolate + motion trail
        box = sample_track(series, scene.agent_time_idcs, real_t)
        # trail: sample a few points in the recent past
        trail_pts = []
        for dt in (0.6, 0.45, 0.3, 0.15, 0.0):
            tt = real_t - dt
            if tt < 0:
                continue
            b = sample_track(series, scene.agent_time_idcs, tt)
            if b is not None:
                trail_pts.append(poly_centroid(b))
        if len(trail_pts) >= 2:
            for i in range(len(trail_pts) - 1):
                a_ = 0.10 + 0.35 * (i / max(1, len(trail_pts) - 2))
                d.line([px(trail_pts[i]), px(trail_pts[i + 1])],
                       fill=col + (int(255 * a_),), width=trail_w)
        if box is not None:
            d.polygon(poly_px(box), outline=col + (235,), width=box_w)
            d.polygon(poly_px(box), fill=col + (55,))

    # -- human reference (dashed) ------------------------------------------
    if phase == 2 and scene.human_bev:
        pts = [scene.ego_anchor] + list(scene.human_bev)
        pts_px = poly_px(pts)
        dash_len, gap_len = 10 * BEV_SS, 7 * BEV_SS
        for i in range(len(pts_px) - 1):
            x0, y0 = pts_px[i]
            x1, y1 = pts_px[i + 1]
            seg_len = math.hypot(x1 - x0, y1 - y0)
            if seg_len < 1e-6:
                continue
            n_dashes = max(1, int(seg_len / (dash_len + gap_len)))
            for k in range(n_dashes + 1):
                t0 = k * (dash_len + gap_len) / seg_len
                t1 = min(1.0, t0 + dash_len / seg_len)
                if t0 >= 1.0:
                    break
                p0 = (lerp(x0, x1, t0), lerp(y0, y1, t0))
                p1 = (lerp(x0, x1, t1), lerp(y0, y1, t1))
                d.line([p0, p1], fill=PALETTE["human"] + (220,), width=max(1, int(2.2 * BEV_SS)))

    # -- predicted trajectory (growing) + ego box --------------------------
    if phase == 2:
        reveal_t = max(0.0, min(4.0, real_t))
        full_pts = [scene.ego_anchor] + list(scene.pred_bev)
        full_times = [0.0] + scene.wp_times
        drawn = [full_pts[0]]
        for i in range(1, len(full_pts)):
            if full_times[i] <= reveal_t:
                drawn.append(full_pts[i])
            else:
                t0, t1 = full_times[i - 1], full_times[i]
                tt = (reveal_t - t0) / (t1 - t0) if t1 > t0 else 0.0
                tt = max(0.0, min(1.0, tt))
                drawn.append(lerp_pt(full_pts[i - 1], full_pts[i], tt))
                break
        if len(drawn) >= 2:
            d.line(poly_px(drawn), fill=PALETTE["pred"] + (255,),
                   width=max(1, int(3.0 * BEV_SS)), joint="curve")
        for p in drawn[1:]:
            r = 2.6 * BEV_SS
            xx, yy = px(p)
            d.ellipse([xx - r, yy - r, xx + r, yy + r], fill=PALETTE["pred"] + (255,))

        ego_center, heading = sample_path(scene.ego_anchor, scene.pred_bev,
                                           scene.wp_times, real_t)
        length_m, width_m = 4.9, 2.0
        length_px = length_m * scene.scale_px_per_m
        width_px = width_m * scene.scale_px_per_m
        ego_poly = ego_box_from_center(ego_center, heading, length_px, width_px)
        d.polygon(poly_px(ego_poly), fill=PALETTE["ego"] + (90,),
                  outline=PALETTE["ego"] + (255,), width=max(1, int(2.4 * BEV_SS)))
        # heading tick
        dx, dy = heading
        n = math.hypot(dx, dy) or 1.0
        tip = (ego_center[0] + dx / n * (length_px * 0.55),
               ego_center[1] + dy / n * (length_px * 0.55))
        d.line([px(ego_center), px(tip)], fill=(255, 255, 255, 230),
               width=max(1, int(2.0 * BEV_SS)))
    else:
        # phase 1: static ego marker at t0
        ego_poly = ego_box_from_center(scene.ego_anchor, (0, -1),
                                        4.9 * scene.scale_px_per_m,
                                        2.0 * scene.scale_px_per_m)
        d.polygon(poly_px(ego_poly), fill=PALETTE["ego"] + (int(90 * agent_alpha),),
                  outline=PALETTE["ego"] + (int(255 * agent_alpha),),
                  width=max(1, int(2.4 * BEV_SS)))

    # -- failure highlight (flash) ------------------------------------------
    if phase == 2 and caption_active is not None:
        kind, fdict = caption_active
        col = PALETTE.get(kind, (200, 0, 0))
        b = (fdict or {}).get("bev") or {}
        pulse = 0.55 + 0.45 * math.sin(real_t * 10.0)
        if kind in ("ttc", "nc"):
            agent_poly = b.get("agent")
            if agent_poly:
                d.polygon(poly_px(agent_poly), outline=col + (255,),
                          width=max(1, int(3.2 * BEV_SS)))
            ego_poly2 = b.get("ego")
            if ego_poly2:
                d.polygon(poly_px(ego_poly2), outline=col + (int(255 * pulse),),
                          width=max(1, int(2.6 * BEV_SS)))
            imp = b.get("impact")
            if imp:
                r = 7 * BEV_SS
                xx, yy = px(imp)
                d.ellipse([xx - r, yy - r, xx + r, yy + r], outline=col + (255,),
                          width=max(1, int(2.4 * BEV_SS)))
        elif kind == "dac":
            for poly in (b if isinstance(b, list) else fdict.get("bev", [])):
                d.polygon(poly_px(poly), outline=col + (int(255 * pulse),),
                          width=max(1, int(3.2 * BEV_SS)))

    ds = img.resize((BEV_OUT, BEV_OUT), Image.LANCZOS)
    return ds


def draw_scale_bar(draw, x, y, mpp, out_px_per_native_px):
    """5 m scale bar. out_px_per_native_px converts native(540) px to the
    on-screen BEV_OUT px (BEV_OUT/BEV_SRC)."""
    meters = 5.0
    native_px = meters / mpp
    screen_px = native_px * out_px_per_native_px
    draw.line([(x, y), (x + screen_px, y)], fill=PALETTE["text"], width=3)
    for xx in (x, x + screen_px):
        draw.line([(xx, y - 5), (xx, y + 5)], fill=PALETTE["text"], width=3)
    draw.text((x, y + 8), "%d m" % int(meters), fill=PALETTE["text"])


# --------------------------------------------------------------------- #
# main frame compositor
# --------------------------------------------------------------------- #
def load_fonts():
    from PIL import ImageFont
    try:
        f_title = ImageFont.truetype(FONT_BOLD, 30)
        f_sub = ImageFont.truetype(FONT_REG, 20)
        f_body = ImageFont.truetype(FONT_REG, 22)
        f_small = ImageFont.truetype(FONT_REG, 17)
        f_gate = ImageFont.truetype(FONT_BOLD, 18)
        f_clock = ImageFont.truetype(FONT_BOLD, 26)
        f_legend = ImageFont.truetype(FONT_REG, 16)
    except Exception as e:
        log("WARNING: truetype font load failed (%s), falling back to default" % e)
        d = ImageFont.load_default()
        f_title = f_sub = f_body = f_small = f_gate = f_clock = f_legend = d
    return dict(title=f_title, sub=f_sub, body=f_body, small=f_small,
                gate=f_gate, clock=f_clock, legend=f_legend)


def active_caption(scene, real_t, phase):
    """Return (kind, failure_dict, caption_text) to show at this real_t, or
    None. Captions become relevant once real_t passes the event's time_s and
    stay up for the rest of the clip."""
    if phase != 2:
        return None
    best = None
    best_t = -1.0
    for cap in scene.captions:
        kind = cap.get("kind")
        fdict = scene.failures.get(KIND_TO_SIDECAR.get(kind, kind))
        # dac's sidecar uses "first_time_s" instead of "time_s"
        t_evt = (fdict or {}).get("time_s", (fdict or {}).get("first_time_s", 4.0))
        if real_t >= t_evt and t_evt > best_t:
            best = (kind, fdict, cap.get("text", ""))
            best_t = t_evt
    return best


def compose_frame(scene, cam_img_rgb, fonts, phase, real_t, phase1_t=None):
    from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (W, H), (16, 18, 23))
    d = ImageDraw.Draw(canvas, "RGBA")

    # ---- title strip -------------------------------------------------
    title_h = 74
    d.rectangle([0, 0, W, title_h], fill=(12, 13, 17))
    title = "%s   |   split: %s   |   %s PDMS: %.3f" % (
        scene.token, scene.split, METHOD, scene.pdms)
    d.text((24, 14), title, font=fonts["title"], fill=(235, 235, 238))
    d.text((24, 46), "scene: %s   ·   camera CAM_F0, letterboxed   ·   BEV is ego-centric, y-down" %
           scene.reason, font=fonts["small"], fill=(150, 155, 165))

    # ---- clock (top right) --------------------------------------------
    clock_txt = "t = %+.1f s" % real_t
    phase_txt = "HISTORY (replay)" if phase == 1 else "FUTURE ROLLOUT (predicted)"
    d.text((W - 320, 12), clock_txt, font=fonts["clock"], fill=(255, 255, 255))
    d.text((W - 320, 44), phase_txt, font=fonts["small"],
           fill=(120, 200, 255) if phase == 2 else (200, 200, 120))

    content_top = title_h
    content_bot = H - 130
    content_h = content_bot - content_top

    # ---- camera panel ----------------------------------------------------
    cam_w_area = 1280
    cam_disp_w, cam_disp_h = 1280, 720
    cx0 = 0
    cy0 = content_top + (content_h - cam_disp_h) // 2
    from PIL import Image as PILImage
    cam_pil = PILImage.fromarray(cam_img_rgb).resize((cam_disp_w, cam_disp_h), PILImage.LANCZOS)
    canvas.paste(cam_pil, (cx0, cy0))
    d.rectangle([cx0, cy0, cx0 + cam_disp_w, cy0 + cam_disp_h], outline=(60, 62, 70), width=2)

    # camera-panel overlay: growing projected trajectory (phase 2 only)
    if phase == 2:
        cam_sf_x = cam_disp_w / float(scene.panels["cam"]["w"])
        cam_sf_y = cam_disp_h / float(scene.panels["cam"]["h"])
        tm = scene.traj.get("methods", {}).get(METHOD, {})
        cam_pts = None
        for arr in (tm.get("cam") or []):
            if arr:
                cam_pts = arr
                break
        if cam_pts:
            reveal_t = max(0.0, min(4.0, real_t))
            n_show = max(1, int(round((reveal_t / 4.0) * len(cam_pts))))
            pts = [(cx0 + p[0] * cam_sf_x, cy0 + p[1] * cam_sf_y) for p in cam_pts[:n_show]]
            if len(pts) >= 2:
                d.line(pts, fill=PALETTE["pred"] + (235,), width=4, joint="curve")
            for p in pts:
                d.ellipse([p[0] - 4, p[1] - 4, p[0] + 4, p[1] + 4], fill=PALETTE["pred"] + (255,))

    # ---- BEV panel --------------------------------------------------------
    caption = active_caption(scene, real_t, phase)
    cap_for_bev = (caption[0], caption[1]) if caption else None
    bev_img = render_bev_frame(scene, phase, real_t, phase1_t=phase1_t, caption_active=cap_for_bev)
    bx0 = cam_w_area + (W - cam_w_area - BEV_OUT) // 2
    by0 = content_top + 46
    canvas.paste(bev_img, (bx0, by0))
    d.rectangle([bx0, by0, bx0 + BEV_OUT, by0 + BEV_OUT], outline=(200, 205, 210), width=2)
    d.text((bx0, content_top + 8), "BIRD'S-EYE VIEW  (ego-centric)", font=fonts["small"],
           fill=PALETTE["on_dark_dim"])

    # scale bar (bottom-left inside the BEV panel)
    out_px_per_native = BEV_OUT / BEV_SRC
    draw_scale_bar(d, bx0 + 14, by0 + BEV_OUT - 30, scene.mpp, out_px_per_native)

    # legend (right of BEV, below panel)
    leg_x = bx0
    leg_y = by0 + BEV_OUT + 12
    legend_items = [
        (PALETTE["pred"], "predicted (%s)" % METHOD),
        (PALETTE["human"], "human (dashed, reference)"),
        (PALETTE["ego"], "ego footprint"),
        (PALETTE["vehicle"], "vehicle"),
        (PALETTE["pedestrian"], "pedestrian"),
        (PALETTE["cone"], "cone / generic"),
    ]
    lx, ly = leg_x, leg_y
    col_w = BEV_OUT // 2
    for i, (col, label) in enumerate(legend_items):
        row = i % 3
        colu = i // 3
        yy = ly + row * 22
        xx = lx + colu * col_w
        d.rectangle([xx, yy + 4, xx + 16, yy + 14], fill=col + (255,))
        d.text((xx + 22, yy), label, font=fonts["legend"], fill=PALETTE["on_dark"])

    # ---- gate-score strip (top of BEV column, above panel) -----------------
    strip_y = title_h + 4
    strip_x = bx0
    # label removed: it overprinted the BEV panel title, and the chips are self-labelling

    # ---- footer band --------------------------------------------------------
    d.rectangle([0, content_bot, W, H], fill=PALETTE["footer_bg"])
    # gate chips
    gx = 24
    gy = content_bot + 14
    for g in GATES:
        val = scene.scores.get(g)
        if val is None:
            continue
        passed = val >= 0.999
        marginal = 0.001 <= val < 0.999
        col = PALETTE["gate_pass"] if passed else PALETTE["gate_fail"]
        chip_w = 150
        # flash the chip if it's the currently active failure kind
        flashing = caption is not None and caption[0] == g
        border = 3 if flashing else 1
        d.rectangle([gx, gy, gx + chip_w, gy + 34], outline=col, width=border,
                     fill=(255, 255, 255))
        label = "%s: %.2f" % (g.upper(), val)
        d.text((gx + 10, gy + 7), label, font=fonts["gate"], fill=col)
        gx += chip_w + 12

    # caption / failure footer text
    if caption is not None:
        kind, fdict, text = caption
        col = PALETTE.get(kind, (150, 20, 20))
        cap_y = gy + 46
        note = "[%s FAILURE]  %s" % (kind.upper(), text)
        d.text((24, cap_y), note, font=fonts["body"], fill=col)
        if kind in ("ttc", "nc") and fdict and fdict.get("agent_type"):
            d.text((24, cap_y + 26),
                   "implicated agent geometry is ground truth from the scorer sidecar (not inferred)",
                   font=fonts["small"], fill=PALETTE["subtext"])
        elif kind == "dac" and fdict:
            d.text((24, cap_y + 26),
                   "highlighted footprint is the ego's own off-road polygon (ground truth, not inferred)",
                   font=fonts["small"], fill=PALETTE["subtext"])
    else:
        # the chips can show a failed gate while no TIMED caption is active; saying
        # "no active failure" next to a red DAC 0.00 chip reads as a contradiction
        failed_gates = [k.upper() for k, v in (scene.scores or {}).items()
                        if v is not None and v < 0.999]
        if phase != 2:
            msg = "history replay -- future not yet scored"
            col = PALETTE["subtext"]
        elif failed_gates:
            msg = ("scene fails %s over the full 4 s horizon -- no per-instant geometry "
                   "recorded for it" % ", ".join(sorted(failed_gates)))
            col = PALETTE["gate_fail"]
        else:
            msg = "no active failure at this time"
            col = PALETTE["subtext"]
        d.text((24, gy + 46), msg, font=fonts["small"], fill=col)

    d.text((W - 300, gy + 46),
            "scale: 1 px \u2248 %.4f m" % scene.mpp,
            font=fonts["small"], fill=PALETTE["subtext"])

    return canvas


# --------------------------------------------------------------------- #
# per-scene render
# --------------------------------------------------------------------- #
def render_scene(scene, still_frame_fracs=(0.05, 0.35, 0.75)):
    import cv2
    import numpy as np

    hist_frames, orig_nframes, orig_shape = decode_history_frames(scene.token)
    fonts = load_fonts()

    out_path = os.path.join(OUT_CLIPS, scene.token + ".mp4")
    raw_path = out_path + ".mp4v.tmp.mp4"        # transcoded to H.264 after writing
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(raw_path, fourcc, FPS, (W, H))
    if not vw.isOpened():
        raise RuntimeError("VideoWriter failed to open for %s" % raw_path)

    total_frames = N1 + N2
    still_idcs = sorted(set(int(round(f * (total_frames - 1))) for f in still_frame_fracs))
    stills_written = []

    frame_i = 0
    # ---- Phase 1: cross-faded history, real_t -1.5 .. 0.0 -----------------
    n_seg = 3  # imgs[0]->1->2->3
    for i in range(N1):
        u = i / max(1, N1 - 1)           # 0..1 across full history
        phase1_t = lerp(-1.5, 0.0, u)
        seg_u = u * n_seg
        seg = min(n_seg - 1, int(seg_u))
        local_t = seg_u - seg
        a_img = hist_frames[seg].astype(np.float32)
        b_img = hist_frames[seg + 1].astype(np.float32)
        blended = (a_img * (1 - local_t) + b_img * local_t).astype(np.uint8)
        canvas = compose_frame(scene, blended, fonts, phase=1, real_t=phase1_t, phase1_t=phase1_t)
        bgr = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)
        vw.write(bgr)
        if frame_i in still_idcs:
            still_path = os.path.join(OUT_STILLS, "%s_t%02d.png" % (scene.token, frame_i))
            cv2.imwrite(still_path, bgr)
            stills_written.append((still_path, phase1_t, "history"))
        frame_i += 1

    # ---- Phase 2: held camera, future rollout, real_t 0.0 .. 4.0 -----------
    held_img = hist_frames[-1]
    for i in range(N2):
        u = i / max(1, N2 - 1)
        real_t = lerp(0.0, 4.0, u)
        canvas = compose_frame(scene, held_img, fonts, phase=2, real_t=real_t)
        bgr = cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR)
        vw.write(bgr)
        if frame_i in still_idcs:
            still_path = os.path.join(OUT_STILLS, "%s_t%02d.png" % (scene.token, frame_i))
            cv2.imwrite(still_path, bgr)
            stills_written.append((still_path, real_t, "future"))
        frame_i += 1

    vw.release()
    ok_h264 = transcode_h264(raw_path, out_path)
    log("  codec: %s" % ("H.264/yuv420p (web-playable)" if ok_h264
                         else "mp4v (NOT web-playable)"))
    return out_path, total_frames, stills_written, orig_nframes, orig_shape


# --------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------- #
def main():
    os.makedirs(OUT_CLIPS, exist_ok=True)
    os.makedirs(OUT_STILLS, exist_ok=True)
    os.makedirs(OUT_LOGS, exist_ok=True)

    probe_env()
    selftest_video()

    chosen, meta = select_scenes()

    manifest_lines = []
    manifest_lines.append("NAVSIM scenes_v2 render manifest")
    manifest_lines.append("generated: %s" % time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    manifest_lines.append("method shown: %s   fps: %d   resolution: %dx%d" % (METHOD, FPS, W, H))
    manifest_lines.append("phase1 (history, cross-faded real cam frames): %.1fs, real t=-1.5..0.0s" % PHASE1_S)
    manifest_lines.append("phase2 (future rollout, held cam + drawn overlay): %.1fs, real t=0.0..4.0s" % PHASE2_S)
    manifest_lines.append("")

    n_ok = 0
    for tok, label in chosen:
        try:
            log("\n### rendering %s (%s) ###" % (tok, label))
            scene = Scene(tok, label, meta[tok])
            t0 = time.time()
            out_path, total_frames, stills, orig_nf, orig_shape = render_scene(scene)
            dt = time.time() - t0
            size = os.path.getsize(out_path)
            log("  wrote %s  (%d bytes, %d frames, %.1fs render time)" %
                (out_path, size, total_frames, dt))
            log("  decoded %d frames from original clip, shape %s" % (orig_nf, orig_shape))
            for sp, rt, ph in stills:
                ssize = os.path.getsize(sp) if os.path.exists(sp) else -1
                log("  still: %s  (%s, real_t=%.2f, %d bytes)" % (sp, ph, rt, ssize))

            manifest_lines.append("token: %s" % tok)
            manifest_lines.append("  selection reason: %s" % label)
            manifest_lines.append("  split: navtest")
            manifest_lines.append("  cmd_tokens_film scores: %s" % json.dumps(scene.scores))
            manifest_lines.append("  cmd_tokens_film pdms: %.4f" % scene.pdms)
            manifest_lines.append("  mpp (1/bev_bounds.scale): %.5f m/px  (bev_bounds.scale=%.3f)" %
                                   (scene.mpp, scene.scale_px_per_m))
            manifest_lines.append("  captions: %s" %
                                   json.dumps([c.get("text") for c in scene.captions]))
            manifest_lines.append("  clip: %s  (%d bytes, %d frames @ %d fps = %.2fs, %dx%d)" %
                                   (out_path, size, total_frames, FPS, total_frames / FPS, W, H))
            for sp, rt, ph in stills:
                manifest_lines.append("  still: %s  (%s phase, real_t=%.2fs)" % (sp, ph, rt))
            manifest_lines.append("")
            n_ok += 1
        except Exception:
            log("!!! FAILED on %s: %s" % (tok, traceback.format_exc()))
            manifest_lines.append("token: %s  -- RENDER FAILED, see logs" % tok)
            manifest_lines.append("")

    manifest_path = os.path.join(OUT_ROOT, "MANIFEST.txt")
    with open(manifest_path, "w") as f:
        f.write("\n".join(manifest_lines))
    log("\nMANIFEST written to %s" % manifest_path)
    log("DONE: %d/%d scenes rendered successfully" % (n_ok, len(chosen)))


if __name__ == "__main__":
    main()
