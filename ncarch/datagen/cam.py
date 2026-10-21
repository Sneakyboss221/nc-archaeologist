"""Mini CAM: turns a part spec into tool-centre paths (operations).

Moves (part-local coordinates, mm):
  ("rapid", x, y, z) | ("feed", x, y, z) | ("arc", x, y, z, cx, cy, cw)
  ("drill", x, y, z_bottom, r_plane, peck)
"""
from __future__ import annotations

import math

import numpy as np

SAFE, RETRACT = 5.0, 2.0


class Path:
    def __init__(self):
        self.moves = []
        self.pos = None

    def rapid(self, x, y, z):
        self.moves.append(("rapid", x, y, z))
        self.pos = (x, y, z)

    def feed(self, x, y, z):
        self.moves.append(("feed", x, y, z))
        self.pos = (x, y, z)

    def arc(self, x, y, z, cx, cy, cw):
        self.moves.append(("arc", x, y, z, cx, cy, cw))
        self.pos = (x, y, z)

    def enter(self, x, y, z):
        """Retract, travel, and plunge to (x, y, z)."""
        if self.pos is None or self.pos[2] < SAFE:
            if self.pos is not None:
                self.rapid(self.pos[0], self.pos[1], SAFE)
        self.rapid(x, y, SAFE)
        self.rapid(x, y, RETRACT)
        self.feed(x, y, z)

    def lift(self):
        if self.pos is not None:
            self.rapid(self.pos[0], self.pos[1], SAFE)


def zlevels(depth, stepdown):
    n = max(1, int(math.ceil(depth / stepdown - 1e-9)))
    return [-depth * (i + 1) / n for i in range(n)]


def _intervals(allowed, y, xmin, xmax, step=0.05):
    xs = np.arange(xmin, xmax + step / 2, step)
    ok = allowed(xs, np.full_like(xs, y))
    out, start = [], None
    for x, a in zip(xs, ok):
        if a and start is None:
            start = x
        if not a and start is not None:
            out.append((start, prev))
            start = None
        prev = x
    if start is not None:
        out.append((start, xs[-1]))
    return [iv for iv in out if iv[1] - iv[0] > 0.05]


def _link_ok(allowed, p, q, n=12):
    xs = np.linspace(p[0], q[0], n)
    ys = np.linspace(p[1], q[1], n)
    return bool(allowed(xs, ys).all())


def zigzag(path, allowed, bbox, stepover, z, rotate=False):
    """Raster-fill the tool-centre region `allowed` at height z."""
    xmin, xmax, ymin, ymax = bbox
    if rotate:  # raster along Y instead of X
        def allowed_r(a, b):
            return allowed(b, a)
        xmin, xmax, ymin, ymax = ymin, ymax, xmin, xmax
        region = allowed_r
    else:
        region = allowed
    n = max(1, int(math.ceil((ymax - ymin) / stepover - 1e-9)))
    ys = np.linspace(ymin, ymax, n + 1)
    fwd = True
    first = True
    for y in ys:
        ivs = _intervals(region, float(y), xmin, xmax)
        if not fwd:
            ivs = [(b, a) for a, b in reversed(ivs)]
        for a, b in ivs:
            pa, pb = (a, float(y)), (b, float(y))
            if rotate:
                pa, pb = pa[::-1], pb[::-1]
            if first or path.pos is None or not _link_ok(allowed, path.pos[:2], pa) or abs(path.pos[2] - z) > 1e-9:
                path.enter(pa[0], pa[1], z)
                first = False
            else:
                path.feed(pa[0], pa[1], z)
            path.feed(pb[0], pb[1], z)
        fwd = not fwd


def rect_loop(path, cx, cy, a, b, z, climb=True):
    """Closed rectangular loop of half-sizes a, b (tool-centre)."""
    pts = [(cx - a, cy - b), (cx + a, cy - b), (cx + a, cy + b), (cx - a, cy + b)]
    if not climb:   # same start corner, opposite direction
        pts = pts[:1] + pts[:0:-1]
    for x, y in pts[1:] + pts[:1]:
        path.feed(x, y, z)


def circle_loop(path, cx, cy, r, z, cw):
    """Full circle starting/ending at (cx + r, cy), as two half arcs."""
    path.arc(cx - r, cy, z, cx, cy, cw)
    path.arc(cx + r, cy, z, cx, cy, cw)


def rounded_rect_loop(path, w, h, rc, z, cw):
    """Tool-centre loop around a rounded rectangle (half sizes w/2, h/2, radius rc)."""
    a, b = w / 2 - rc, h / 2 - rc
    # start at the middle of the bottom edge, go CCW (or CW)
    seq_ccw = [("feed", a, -b - rc), ("arc", a + rc, -b, a, -b),
               ("feed", a + rc, b), ("arc", a, b + rc, a, b),
               ("feed", -a, b + rc), ("arc", -a - rc, b, -a, b),
               ("feed", -a - rc, -b), ("arc", -a, -b - rc, -a, -b),
               ("feed", 0.0, -b - rc)]
    if not cw:
        for m in seq_ccw:
            if m[0] == "feed":
                path.feed(m[1], m[2], z)
            else:
                path.arc(m[1], m[2], z, m[3], m[4], False)
    else:
        mirrored = [("feed", -a, -b - rc), ("arc", -a - rc, -b, -a, -b),
                    ("feed", -a - rc, b), ("arc", -a, b + rc, -a, b),
                    ("feed", a, b + rc), ("arc", a + rc, b, a, b),
                    ("feed", a + rc, -b), ("arc", a, -b - rc, a, -b),
                    ("feed", 0.0, -b - rc)]
        for m in mirrored:
            if m[0] == "feed":
                path.feed(m[1], m[2], z)
            else:
                path.arc(m[1], m[2], z, m[3], m[4], True)


# ------------------------------------------------------------------ operations
def op_face(spec, tool_d, rng):
    R = tool_d / 2
    p = Path()
    sw, sh = spec["stock_w"], spec["stock_h"]
    so = tool_d * rng.uniform(0.6, 0.75)
    z = -spec["face_depth"]
    xmin, xmax = -sw / 2 - R - 2, sw / 2 + R + 2
    n = max(1, int(math.ceil((sh - 0.2 * tool_d) / so)))
    ys = np.linspace(-sh / 2 + 0.4 * R, sh / 2 - 0.4 * R, n + 1)
    p.enter(xmin, float(ys[0]), z)
    fwd = True
    for i, y in enumerate(ys):
        a, b = (xmin, xmax) if fwd else (xmax, xmin)
        if i:
            p.feed(a, float(y), z)
        p.feed(b, float(y), z)
        fwd = not fwd
    p.lift()
    return p


def op_rect_pocket(f, rng, strategy, stepover_ratio, stepdown, climb):
    R = f["tool_d"] / 2
    a, b = f["w"] / 2 - R, f["h"] / 2 - R
    so = f["tool_d"] * stepover_ratio
    p = Path()
    for z in zlevels(f["depth"], stepdown):
        if strategy == "zigzag":
            def allowed(x, y):
                return (np.abs(x - f["x"]) <= a + 1e-6) & (np.abs(y - f["y"]) <= b + 1e-6)
            zigzag(p, allowed, (f["x"] - a, f["x"] + a, f["y"] - b, f["y"] + b), so, z,
                   rotate=bool(rng.random() < 0.3))
            p.feed(f["x"] - a, f["y"] - b, z)
            rect_loop(p, f["x"], f["y"], a, b, z, climb)
        else:  # offset spiral, inside -> out
            loops = []
            k = 0
            while a - k * so > 0 and b - k * so > 0:
                loops.append((a - k * so, b - k * so))
                k += 1
            loops = loops[::-1]
            ai, bi = loops[0]
            c = max(ai - bi, 0.0)
            p.enter(f["x"] - c, f["y"], z)
            if c > 0:
                p.feed(f["x"] + c, f["y"], z)
            for la, lb in loops:
                p.feed(f["x"] - la, f["y"] - lb, z)
                rect_loop(p, f["x"], f["y"], la, lb, z, climb)
        p.lift()
    return p


def op_circ_pocket(f, rng, stepover_ratio, stepdown, climb):
    R = f["tool_d"] / 2
    rmax = f["d"] / 2 - R
    so = f["tool_d"] * stepover_ratio
    radii = list(np.arange(so, rmax, so)) + [rmax]
    p = Path()
    for z in zlevels(f["depth"], stepdown):
        p.enter(f["x"], f["y"], z)
        for r in radii:
            p.feed(f["x"] + r, f["y"], z)
            circle_loop(p, f["x"], f["y"], float(r), z, cw=not climb)
        p.lift()
    return p


def op_ring_pocket(f, rng, stepover_ratio, stepdown, climb):
    R = f["tool_d"] / 2
    a, b = f["w"] / 2 - R, f["h"] / 2 - R
    isl = f["island"]
    so = f["tool_d"] * stepover_ratio

    def allowed(x, y):
        inner = (np.abs(x - f["x"]) <= a + 1e-6) & (np.abs(y - f["y"]) <= b + 1e-6)
        if isl["type"] == "circle":
            clear = np.hypot(x - f["x"], y - f["y"]) >= isl["d"] / 2 + R - 1e-6
        else:
            qx = np.maximum(np.abs(x - f["x"]) - isl["w"] / 2, 0)
            qy = np.maximum(np.abs(y - f["y"]) - isl["h"] / 2, 0)
            clear = np.hypot(qx, qy) >= R - 1e-6
        return inner & clear

    p = Path()
    for z in zlevels(f["depth"], stepdown):
        zigzag(p, allowed, (f["x"] - a, f["x"] + a, f["y"] - b, f["y"] + b), so, z)
        p.lift()
        p.enter(f["x"] - a, f["y"] - b, z)
        rect_loop(p, f["x"], f["y"], a, b, z, climb)
        p.lift()
        if isl["type"] == "circle":
            r = isl["d"] / 2 + R
            p.enter(f["x"] + r, f["y"], z)
            circle_loop(p, f["x"], f["y"], r, z, cw=climb)
        else:
            w, h = isl["w"] + 2 * R, isl["h"] + 2 * R
            p.enter(f["x"], f["y"] - h / 2, z)
            rounded_rect_loop(p, w, h, R, z, cw=climb)
        p.lift()
    return p


def op_slot(f, rng, stepdown):
    p = Path()
    fwd = True
    for i, z in enumerate(zlevels(f["depth"], stepdown * 0.6)):
        a, b = ((f["x0"], f["y0"]), (f["x1"], f["y1"])) if fwd else ((f["x1"], f["y1"]), (f["x0"], f["y0"]))
        if i == 0:
            p.enter(a[0], a[1], z)
        else:
            p.feed(a[0], a[1], z)
        p.feed(b[0], b[1], z)
        fwd = not fwd
    p.lift()
    return p


def op_step(spec, f, rng, stepover_ratio, stepdown):
    R = f["tool_d"] / 2
    sw, sh = spec["stock_w"], spec["stock_h"]
    xe = f["x_edge"] - R
    so = f["tool_d"] * stepover_ratio

    def allowed(x, y):
        return x <= xe + 1e-6

    p = Path()
    for z in zlevels(f["depth"], stepdown):
        zigzag(p, allowed, (-sw / 2 - R - 1, xe, -sh / 2 - R - 1, sh / 2 + R + 1), so, z, rotate=True)
        p.lift()
    return p


def op_drill(holes, rng, peck):
    p = Path()
    for h in holes:
        p.moves.append(("drill", h["x"], h["y"], -(h["depth"] + (h["d"] / 2) / math.tan(math.radians(59))),
                        RETRACT, peck))
    p.pos = (holes[-1]["x"], holes[-1]["y"], SAFE)
    return p


def op_profile(spec, tool_d, stepdown, climb):
    o = spec["outline"]
    R = tool_d / 2
    p = Path()
    for z in zlevels(o["depth"], stepdown * 1.5):
        if o["type"] == "circle":
            r = o["d"] / 2 + R
            p.enter(r + 3, 0.0, z)        # lead-in from outside
            p.feed(r, 0.0, z)
            circle_loop(p, 0.0, 0.0, r, z, cw=climb)
        else:
            w, h, rc = o["w"] + 2 * R, o["h"] + 2 * R, o["r"] + R
            p.enter(0.0, -h / 2 - 3, z)
            p.feed(0.0, -h / 2, z)
            rounded_rect_loop(p, w, h, rc, z, cw=climb)
        p.lift()
    return p


def plan(spec, rng):
    """Return a list of operations: dict(name, kind, tool_d, spindle, feed, plunge, path)."""
    ops = []
    stepover = float(rng.uniform(0.4, 0.6))
    stepdown = float(rng.uniform(1.5, 3.5))
    climb = bool(rng.random() < 0.7)
    strategy = "zigzag" if rng.random() < 0.6 else "spiral"

    def add(name, kind, d, path):
        rpm = int(rng.uniform(0.8, 1.2) * min(12000, 60000 / max(d, 1)))
        ops.append(dict(name=name, kind=kind, tool_d=d, spindle=rpm,
                        feed=int(rng.uniform(0.6, 1.4) * rpm * 0.05 * min(d, 12)),
                        plunge=int(rng.uniform(80, 250)), path=path))

    if spec["face_depth"] > 0:
        fd = float(rng.choice([40.0, 50.0, 63.0]))
        add("facing", "face", fd, op_face(spec, fd, rng))
    milled = [f for f in spec["features"] if f["type"] != "hole"]
    holes = [f for f in spec["features"] if f["type"] == "hole"]
    by_tool = {}
    for f in milled:
        by_tool.setdefault(f["tool_d"], []).append(f)
    for d, feats in by_tool.items():
        for f in feats:
            t = f["type"]
            if t == "rect_pocket":
                add("pocket", "flat", d, op_rect_pocket(f, rng, strategy, stepover, stepdown, climb))
            elif t == "circ_pocket":
                add("bore", "flat", d, op_circ_pocket(f, rng, stepover, stepdown, climb))
            elif t == "ring_pocket":
                add("pocket_island", "flat", d, op_ring_pocket(f, rng, stepover, stepdown, climb))
            elif t == "slot":
                add("slot", "flat", d, op_slot(f, rng, stepdown))
            elif t == "step":
                add("step", "flat", d, op_step(spec, f, rng, stepover, stepdown))
    by_d = {}
    for h in holes:
        by_d.setdefault(h["d"], []).append(h)
    drill_ops = [("drill", "drill", d, op_drill(hs, rng, float(rng.uniform(1.5, 4.0)))) for d, hs in by_d.items()]
    if rng.random() < 0.3:      # some programmers drill first
        drill_first = drill_ops
        ops_tail = []
    else:
        drill_first, ops_tail = [], drill_ops
    if drill_first:
        head = ops[:1] if spec["face_depth"] > 0 else []
        rest = ops[len(head):]
        ops = head
        for a in drill_first:
            add(*a)
        ops += rest
    for a in ops_tail:
        add(*a)
    if spec["outline"] is not None:
        pd = float(rng.choice([8.0, 10.0, 12.0, 16.0]))
        add("profile", "flat", pd, op_profile(spec, pd, stepdown, climb))
    return ops, dict(stepover=stepover, stepdown=stepdown, climb=climb, strategy=strategy)
