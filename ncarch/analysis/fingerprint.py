"""Program fingerprint: describes WHAT a program makes, not how it is written.

All geometric terms are invariant to rotation and translation on the table and
(except the separate scale block) to the overall size of the part.
"""
from __future__ import annotations

import math

import numpy as np
from skimage import measure

from .process import OPS

FEATURE_TYPES = ["hole", "pocket", "circular_pocket", "slot", "step", "outline", "pocket_island"]
N_HIST = 12
N_RADIAL = 12


def _hu(img):
    mu = measure.moments_central(img)
    nu = measure.moments_normalized(mu)
    hu = measure.moments_hu(nu)
    return -np.sign(hu) * np.log10(np.abs(hu) + 1e-30)


def design_depth(stock, sheet, face_d):
    """Depth image of the design features only.

    Facing, the outer profile ring (a separation cut whose presence depends on
    how the blank was supplied) and cuts in air outside the estimated stock
    are removed.
    """
    D = np.maximum(stock.depth() - face_d, 0.0).astype(float)
    for row, blk in zip(sheet, stock.blocks):
        if row["operation"] == "profiling":
            D[blk["mask"]] = 0.0
    if stock.footprint is not None:
        D[~stock.footprint] = 0.0
    D[D < 0.3] = 0.0
    return D


def geometry_vector(stock, feats, pattern, face_d, sheet):
    D = design_depth(stock, sheet, face_d)
    feats = [f for f in feats if f["type"] != "outline"]
    if D.max() <= 0:
        return np.zeros(N_HIST + 7 + N_RADIAL + len(FEATURE_TYPES) + 8)
    dmax = D.max()
    on = D > 0
    # 1. depth distribution of the cut area (relative to deepest cut)
    hist, _ = np.histogram(D[on] / dmax, bins=N_HIST, range=(0, 1))
    hist = hist / max(hist.sum(), 1)
    # 2. Hu moment invariants of the depth image (rotation/scale invariant)
    hu = np.clip(_hu(D / dmax), -30, 30) / 10.0
    # 3. radial depth profile about the depth-weighted centroid
    ys, xs = np.nonzero(on)
    w = D[on]
    cx, cy = np.average(xs, weights=w), np.average(ys, weights=w)
    r = np.hypot(xs - cx, ys - cy)
    rg = math.sqrt(np.average(r ** 2, weights=w)) + 1e-9      # radius of gyration
    rb = np.clip((r / (2 * rg) * N_RADIAL).astype(int), 0, N_RADIAL - 1)
    radial = np.bincount(rb, weights=w / dmax, minlength=N_RADIAL)
    radial = radial / max(radial.sum(), 1e-9)
    # 4. recognised feature counts (log-scaled)
    counts = np.array([sum(f["type"] == t for f in feats) for t in FEATURE_TYPES], float)
    counts = np.log1p(counts)
    # 5. shape & pattern descriptors
    pts = np.column_stack([xs, ys]).astype(float)
    ev = np.sort(np.linalg.eigvalsh(np.cov(pts.T))) if len(pts) > 2 else np.array([1.0, 1.0])
    elong = math.sqrt(ev[0] / max(ev[1], 1e-9))
    holes = [f for f in feats if f["type"] == "hole"]
    hole_d = np.mean([f["diameter"] for f in holes]) / (2 * rg * stock.res) if holes else 0.0
    bolt = 1.0 if pattern and pattern["kind"] == "bolt_circle" else 0.0
    cut_frac = on.mean()
    through = (D > 0.8 * dmax).sum() / max(on.sum(), 1)
    top_feats = [f for f in feats if f["parent"] is None and f["type"] not in ("outline", "step")]
    biggest = max((f["area"] for f in top_feats), default=0.0) / max(on.sum() * stock.res ** 2, 1e-9)
    nested = sum(f["parent"] is not None for f in feats)
    shape = np.array([elong, hole_d, bolt, cut_frac, through, biggest, math.log1p(nested),
                      float(np.mean([f["aspect"] for f in top_feats])) / 5 if top_feats else 0.0])
    return np.concatenate([hist, hu, radial, counts, shape])


def process_vector(sheet, summary):
    total = sum(r["time_s"] for r in sheet) or 1.0
    mix = np.array([sum(r["time_s"] for r in sheet if r["operation"] == op) / total for op in OPS])
    present = np.array([float(any(r["operation"] == op for r in sheet)) for op in OPS])
    n_ops = np.array([math.log1p(sum(r["count"] for r in sheet if r["operation"] == op)) for op in OPS])
    return np.concatenate([mix, present, n_ops,
                           [math.log1p(summary["n_tools"]), math.log1p(summary["tool_changes"])]])


def scale_vector(stock, summary):
    D = stock.depth()
    h, w = D.shape
    return np.array([math.log(w * stock.res), math.log(h * stock.res), math.log1p(float(D.max())),
                     math.log1p(summary["removed_volume_mm3"]), math.log1p(summary["cycle_time_s"])])
