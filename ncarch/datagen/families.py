"""Eight parametric part families and their analytic ground-truth geometry.

Every spec is in part-local coordinates (origin at the stock centre, Z0 = stock
top). The ground-truth depth function is used for evaluation only.
"""
from __future__ import annotations

import math

import numpy as np

DRILLS = [5.0, 6.0, 6.8, 8.0, 8.5, 10.0]
ENDMILLS = [6.0, 8.0, 10.0, 12.0, 16.0]
DRILL_TAN = math.tan(math.radians(59))

FAMILIES = ["bolt_plate", "pocket_housing", "slotted_bracket", "flange",
            "stepped_block", "tray", "keyway_bar", "boss"]


def _u(rng, a, b):
    return float(rng.uniform(a, b))


def _pick(rng, xs):
    return float(xs[rng.integers(len(xs))])


def _hole(x, y, d, depth):
    return dict(type="hole", x=x, y=y, d=d, depth=depth)


def _outline_rect(rng, W, H, p, T):
    if rng.random() < p:
        return dict(type="rect", w=W, h=H, r=_u(rng, 2, 8), depth=T + 0.5)
    return None


def bolt_plate(rng):
    W, H, T = _u(rng, 60, 140), _u(rng, 50, 110), _u(rng, 8, 16)
    d, e = _pick(rng, DRILLS), _u(rng, 8, 14)
    nx, ny = [(2, 2), (3, 2), (2, 3), (4, 2)][rng.integers(4)]
    xs = np.linspace(-W / 2 + e, W / 2 - e, nx)
    ys = np.linspace(-H / 2 + e, H / 2 - e, ny)
    feats = [_hole(float(x), float(y), d, T + 1) for x in xs for y in ys]
    return dict(W=W, H=H, T=T, outline=_outline_rect(rng, W, H, 0.6, T), features=feats)


def pocket_housing(rng):
    W, H, T = _u(rng, 70, 140), _u(rng, 60, 110), _u(rng, 20, 35)
    w, h = W * _u(rng, 0.5, 0.7), H * _u(rng, 0.5, 0.7)
    D = _pick(rng, [t for t in ENDMILLS if t < min(w, h) / 3])
    feats = [dict(type="rect_pocket", x=0.0, y=0.0, w=w, h=h, depth=_u(rng, 8, 18), tool_d=D)]
    d = _pick(rng, DRILLS[:3])
    e = min((W - w) / 4, (H - h) / 4)
    if e > d:
        for sx in (-1, 1):
            for sy in (-1, 1):
                feats.append(_hole(sx * (W / 2 - e), sy * (H / 2 - e), d, T + 1))
    return dict(W=W, H=H, T=T, outline=_outline_rect(rng, W, H, 0.5, T), features=feats)


def slotted_bracket(rng):
    W, H, T = _u(rng, 80, 150), _u(rng, 40, 80), _u(rng, 8, 14)
    n = int(rng.integers(2, 4))
    D = _pick(rng, [6.0, 8.0, 10.0])
    L = W * _u(rng, 0.3, 0.5)
    ys = np.linspace(-H / 2 + H / (n + 1), H / 2 - H / (n + 1), n)
    feats = [dict(type="slot", x0=-L / 2, y0=float(y), x1=L / 2, y1=float(y), w=D, depth=T + 0.5, tool_d=D)
             for y in ys]
    d = _pick(rng, DRILLS)
    for sx in (-1, 1):
        feats.append(_hole(sx * (W / 2 - (W / 2 - L / 2) / 2), 0.0, d, T + 1))
    return dict(W=W, H=H, T=T, outline=_outline_rect(rng, W, H, 0.5, T), features=feats)


def flange(rng):
    Do, T = _u(rng, 70, 130), _u(rng, 10, 20)
    bore = Do * _u(rng, 0.25, 0.4)
    D = _pick(rng, [t for t in ENDMILLS if t < bore / 2.5])
    feats = [dict(type="circ_pocket", x=0.0, y=0.0, d=bore, depth=T + 0.5, tool_d=D)]
    n, d = int(_pick(rng, [4, 5, 6, 8])), _pick(rng, [5.0, 6.0, 6.8, 8.5])
    pcd = (bore + Do) / 2
    a0 = _u(rng, 0, math.pi / n)
    for k in range(n):
        a = a0 + 2 * math.pi * k / n
        feats.append(_hole(pcd / 2 * math.cos(a), pcd / 2 * math.sin(a), d, T + 1))
    return dict(W=Do, H=Do, T=T, outline=dict(type="circle", d=Do, depth=T + 0.5), features=feats)


def stepped_block(rng):
    W, H, T = _u(rng, 60, 120), _u(rng, 40, 90), _u(rng, 25, 45)
    n = int(rng.integers(2, 4))
    D = _pick(rng, [10.0, 12.0, 16.0])
    lengths = sorted([W * _u(rng, 0.15, 0.8) for _ in range(n)], reverse=True)
    depths = sorted([_u(rng, 4, T * 0.7) for _ in range(n)])
    feats = [dict(type="step", x_edge=-W / 2 + L, depth=dp, tool_d=D) for L, dp in zip(lengths, depths)]
    if rng.random() < 0.5:
        d = _pick(rng, DRILLS)
        xr = (-W / 2 + lengths[0] + W / 2) / 2
        feats += [_hole(xr, s * H / 4, d, T * 0.6) for s in (-1, 1)]
    return dict(W=W, H=H, T=T, outline=None, features=feats)


def tray(rng):
    W, H, T = _u(rng, 80, 150), _u(rng, 60, 110), _u(rng, 15, 25)
    nx, ny = [(2, 2), (3, 2), (2, 3), (3, 3), (4, 2)][rng.integers(5)]
    b, t = _u(rng, 6, 10), _u(rng, 4, 8)
    pw, ph = (W - 2 * b - (nx - 1) * t) / nx, (H - 2 * b - (ny - 1) * t) / ny
    D = _pick(rng, [m for m in ENDMILLS if m <= min(pw, ph) / 2.5] or [6.0])
    depth = _u(rng, 5, 12)
    feats = []
    for i in range(nx):
        for j in range(ny):
            feats.append(dict(type="rect_pocket", x=-W / 2 + b + pw / 2 + i * (pw + t),
                              y=-H / 2 + b + ph / 2 + j * (ph + t), w=pw, h=ph, depth=depth, tool_d=D))
    return dict(W=W, H=H, T=T, outline=_outline_rect(rng, W, H, 0.4, T), features=feats)


def keyway_bar(rng):
    L, W, T = _u(rng, 100, 160), _u(rng, 25, 45), _u(rng, 15, 30)
    D = _pick(rng, [m for m in [6.0, 8.0, 10.0, 12.0] if m < W / 2.5])
    ls = L * _u(rng, 0.3, 0.6)
    feats = [dict(type="slot", x0=-ls / 2, y0=0.0, x1=ls / 2, y1=0.0, w=D, depth=_u(rng, 3, 8), tool_d=D)]
    d = _pick(rng, [6.0, 6.8, 8.5])
    feats += [_hole(s * (L / 2 - 10), 0.0, d, T + 1) for s in (-1, 1)]
    return dict(W=L, H=W, T=T, outline=_outline_rect(rng, L, W, 0.5, T), features=feats)


def boss(rng):
    W, H, T = _u(rng, 70, 130), _u(rng, 60, 110), _u(rng, 20, 30)
    w, h = W * _u(rng, 0.6, 0.8), H * _u(rng, 0.6, 0.8)
    isl = min(w, h) * _u(rng, 0.3, 0.5)
    gap = (min(w, h) - isl) / 2
    D = _pick(rng, [m for m in [8.0, 10.0, 12.0] if m < gap / 1.5] or [6.0])
    island = dict(type="circle", d=isl) if rng.random() < 0.6 else dict(type="rect", w=isl, h=isl)
    feats = [dict(type="ring_pocket", x=0.0, y=0.0, w=w, h=h, island=island, depth=_u(rng, 6, 14), tool_d=D)]
    if rng.random() < 0.5:
        feats.append(_hole(0.0, 0.0, _pick(rng, [6.0, 8.5, 10.0]), T + 1))
    return dict(W=W, H=H, T=T, outline=_outline_rect(rng, W, H, 0.5, T), features=feats)


GENERATORS = dict(bolt_plate=bolt_plate, pocket_housing=pocket_housing, slotted_bracket=slotted_bracket,
                  flange=flange, stepped_block=stepped_block, tray=tray, keyway_bar=keyway_bar, boss=boss)


def make_spec(family, rng):
    spec = GENERATORS[family](rng)
    spec["family"] = family
    spec["face_depth"] = _u(rng, 0.5, 1.0) if rng.random() < 0.85 else 0.0
    # 2 mm of stock around the finished outline so a profile pass frees the part
    spec["stock_w"], spec["stock_h"] = spec["W"] + 4, spec["H"] + 4
    return spec


# ---------------------------------------------------------------- ground truth
def _rounded_rect(X, Y, cx, cy, w, h, r):
    r = min(r, w / 2, h / 2)
    qx, qy = np.abs(X - cx) - (w / 2 - r), np.abs(Y - cy) - (h / 2 - r)
    return np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) <= r


def _seg_dist(X, Y, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    t = np.clip(((X - x0) * dx + (Y - y0) * dy) / max(dx * dx + dy * dy, 1e-12), 0, 1)
    return np.hypot(X - (x0 + t * dx), Y - (y0 + t * dy))


def gt_depth(spec, X, Y, profile_tool_d=None):
    """Designed removed depth (>= 0) at local coordinates X, Y."""
    sw, sh = spec["stock_w"], spec["stock_h"]
    inside = (np.abs(X) <= sw / 2) & (np.abs(Y) <= sh / 2)
    D = np.where(inside, spec["face_depth"], 0.0)
    o = spec["outline"]
    if o is not None and profile_tool_d:
        Rt = profile_tool_d
        if o["type"] == "rect":
            part = _rounded_rect(X, Y, 0, 0, o["w"], o["h"], o["r"])
            ring = _rounded_rect(X, Y, 0, 0, o["w"] + 2 * Rt, o["h"] + 2 * Rt, o["r"] + Rt)
        else:
            rr = np.hypot(X, Y)
            part, ring = rr <= o["d"] / 2, rr <= o["d"] / 2 + Rt
        D = np.where(ring & ~part & inside, np.maximum(D, o["depth"]), D)
    for f in spec["features"]:
        t = f["type"]
        if t == "hole":
            r = np.hypot(X - f["x"], Y - f["y"])
            tip = f["depth"] + (f["d"] / 2) / DRILL_TAN
            cone = tip - r / DRILL_TAN
            D = np.where(r <= f["d"] / 2, np.maximum(D, cone), D)
        elif t == "rect_pocket":
            m = _rounded_rect(X, Y, f["x"], f["y"], f["w"], f["h"], f["tool_d"] / 2)
            D = np.where(m, np.maximum(D, f["depth"]), D)
        elif t == "circ_pocket":
            m = np.hypot(X - f["x"], Y - f["y"]) <= f["d"] / 2
            D = np.where(m, np.maximum(D, f["depth"]), D)
        elif t == "slot":
            m = _seg_dist(X, Y, f["x0"], f["y0"], f["x1"], f["y1"]) <= f["w"] / 2
            D = np.where(m, np.maximum(D, f["depth"]), D)
        elif t == "step":
            m = inside & (X <= f["x_edge"])
            D = np.where(m, np.maximum(D, f["depth"]), D)
        elif t == "ring_pocket":
            m = _rounded_rect(X, Y, f["x"], f["y"], f["w"], f["h"], f["tool_d"] / 2)
            isl = f["island"]
            if isl["type"] == "circle":
                keep = np.hypot(X - f["x"], Y - f["y"]) <= isl["d"] / 2
            else:
                keep = _rounded_rect(X, Y, f["x"], f["y"], isl["w"], isl["h"], 0.0)
            D = np.where(m & ~keep, np.maximum(D, f["depth"]), D)
    return D
