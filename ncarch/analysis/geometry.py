"""Machining-feature recognition on the recovered depth image."""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage
from skimage import measure

STRUCT = ndimage.generate_binary_structure(2, 1)


def open_to_edge(mask, res, inner=None):
    """Is a cut region open to the side of the part (a step) rather than enclosed?

    With an estimated stock outline, the region must run past the stock edge.
    Without one, only the machined domain is known. A region then counts as open
    if it runs along one to three sides of that domain for a real length: a hole
    that merely sits at the extreme of the cut area only grazes the edge, and a
    region that spans all four sides IS the whole known area, so nothing shows
    it is open.
    """
    if inner is not None:
        return bool((mask & ~inner).sum() * res * res >= 4.0)
    band = max(1, int(3.0 / res))
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return False
    ext_x, ext_y = (xs.max() - xs.min() + 1) * res, (ys.max() - ys.min() + 1) * res
    sides = 0
    for edge, ext in ((mask[:band].any(axis=0), ext_x), (mask[-band:].any(axis=0), ext_x),
                      (mask[:, :band].any(axis=1), ext_y), (mask[:, -band:].any(axis=1), ext_y)):
        if edge.sum() * res >= max(8.0, 0.25 * ext):
            sides += 1
    return sides == 3   # runs through the part: open on one side, flanked on two


def facing_depth(depth, sheet):
    for row in sheet:
        if row["operation"] == "facing":
            return row["depth"]
    return 0.0


def _component(mask, D, res, edge_cells, inner=None):
    ys, xs = np.nonzero(mask)
    area = mask.sum() * res * res
    props = measure.regionprops(mask.astype(np.uint8))[0]
    perim = max(props.perimeter * res, 1e-9)
    circ = 4 * math.pi * area / perim ** 2
    pts = np.column_stack([xs, ys]).astype(float) * res
    c = pts.mean(axis=0)
    ev, evec = np.linalg.eigh(np.cov(pts.T)) if len(pts) > 2 else (np.array([1.0, 1.0]), np.eye(2))
    ev = np.maximum(ev, 1e-9)
    # extents along the principal axes
    proj = (pts - c) @ evec
    ext = proj.max(axis=0) - proj.min(axis=0) + res
    angle = math.degrees(math.atan2(evec[1, 1], evec[0, 1])) % 180
    dvals = D[mask]
    touches = open_to_edge(mask, res, inner)
    filled = ndimage.binary_fill_holes(mask)
    island = (filled.sum() - mask.sum()) * res * res
    return dict(area=area, circ=circ, cx=float(c[0]), cy=float(c[1]), length=float(ext[1]),
                width=float(ext[0]), angle=angle, aspect=float(math.sqrt(ev[1] / ev[0])),
                depth=float(np.median(dvals)), max_depth=float(dvals.max()),
                touches=touches, island_area=float(island))


def classify(c):
    # an enclosed uncut region larger than the cut ring itself = the finished part
    # inside a profile pass; a smaller one = an island left inside a pocket
    if c["island_area"] > 1.0 * c["area"]:
        return "outline"
    if c["touches"]:
        return "step"
    if c["island_area"] > max(0.03 * c["area"], 20.0):
        return "pocket_island"
    fill = c["area"] / max(c["length"] * c["width"], 1e-9)   # circle ~0.785, square ~1
    if c["circ"] > 0.75 and c["aspect"] < 1.3 and fill < 0.86:
        d = 2 * math.sqrt(c["area"] / math.pi)
        return "hole" if d <= 14.0 else "circular_pocket"
    if c["aspect"] > 2.5 and c["width"] < 16.5:
        return "slot"
    return "pocket"


def floor_levels(D, fd, res, min_area):
    """Depths of flat floors (plateaus): steps, pocket floors, through-cuts.

    Only cells with ~zero slope count, so drill-point cones and ball-end
    scallops do not create spurious levels.
    """
    gy, gx = np.gradient(D, res)
    flat = (np.hypot(gx, gy) < 0.05) & (D > fd + 0.3)
    if not flat.any():
        return []
    vals = np.round(D[flat] * 2) / 2                      # 0.5 mm bins
    u, cnt = np.unique(vals, return_counts=True)
    levels = [float(v) for v, c in zip(u, cnt) if c * res * res >= min_area * 2]
    merged = []
    for v in levels:
        if merged and v - merged[-1] < 0.75:
            continue
        merged.append(v)
    return merged


def recognize(stock, sheet, min_area=4.0):
    """Find features level by level with nesting.

    Thresholds sit between successive floor depths. Each connected region at
    one level becomes a feature whose parent is the region containing it one
    level up. A region identical to its parent (e.g. a through-hole seen at
    every level) is not repeated.
    """
    D = stock.depth()
    res = stock.res
    fd = facing_depth(D, sheet)
    edge = max(1, int(3.0 / res))
    inner = None
    if stock.footprint is not None:
        inner = ndimage.binary_erosion(stock.footprint, iterations=max(1, int(1.5 / res)))
    floors = floor_levels(D, fd, res, min_area)
    thresholds = [fd + 0.3] + [(a + b) / 2 for a, b in zip(floors, floors[1:])]
    feats = []
    prev_lab, prev_ids = None, {}
    for t in thresholds:
        mask = ndimage.binary_opening(ndimage.binary_closing(D > t, STRUCT), STRUCT)
        lab, n = ndimage.label(mask)
        ids = {}
        for i in range(1, n + 1):
            m = lab == i
            if m.sum() * res * res < min_area:
                continue
            parent = None
            if prev_lab is not None:
                pl = np.bincount(prev_lab[m]).argmax()
                parent = prev_ids.get(int(pl))
                if parent is not None and m.sum() >= 0.95 * feats[parent]["_n"]:
                    ids[i] = parent            # same region as one level up
                    continue
            c = _component(m, D, res, edge, inner)
            c["type"] = classify(c)
            c["parent"] = parent
            c["id"] = len(feats)
            c["_n"] = int(m.sum())
            floor = [f for f in floors if f > t]
            c["depth"] = round(floor[0], 3) if floor else c["depth"]
            ids[i] = c["id"]
            feats.append(c)
        prev_lab, prev_ids = lab, ids
    for f in feats:
        f.pop("_n", None)
    # hole patterns: bolt circles and grids
    holes = [f for f in feats if f["type"] == "hole"]
    pattern = None
    if len(holes) >= 3:
        P = np.array([[h["cx"], h["cy"]] for h in holes])
        cen = P.mean(axis=0)
        r = np.linalg.norm(P - cen, axis=1)
        ang = np.sort(np.arctan2(P[:, 1] - cen[1], P[:, 0] - cen[0]))
        gaps = np.diff(np.concatenate([ang, ang[:1] + 2 * np.pi]))
        # on a common circle AND evenly spaced (rectangle corners are concyclic too)
        if r.mean() > 1 and r.std() / r.mean() < 0.05 and gaps.std() / gaps.mean() < 0.1:
            pattern = dict(kind="bolt_circle", n=len(holes), pcd=round(2 * float(r.mean()), 2))
        else:
            pattern = dict(kind="scattered", n=len(holes))
    for f in feats:
        f["x"] = round(stock.x0 + f.pop("cx"), 3)
        f["y"] = round(stock.y0 + f.pop("cy"), 3)
        for k in ("area", "circ", "length", "width", "angle", "aspect", "depth", "max_depth", "island_area"):
            f[k] = round(f[k], 3)
        if f["type"] in ("hole", "circular_pocket"):
            f["diameter"] = round(2 * math.sqrt(f["area"] / math.pi), 2)
    return feats, pattern, fd


def describe(feats, pattern):
    """Human-readable one-line summary, e.g. '4x hole D8.5 on PCD 60, 1x pocket 40x25x6'."""
    out = []
    groups = {}
    for f in feats:
        if f["type"] == "hole":
            key = ("hole", round(f["diameter"]))
        elif f["type"] in ("pocket", "slot", "pocket_island"):
            key = (f["type"], round(f["length"]), round(f["width"]), round(f["max_depth"]))
        else:
            key = (f["type"],)
        groups[key] = groups.get(key, 0) + 1
    for key, n in sorted(groups.items(), key=lambda kv: -kv[1]):
        if key[0] == "hole":
            s = f"{n}x hole Ø{key[1]}"
            if pattern and pattern["kind"] == "bolt_circle" and pattern["n"] == n:
                s += f" on PCD {pattern['pcd']:.0f}"
        elif len(key) == 4:
            s = f"{n}x {key[0].replace('_', ' ')} {key[1]}x{key[2]}x{key[3]}"
        else:
            s = f"{n}x {key[0].replace('_', ' ')}"
        out.append(s)
    return ", ".join(out) if out else "no features below faced surface"
