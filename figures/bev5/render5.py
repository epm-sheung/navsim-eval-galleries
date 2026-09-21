#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Five improved BEV renderings of NAVSIM scenes -> PNG (Pillow).

Fixes the two things that made the gallery BEV weak as a standalone figure:
  1. the gallery fits bev_bounds PER SCENE, so a slow scene zooms to ~16 m and the
     ego box fills the frame. Here every pixel coord is inverted back to METRES via
     bev_bounds and re-projected into an ego-centric window with a CLAMPED scale.
  2. drivable area was white-on-white. Here it is a filled region with a real edge.
"""
import json, os, sys, glob, math, collections
from PIL import Image, ImageDraw, ImageFont

SCENES = "/scratch/eddie96/eddie/navsim_pages/scenes"
OUT    = "/scratch/eddie96/eddie/navsim_pages/figures/bev5"
BEV_H  = 540.0                      # gallery panel height, needed for the y inversion
SS     = 3                          # supersample factor

# ---------------------------------------------------------------- palette
INK   = (26, 32, 39); INK2=(74,83,94); INK3=(120,130,142)
PAPER = (250, 250, 248)
ROAD  = (226, 230, 233); ROAD_E=(196,202,208)
EGO   = (31, 111, 107)
PRED  = (23, 92, 168)
HUMAN = (120, 128, 138)
CRIT  = (168, 50, 45); WARN=(176,106,18); GOOD=(47,125,79)
TYPEC = {"VEHICLE":(96,116,140), "PEDESTRIAN":(196,104,42),
         "TRAFFIC_CONE":(186,150,40), "GENERIC_OBJECT":(150,150,156)}
METHC = [(23,92,168),(168,50,45),(47,125,79),(176,106,18),(106,90,205),
         (20,140,150),(190,80,150),(110,110,118),(70,160,90),(200,140,60)]

def font(sz, bold=False):
    cands = ["/usr/share/fonts/dejavu-sans-fonts/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
             "/usr/share/fonts/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""),
             "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else "")]
    for c in cands:
        if os.path.exists(c):
            try: return ImageFont.truetype(c, sz)
            except Exception: pass
    for root,_,fs in os.walk("/usr/share/fonts"):
        for f in fs:
            if f.startswith("DejaVuSans") and f.endswith(".ttf"):
                try: return ImageFont.truetype(os.path.join(root,f), sz)
                except Exception: pass
    return ImageFont.load_default()

# ------------------------------------------------------- coordinate handling
def inv(b):
    """gallery pixel -> metric (x forward, y left). Inverse of the renderer's bev_to_px."""
    sc, ox, oy, xmn, ymn = b["scale"], b["ox"], b["oy"], b["xmin"], b["ymin"]
    def f(p):
        px, py = p[0], p[1]
        return ((px - ox)/sc + xmn, (BEV_H - py - oy)/sc + ymn)
    return f

class View(object):
    """ego-centric metric window -> canvas px, with a clamped scale."""
    def __init__(self, pts, W, H, minppm=11.0, maxppm=34.0, pad=5.0):
        xs=[p[0] for p in pts] or [0.0]; ys=[p[1] for p in pts] or [0.0]
        x0,x1=min(xs)-pad,max(xs)+pad; y0,y1=min(ys)-pad,max(ys)+pad
        x0=min(x0,-5.0); x1=max(x1,14.0); y0=min(y0,-7.0); y1=max(y1,7.0)
        s=min(W/max(x1-x0,1e-6), H/max(y1-y0,1e-6))
        s=max(minppm,min(maxppm,s))
        self.s=s; self.W=W; self.H=H
        self.cx=(x0+x1)/2.0; self.cy=(y0+y1)/2.0
        self.ppm=s
    def __call__(self, p):
        # x forward -> right, y left -> up
        return (self.W/2.0 + (p[0]-self.cx)*self.s,
                self.H/2.0 - (p[1]-self.cy)*self.s)

# ------------------------------------------------------------------ drawing
def poly(d, pts, fill=None, outline=None, w=1):
    if len(pts) >= 3: d.polygon(pts, fill=fill, outline=outline)
    if outline and w > 1 and len(pts) >= 2:
        d.line(list(pts)+[pts[0]], fill=outline, width=w, joint="curve")

def dashed(d, pts, fill, w, dash=14, gap=10):
    if len(pts) < 2: return
    rem=dash; on=True; cur=[pts[0]]
    for a,b in zip(pts[:-1], pts[1:]):
        seg=math.hypot(b[0]-a[0], b[1]-a[1]); t=0.0
        while t < seg:
            step=min(rem, seg-t); u0=t/seg; u1=(t+step)/seg
            p0=(a[0]+(b[0]-a[0])*u0, a[1]+(b[1]-a[1])*u0)
            p1=(a[0]+(b[0]-a[0])*u1, a[1]+(b[1]-a[1])*u1)
            if on: d.line([p0,p1], fill=fill, width=w)
            t+=step; rem-=step
            if rem<=1e-9: on=not on; rem=dash if on else gap
    return

def scalebar(d, view, W, H, f):
    for cand in (5,10,20,25,50):
        px=cand*view.ppm
        if px > W*0.14: break
    x0,y0=int(W*0.035), int(H-H*0.055) if not hasattr(scalebar,"_lift") else int(H-H*0.055)-scalebar._lift
    d.line([(x0,y0),(x0+px,y0)], fill=INK2, width=3*SS)
    for xx in (x0, x0+px):
        d.line([(xx,y0-5*SS),(xx,y0+5*SS)], fill=INK2, width=3*SS)
    d.text((x0, y0-20*SS), "%d m" % cand, font=f, fill=INK2)

def ego_poly(view, L=4.6, Wd=2.0, at=(0.0,0.0), head=0.0):
    c,s=math.cos(head), math.sin(head)
    box=[(-L*0.35,-Wd/2),(L*0.65,-Wd/2),(L*0.65,Wd/2),(-L*0.35,Wd/2)]
    return [view((at[0]+p[0]*c-p[1]*s, at[1]+p[0]*s+p[1]*c)) for p in box]

# ------------------------------------------------------------------- loading
def load(tok):
    ev=json.load(open(os.path.join(SCENES,"events","%s.json"%tok)))
    tj=json.load(open(os.path.join(SCENES,"traj","%s.json"%tok)))
    return ev, tj, inv(tj["bev_bounds"])

def m_agents(ev, T):
    """-> list of (type, [box_metric or None per time idx]) and time_idcs"""
    ag=ev.get("agents",{}); out=[]
    for o in ag.get("objects",[]):
        boxes=[]
        for bx in o.get("bev",[]):
            if not bx: boxes.append(None); continue
            try: boxes.append([T(p) for p in bx])
            except Exception: boxes.append(None)
        out.append((o.get("type","GENERIC_OBJECT"), boxes))
    return out, ag.get("time_idcs",[])

def m_drivable(ev, T):
    out=[]
    for pg in ev.get("drivable_area",{}).get("bev",[]):
        sh=pg.get("shell") or []
        if len(sh)>=3:
            out.append(([T(p) for p in sh],
                        [[T(p) for p in h] for h in (pg.get("holes") or []) if len(h)>=3]))
    return out

def m_path(tj, meth, T, frame=0):
    m=tj.get("methods",{}).get(meth)
    if not m: return []
    bev=m.get("bev") or []
    if not bev: return []
    fr=bev[min(frame,len(bev)-1)] or []
    return [T(p) for p in fr if p]

def base_canvas(W,H):
    im=Image.new("RGB",(W*SS,H*SS),PAPER); return im, ImageDraw.Draw(im,"RGBA")

def finish(im, W, H, path):
    im=im.resize((W,H), Image.LANCZOS); im.save(path, "PNG", optimize=True)
    return os.path.getsize(path)

def draw_map(d, view, driv, road=ROAD, edge=ROAD_E, ew=2):
    for shell,holes in driv:
        poly(d, shell, fill=road, outline=edge, w=ew*SS)
        for h in holes: poly(d, h, fill=PAPER, outline=edge, w=1*SS)

def draw_agents(d, boxes_at, alpha=255, label_types=True):
    for typ, bx in boxes_at:
        if not bx: continue
        c=TYPEC.get(typ,TYPEC["GENERIC_OBJECT"])
        poly(d, bx, fill=c+(alpha,), outline=tuple(int(v*0.65) for v in c)+(alpha,), w=1*SS)

def header(d, W, title, sub, fB, fS, y=0):
    d.text((int(W*0.030*SS), y+int(10*SS)), title, font=fB, fill=INK)
    d.text((int(W*0.030*SS), y+int(34*SS)), sub,   font=fS, fill=INK2)

def gate_strip(d, W, H, scores, fS, fB):
    keys=[("nc","NC"),("dac","DAC"),("ttc","TTC"),("c","C"),("ddc","DDC")]
    x=int(W*0.030*SS); y=int((H-34)*SS)
    for k,lab in keys:
        v=scores.get(k)
        if v is None: continue
        ok = v >= 0.999
        col = GOOD if ok else CRIT
        txt="%s %.2f"%(lab,v)
        w=int(d.textlength(txt,font=fB))+int(16*SS)
        d.rounded_rectangle([x,y,x+w,y+int(24*SS)], radius=4*SS,
                            fill=(col[0],col[1],col[2],28), outline=col, width=2)
        d.text((x+int(8*SS), y+int(4*SS)), txt, font=fB, fill=col)
        x+=w+int(9*SS)

def legend(d, W, H, items, fS, x=None, y=None):
    x = x if x is not None else int(W*0.66*SS); y = y if y is not None else int(H*0.035*SS)
    for lab,col,kind in items:
        if kind=="dash": dashed(d,[(x,y+int(7*SS)),(x+int(26*SS),y+int(7*SS))],col,3*SS,7*SS,5*SS)
        elif kind=="line": d.line([(x,y+int(7*SS)),(x+int(26*SS),y+int(7*SS))],fill=col,width=4*SS)
        else: d.rectangle([x,y+int(2*SS),x+int(14*SS),y+int(13*SS)],fill=col,outline=None)
        d.text((x+int(32*SS), y), lab, font=fS, fill=INK2)
        y+=int(19*SS)

W,H = 1400, 620
fT=font(21*SS,True); fB=font(13*SS,True); fS=font(12*SS); fXS=font(11*SS)

def collect_pts(driv, agents_t0, paths):
    """Fit the window to the DRIVING, not to the map. The drivable polygon spans whole
    intersections and fitting to it zooms out until the trajectory is a few pixels long.
    Agents are included only if they are near the driven corridor."""
    pts=[(0.0,0.0),(4.0,0.0)]
    for p in paths: pts+=list(p)
    if len(pts)<=2:
        for sh,_ in driv: pts+=sh[:40]
    xs=[q[0] for q in pts]; ys=[q[1] for q in pts]
    x0,x1,y0,y1=min(xs),max(xs),min(ys),max(ys)
    for _,bx in agents_t0:
        if not bx: continue
        cx=sum(q[0] for q in bx)/4.0; cy=sum(q[1] for q in bx)/4.0
        if x0-14 <= cx <= x1+14 and y0-11 <= cy <= y1+11: pts+=bx
    return pts

# ---------------------------------------------------------------- FIGURE 1
def fig_clean(tok, out):
    ev,tj,T=load(tok); driv=m_drivable(ev,T); ags,tidx=m_agents(ev,T)
    ag0=[(t,(b[0] if b else None)) for t,b in ags]
    pred=m_path(tj,"cmd_tokens_film",T); hum=m_path(tj,"human",T)
    view=View(collect_pts(driv,ag0,[pred,hum]),W*SS,int((H-96)*SS))
    im,d=base_canvas(W,H)
    off=int(64*SS)
    def V(p): q=view(p); return (q[0], q[1]+off)
    for sh,ho in driv:
        poly(d,[V(p) for p in sh],fill=ROAD,outline=ROAD_E,w=2*SS)
        for h in ho: poly(d,[V(p) for p in h],fill=PAPER,outline=ROAD_E,w=1*SS)
    for t,b in ag0:
        if not b: continue
        c=TYPEC.get(t,TYPEC["GENERIC_OBJECT"])
        poly(d,[V(p) for p in b],fill=c,outline=tuple(int(v*0.6) for v in c),w=1*SS)
    if pred:
        pp=[V(p) for p in pred]
        d.line(pp,fill=(255,255,255),width=9*SS,joint="curve")   # halo, so it reads over road
        d.line(pp,fill=PRED,width=5*SS,joint="curve")
        for q in pp: d.ellipse([q[0]-3.5*SS,q[1]-3.5*SS,q[0]+3.5*SS,q[1]+3.5*SS],fill=PRED)
    if hum: dashed(d,[V(p) for p in hum],(70,78,88),4*SS,13*SS,9*SS)
    eb=[V(p) for p in [(-1.6,-1.0),(3.0,-1.0),(3.0,1.0),(-1.6,1.0)]]
    poly(d,eb,fill=EGO,outline=(15,70,66),w=2*SS)
    s=tj.get("scores",{}).get("cmd_tokens_film",{})
    header(d,W,"%s"%tok,"navtest · cmd_tokens_film · PDMS %.3f · %d agents"
           %(s.get("pdms",float("nan")),len(ags)),fT,fS)
    legend(d,W,H,[("predicted (ours)",PRED,"line"),("human log",HUMAN,"dash"),
                  ("ego",EGO,"box"),("vehicle",TYPEC["VEHICLE"],"box"),
                  ("pedestrian",TYPEC["PEDESTRIAN"],"box")],fS,
           x=int(W*0.815*SS),y=int(78*SS))
    scalebar(d,view,W*SS,H*SS,fS); gate_strip(d,W,H,s,fS,fB)
    return finish(im,W,H,out)

# ---------------------------------------------------------------- FIGURE 2
def fig_motion(tok, out):
    ev,tj,T=load(tok); driv=m_drivable(ev,T); ags,tidx=m_agents(ev,T)
    pred=m_path(tj,"cmd_tokens_film",T); hum=m_path(tj,"human",T)
    allb=[(t,b[0] if b else None) for t,b in ags]
    view=View(collect_pts(driv,allb,[pred,hum]),W*SS,int((H-96)*SS))
    im,d=base_canvas(W,H); off=int(64*SS)
    def V(p): q=view(p); return (q[0], q[1]+off)
    for sh,ho in driv:
        poly(d,[V(p) for p in sh],fill=(238,240,242),outline=(216,220,224),w=1*SS)
        for h in ho: poly(d,[V(p) for p in h],fill=PAPER,outline=(216,220,224),w=1*SS)
    n=max(1,len(tidx))
    for t,boxes in ags:
        c=TYPEC.get(t,TYPEC["GENERIC_OBJECT"])
        for i,b in enumerate(boxes):
            if not b: continue
            a=int(38+200*(i/float(max(1,n-1))))
            poly(d,[V(p) for p in b],fill=c+(a,),outline=None)
        last=[b for b in boxes if b]
        if last: poly(d,[V(p) for p in last[-1]],fill=None,
                      outline=tuple(int(v*0.6) for v in c),w=2*SS)
    if hum: dashed(d,[V(p) for p in hum],(160,166,174),3*SS,11*SS,8*SS)
    if pred:
        pp=[V(p) for p in pred]
        for i in range(len(pp)-1):
            u=i/float(max(1,len(pp)-2))
            col=(int(18+200*u), int(92-30*u), int(168-90*u))
            d.line([pp[i],pp[i+1]],fill=col,width=6*SS)
    eb=[V(p) for p in [(-1.6,-1.0),(3.0,-1.0),(3.0,1.0),(-1.6,1.0)]]
    poly(d,eb,fill=EGO,outline=(15,70,66),w=2*SS)
    s=tj.get("scores",{}).get("cmd_tokens_film",{})
    dt=(tidx[-1]-tidx[0])*0.1 if len(tidx)>1 else 4.0
    header(d,W,"%s  ·  motion over %.1f s"%(tok,dt),
           "agents ghosted at %d timesteps (faint = earliest) · ego path coloured by time"%len(tidx),
           fT,fS)
    x0=int(W*0.815*SS); y0=int(78*SS)
    d.text((x0,y0-int(18*SS)),"ego path, t = 0 → %.1f s"%dt,font=fS,fill=INK2)
    for i in range(120):
        u=i/119.0; col=(int(18+200*u),int(92-30*u),int(168-90*u))
        d.line([(x0+i*SS,y0),(x0+i*SS,y0+int(11*SS))],fill=col,width=SS+1)
    legend(d,W,H,[("vehicle",TYPEC["VEHICLE"],"box"),("pedestrian",TYPEC["PEDESTRIAN"],"box"),
                  ("cone / generic",TYPEC["TRAFFIC_CONE"],"box"),("human log",HUMAN,"dash")],
           fS,x=x0,y=y0+int(24*SS))
    scalebar(d,view,W*SS,H*SS,fS); gate_strip(d,W,H,s,fS,fB)
    return finish(im,W,H,out)

# ---------------------------------------------------------------- FIGURE 3
def pt_in_poly(p, poly_pts):
    x,y=p; n=len(poly_pts); inside=False; j=n-1
    for i in range(n):
        xi,yi=poly_pts[i]; xj,yj=poly_pts[j]
        if ((yi>y)!=(yj>y)) and (x < (xj-xi)*(y-yi)/((yj-yi) or 1e-12)+xi): inside=not inside
        j=i
    return inside

def fig_failure(tok, out):
    ev,tj,T=load(tok); driv=m_drivable(ev,T); ags,tidx=m_agents(ev,T)
    meths=ev.get("methods",{})
    pick=None
    order=["cmd_tokens_film","variant1_patch_tokens_film","sae_armAp_control","transfuser"]
    order=[m for m in order if m in meths] + \
          [m for m in meths if m not in order and m!="constant_velocity"]
    # prefer a method that both FAILS a gate and explains it with a caption
    for cand in order:
        m=meths.get(cand)
        if not m: continue
        fails=any((v is not None and v<0.999) for v in m.get("scores",{}).values())
        if fails and (m.get("captions") or []): pick=cand; break
    if pick is None:
        for cand in order:
            m=meths.get(cand)
            if m and any((v is not None and v<0.999) for v in m.get("scores",{}).values()):
                pick=cand; break
    if pick is None: pick=("cmd_tokens_film" if "cmd_tokens_film" in meths
                           else (list(meths)[0] if meths else "cmd_tokens_film"))
    mm=meths.get(pick,{}); sc=mm.get("scores",{})
    caps=mm.get("captions",[]) or []
    failed=[k for k,v in sc.items() if v is not None and v<0.999]
    pred=m_path(tj,pick,T); hum=m_path(tj,"human",T)
    ag0=[(t,(b[0] if b else None)) for t,b in ags]
    view=View(collect_pts(driv,ag0,[pred,hum]),W*SS,int((H-150)*SS))
    im,d=base_canvas(W,H); off=int(64*SS)
    def V(p): q=view(p); return (q[0], q[1]+off)
    for sh,ho in driv:
        poly(d,[V(p) for p in sh],fill=ROAD,outline=ROAD_E,w=2*SS)
        for h in ho: poly(d,[V(p) for p in h],fill=PAPER,outline=ROAD_E,w=1*SS)
    for t,b in ag0:
        if not b: continue
        c=TYPEC.get(t,TYPEC["GENERIC_OBJECT"])
        poly(d,[V(p) for p in b],fill=c,outline=tuple(int(v*0.6) for v in c),w=1*SS)
    inferred=False
    # DAC: mark path samples outside every drivable shell
    if "dac" in failed and driv and pred:
        shells=[sh for sh,_ in driv]
        bad=[p for p in pred if not any(pt_in_poly(p,s) for s in shells)]
        for p in bad:
            q=V(p); r=9*SS
            d.ellipse([q[0]-r,q[1]-r,q[0]+r,q[1]+r],outline=CRIT,width=3*SS)
    # TTC / NC: highlight the agent nearest the path (INFERRED)
    if ("ttc" in failed or "nc" in failed) and pred:
        best=None
        for t,boxes in ags:
            for i,b in enumerate(boxes):
                if not b: continue
                cxy=(sum(p[0] for p in b)/4.0, sum(p[1] for p in b)/4.0)
                for p in pred:
                    dd=math.hypot(cxy[0]-p[0], cxy[1]-p[1])
                    if best is None or dd<best[0]: best=(dd,b,t)
        if best:
            inferred=True
            bb=[V(p) for p in best[1]]
            poly(d,bb,fill=None,outline=CRIT,w=4*SS)
            cx=sum(q[0] for q in bb)/4.0; cy=sum(q[1] for q in bb)/4.0
            r=26*SS
            d.ellipse([cx-r,cy-r,cx+r,cy+r],outline=CRIT,width=2*SS)
            lab="nearest box to path (inferred)"
            lw=d.textlength(lab,font=fXS); lx=cx-lw/2.0; ly=cy-r-int(20*SS)
            d.rectangle([lx-4*SS,ly-2*SS,lx+lw+4*SS,ly+int(14*SS)],fill=(255,255,255,235))
            d.text((lx,ly),lab,font=fXS,fill=CRIT)
    if pred:
        pp=[V(p) for p in pred]
        d.line(pp,fill=(255,255,255),width=9*SS,joint="curve")
        d.line(pp,fill=CRIT if failed else PRED,width=5*SS,joint="curve")
    if hum: dashed(d,[V(p) for p in hum],(70,78,88),4*SS,13*SS,9*SS)
    poly(d,[V(p) for p in [(-1.6,-1.0),(3.0,-1.0),(3.0,1.0),(-1.6,1.0)]],
         fill=EGO,outline=(15,70,66),w=2*SS)
    s=tj.get("scores",{}).get(pick,{})
    header(d,W,"%s  ·  %s"%(tok, (", ".join(k.upper() for k in failed) or "no gate failure")),
           "method: %s · PDMS %.3f"%(pick, s.get("pdms",float("nan"))),fT,fS)
    # caption band
    band_y=int((H-86)*SS)
    d.rectangle([0,band_y,W*SS,int((H-40)*SS)],fill=(246,230,229))
    txt = caps[0]["text"] if caps else "no caption recorded for this scene"
    words=txt.split(); lines=[]; cur=""
    for w_ in words:
        t2=(cur+" "+w_).strip()
        if d.textlength(t2,font=fS) > (W-70)*SS: lines.append(cur); cur=w_
        else: cur=t2
    lines.append(cur)
    for i,ln in enumerate(lines[:2]):
        d.text((int(W*0.030*SS), band_y+int((6+15*i)*SS)), ln, font=fS, fill=(120,38,34))
    if inferred:
        d.text((int(W*0.030*SS), band_y+int(38*SS)),
               "agent highlight is INFERRED (nearest box to the path) — the data does not name the implicated agent",
               font=fXS, fill=(150,60,56))
    scalebar._lift=int(112*SS); scalebar(d,view,W*SS,H*SS,fS); del scalebar._lift
    gate_strip(d,W,H,sc,fS,fB)
    return finish(im,W,H,out)

# ---------------------------------------------------------------- FIGURE 4
def fig_methods(tok, out):
    ev,tj,T=load(tok); driv=m_drivable(ev,T); ags,tidx=m_agents(ev,T)
    sc=tj.get("scores",{})
    names=[m for m in tj.get("methods",{}) if m!="human"]
    names=sorted(names,key=lambda m:-(sc.get(m,{}).get("pdms")
        if sc.get(m,{}).get("pdms") is not None else -1))
    paths={m:m_path(tj,m,T) for m in names}; hum=m_path(tj,"human",T)
    ag0=[(t,(b[0] if b else None)) for t,b in ags]
    view=View(collect_pts(driv,ag0,list(paths.values())+[hum]),int(W*0.74*SS),int((H-96)*SS))
    im,d=base_canvas(W,H); off=int(64*SS)
    def V(p): q=view(p); return (q[0], q[1]+off)
    for sh,ho in driv:
        poly(d,[V(p) for p in sh],fill=(240,242,244),outline=(220,224,228),w=1*SS)
        for h in ho: poly(d,[V(p) for p in h],fill=PAPER,outline=(220,224,228),w=1*SS)
    for t,b in ag0:
        if not b: continue
        poly(d,[V(p) for p in b],fill=(206,212,220),outline=(180,188,198),w=1*SS)
    if hum: dashed(d,[V(p) for p in hum],(60,66,74),5*SS,14*SS,9*SS)
    for i,m in enumerate(names):
        p=paths.get(m) or []
        if len(p)<2: continue
        d.line([V(q) for q in p],fill=METHC[i%len(METHC)],width=4*SS,joint="curve")
    poly(d,[V(p) for p in [(-1.6,-1.0),(3.0,-1.0),(3.0,1.0),(-1.6,1.0)]],
         fill=EGO,outline=(15,70,66),w=2*SS)
    sp=[sc.get(m,{}).get("pdms") for m in names if sc.get(m,{}).get("pdms") is not None]
    header(d,W,"%s  ·  %d methods, PDMS spread %.3f"%(tok,len(names),
           (max(sp)-min(sp)) if sp else 0.0),
           "same scene, every method's trajectory · human shown dashed",fT,fS)
    x0=int(W*0.755*SS); y=int(78*SS)
    d.text((x0,y-int(20*SS)),"PDMS",font=fB,fill=INK3); y+=int(4*SS)
    d.line([(x0,y+int(7*SS)),(x0+int(24*SS),y+int(7*SS))],fill=(60,66,74),width=4*SS)
    def pd(m):
        v=sc.get(m,{}).get("pdms")
        return "  \u2014  " if v is None else "%.3f"%v   # 0.0 is a real score, not missing
    d.text((x0+int(30*SS),y),"human  %s"%pd("human"),font=fS,fill=INK2); y+=int(19*SS)
    for i,m in enumerate(names):
        d.line([(x0,y+int(7*SS)),(x0+int(24*SS),y+int(7*SS))],fill=METHC[i%len(METHC)],width=4*SS)
        nm=m if len(m)<=22 else m[:21]+"…"
        d.text((x0+int(30*SS),y),"%s  %s"%(nm, pd(m)),font=fXS,fill=INK2); y+=int(18*SS)
    scalebar(d,view,int(W*0.74*SS),H*SS,fS)
    return finish(im,W,H,out)

# ---------------------------------------------------------------- FIGURE 5
def fig_density(out, limit=None):
    """Aggregate trajectory prior over navtest, in METRES (each scene inverted via its
    own bev_bounds), so this does not assume a shared pixel geometry."""
    files=sorted(glob.glob(os.path.join(SCENES,"traj","*.json")))
    if limit: files=files[:limit]
    GW,GH=680,360; XR=(-3.0,55.0); YR=(-15.5,15.5)
    def cell(p):
        gx=int((p[0]-XR[0])/(XR[1]-XR[0])*GW); gy=int((p[1]-YR[0])/(YR[1]-YR[0])*GH)
        return (gx,gy) if 0<=gx<GW and 0<=gy<GH else None
    acc=[[0]*GW for _ in range(GH)]; accH=[[0]*GW for _ in range(GH)]
    nsc=0; nskip=0
    for fp in files:
        try: tj=json.load(open(fp))
        except Exception: nskip+=1; continue
        b=tj.get("bev_bounds")
        if not b: nskip+=1; continue
        T=inv(b); nsc+=1
        for meth,grid in (("cmd_tokens_film",acc),("human",accH)):
            pts=m_path(tj,meth,T)
            for i in range(len(pts)-1):
                a,c2=pts[i],pts[i+1]
                for k in range(17):
                    u=k/16.0; p=(a[0]+(c2[0]-a[0])*u, a[1]+(c2[1]-a[1])*u)
                    cc=cell(p)
                    if cc: grid[cc[1]][cc[0]]+=1
    def blur(g):
        out=[[0.0]*GW for _ in range(GH)]
        for y in range(GH):
            g0=g[y-1] if y>0 else None; g1=g[y]; g2=g[y+1] if y<GH-1 else None
            for x in range(GW):
                t=0.0
                for gg,wy in ((g0,0.6),(g1,1.0),(g2,0.6)):
                    if gg is None: continue
                    t+=wy*(gg[x]+(gg[x-1] if x>0 else 0)*0.6+(gg[x+1] if x<GW-1 else 0)*0.6)
                out[y][x]=t
        return out
    acc=blur(acc); accH=blur(accH)
    mx=max(1,max(max(r) for r in acc))
    im=Image.new("RGB",(GW,GH),PAPER); px=im.load()
    for y in range(GH):
        for x in range(GW):
            v=acc[y][x]
            if v<=0.02: continue
            u=math.log1p(v)/math.log1p(mx)
            px[x,y]=(int(250-227*u), int(250-158*u), int(248-80*u))
    im=im.resize((W, int(W*GH/float(GW))), Image.LANCZOS)
    HH=im.size[1]+130
    canvas=Image.new("RGB",(W,HH),PAPER); canvas.paste(im,(0,96))
    d=ImageDraw.Draw(canvas,"RGBA")
    mxH=max(1,max(max(r) for r in accH))
    sx=W/float(GW); sy=im.size[1]/float(GH)
    for y in range(GH):
        for x in range(GW):
            if accH[y][x] <= 0.02: continue
            u=math.log1p(accH[y][x])/math.log1p(mxH)
            if u < 0.42: continue
            d.rectangle([x*sx,96+y*sy,(x+1)*sx,96+(y+1)*sy],fill=(38,118,72,int(30+120*u)))
    f2=font(19,True); f3=font(12); f4=font(11)
    d.text((22,14),"Learned trajectory prior over navtest",font=f2,fill=INK)
    d.text((22,40),"%d scenes · cmd_tokens_film waypoint density (log-scaled, blue) with the "
                   "human log distribution overlaid (green)"%nsc,font=f3,fill=INK2)
    d.text((22,58),"ego-centric metres, x forward → right, y left ↑ · each scene inverted "
                   "from its own bev_bounds, so this is metric, not pixel-space",font=f4,fill=INK3)
    y0=96+im.size[1]
    for mx_m in (0,10,20,30,40,50):
        xx=(mx_m-XR[0])/(XR[1]-XR[0])*W
        d.line([(xx,y0),(xx,y0+6)],fill=INK3,width=1)
        d.text((xx-8,y0+8),"%dm"%mx_m,font=f4,fill=INK3)
    canvas.save(out,"PNG",optimize=True)
    return os.path.getsize(out), nsc, nskip

# -------------------------------------------------------------------- main
def pick_scenes():
    clean=[]; ttc=[]; dac=[]; low=[]; disagree=[]
    for fp in sorted(glob.glob(os.path.join(SCENES,"events","*.json"))):
        tok=os.path.basename(fp)[:-5]
        try: ev=json.load(open(fp))
        except Exception: continue
        if ev.get("split")!="navtest": continue
        tp=os.path.join(SCENES,"traj","%s.json"%tok)
        if not os.path.exists(tp): continue
        try: pdms=json.load(open(tp)).get("scores",{}).get("cmd_tokens_film",{}).get("pdms")
        except Exception: continue
        if pdms is None: continue
        kinds=set()
        for mname,m in ev.get("methods",{}).items():
            if mname not in ("cmd_tokens_film","variant1_patch_tokens_film","sae_armAp_control","transfuser"): continue
            sc_=m.get("scores",{}) or {}
            for c in (m.get("captions") or []):
                k=c.get("kind")
                v=sc_.get(k)
                if v is not None and v<0.999: kinds.add(k)
        span=0.0
        try:
            tjj=json.load(open(tp)); Ti=inv(tjj["bev_bounds"])
            hp=m_path(tjj,"human",Ti)
            if len(hp)>=2: span=math.hypot(hp[-1][0]-hp[0][0], hp[-1][1]-hp[0][1])
        except Exception: pass
        if not ev.get("any_failure") and pdms>=0.95 and span>=18.0: clean.append((tok,pdms,span))
        if "ttc" in kinds and span>=12.0: ttc.append((tok,pdms,span))
        if "dac" in kinds and span>=12.0: dac.append((tok,pdms,span))
        low.append((tok,pdms,span))
        try:
            allsc=[v.get("pdms") for v in json.load(open(tp)).get("scores",{}).values()
                   if v.get("pdms") is not None]
            if len(allsc)>=6 and span>=15.0:
                disagree.append((tok, max(allsc)-min(allsc), span))
        except Exception: pass
    low=[r for r in low if r[2]>=12.0] or low
    low.sort(key=lambda r:r[1])
    clean.sort(key=lambda r:-r[2]); ttc.sort(key=lambda r:-r[2]); dac.sort(key=lambda r:-r[2])
    out={}
    out["clean"]=clean[0][0] if clean else low[-1][0]
    out["ttc"]=ttc[0][0] if ttc else low[0][0]
    out["dac"]=dac[0][0] if dac else low[0][0]
    disagree.sort(key=lambda r:-r[1])
    out["disagree"]=disagree[0][0] if disagree else low[0][0]
    out["disagree_spread"]=round(disagree[0][1],3) if disagree else 0.0
    out["low"]=low[0][0]
    return out, dict(nclean=len(clean),nttc=len(ttc),ndac=len(dac),ntot=len(low),span_clean=(clean[0][2] if clean else 0))

if __name__=="__main__":
    os.makedirs(OUT,exist_ok=True)
    sel,stats=pick_scenes()
    print("selection:",sel,stats); sys.stdout.flush()
    man=[]
    a=fig_clean(sel["clean"], os.path.join(OUT,"1_clean.png"));      man.append(("1_clean.png",sel["clean"],a))
    print("1 ok",a); sys.stdout.flush()
    b=fig_motion(sel["clean"], os.path.join(OUT,"2_motion.png"));    man.append(("2_motion.png",sel["clean"],b))
    print("2 ok",b); sys.stdout.flush()
    c=fig_failure(sel["ttc"], os.path.join(OUT,"3_failure.png"));    man.append(("3_failure.png",sel["ttc"],c))
    print("3 ok",c); sys.stdout.flush()
    e=fig_methods(sel["disagree"], os.path.join(OUT,"4_methods.png")); man.append(("4_methods.png",sel["disagree"],e))
    print("4 ok",e); sys.stdout.flush()
    g,nsc,nskip=fig_density(os.path.join(OUT,"5_density.png"));      man.append(("5_density.png","navtest agg n=%d"%nsc,g))
    print("5 ok",g,"scenes",nsc,"skipped",nskip); sys.stdout.flush()
    with open(os.path.join(OUT,"MANIFEST.txt"),"w") as fh:
        for n,t,s in man: fh.write("%-16s  %-40s  %d bytes\n"%(n,t,s))
    print("DONE")
