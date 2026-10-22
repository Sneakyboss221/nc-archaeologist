"""Program fingerprint: describes WHAT a program makes, not how it is written.

All geometric terms are invariant to rotation and translation on the table and
(except the separate scale block) to the overall size of the part.
"""
from __future__ import annotations

import math

import numpy as np

from .process import OPS

FEATURE_TYPES = ["hole", "pocket", "circular_pocket", "slot", "step", "outline", "pocket_island"]
N_HIST = 12
N_RADIAL = 12


def hu_moments(img):
    """The seven Hu moment invariants of a 2D image (rows = first index).

    Raw moments m_pq, converted analytically to central moments mu_pq about
    the centroid, normalised nu_pq = mu_pq / mu_00^(1 + (p+q)/2), then Hu's
    1962 combinations. The arithmetic follows scikit-image step for step, so
    results are bit-identical to it (this matters for the near-zero 7th
    invariant of symmetric parts) without loading its compiled modules.
    """
    calc = np.asarray(img, dtype=np.float64)
    orders = np.arange(4, dtype=np.float64)
    for dim, n in enumerate(calc.shape):              # raw moments via per-axis dot products
        powers = np.arange(n, dtype=np.float64)[:, None] ** orders
        labels = [0, 1]
        calc = np.einsum(calc, labels[:dim] + [2] + labels[dim + 1:], powers, [2, 3],
                         labels[:dim] + [3] + labels[dim + 1:], optimize="greedy")
    m = calc
    cx, cy = m[1, 0] / m[0, 0], m[0, 1] / m[0, 0]
    mu = np.zeros_like(m)
    mu[0, 0] = m[0, 0]
    mu[1, 1] = m[1, 1] - cx * m[0, 1]
    mu[2, 0] = m[2, 0] - cx * m[1, 0]
    mu[0, 2] = m[0, 2] - cy * m[0, 1]
    mu[2, 1] = m[2, 1] - 2 * cx * m[1, 1] - cy * m[2, 0] + cx ** 2 * m[0, 1] + cy * cx * m[1, 0]
    mu[1, 2] = m[1, 2] - 2 * cy * m[1, 1] - cx * m[0, 2] + 2 * cy * cx * m[0, 1]
    mu[3, 0] = m[3, 0] - 3 * cx * m[2, 0] + 2 * cx ** 2 * m[1, 0]
    mu[0, 3] = m[0, 3] - 3 * cy * m[0, 2] + 2 * cy ** 2 * m[0, 1]
    nu = np.zeros_like(mu)
    for p in range(4):
        for q in range(4):
            s = p + q
            nu[p, q] = np.nan if s < 2 else (mu[p, q] / 1.0 ** s) / (mu[0, 0] ** (s / 2 + 1))
    t0, t1 = nu[3, 0] + nu[1, 2], nu[2, 1] + nu[0, 3]
    q0, q1 = t0 * t0, t1 * t1
    n4, s, d = 4 * nu[1, 1], nu[2, 0] + nu[0, 2], nu[2, 0] - nu[0, 2]
    hu = np.empty(7)
    hu[0] = s
    hu[1] = d * d + n4 * nu[1, 1]
    hu[3] = q0 + q1
    hu[5] = d * (q0 - q1) + n4 * t0 * t1
    t0, t1 = t0 * (q0 - 3 * q1), t1 * (3 * q0 - q1)
    q0, q1 = nu[3, 0] - 3 * nu[1, 2], 3 * nu[2, 1] - nu[0, 3]
    hu[2] = q0 * q0 + q1 * q1
    hu[4] = q0 * t0 + q1 * t1
    hu[6] = q1 * t0 - q0 * t1
    return hu


def _hu(img):
    hu = hu_moments(img)
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
