"""2.5D height-map (dexel) stock model and material-removal simulation."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .tools import profile

EPS = 1e-6


@dataclass
class Stock:
    x0: float
    y0: float
    res: float
    top: float
    base: float
    Z: np.ndarray                      # shape (ny, nx), row = y
    blocks: list = field(default_factory=list)   # per tool-block removal stats
    footprint: np.ndarray | None = None          # estimated stock outline (from facing)

    @property
    def shape(self):
        return self.Z.shape

    def cell_centers(self):
        ny, nx = self.Z.shape
        xs = self.x0 + (np.arange(nx) + 0.5) * self.res
        ys = self.y0 + (np.arange(ny) + 0.5) * self.res
        return xs, ys

    def depth(self):
        """Removed depth below the stock top (>= 0)."""
        return self.top - self.Z


def infer_domain(segments, tools, margin=2.0):
    """Stock top, base and XY extents inferred from the cutting moves alone."""
    feeds = [s for s in segments if s.kind == "feed"]
    if not feeds:
        raise ValueError("program contains no cutting moves")
    zs = np.array([min(s.start[2], s.end[2]) for s in feeds])
    if (zs < -0.01).any():
        top = 0.0                           # usual convention: Z0 = stock top
    else:
        top = float(max(max(s.start[2], s.end[2]) for s in feeds
                        if abs(s.end[0] - s.start[0]) + abs(s.end[1] - s.start[1]) > EPS))
    cutting = [s for s in feeds if min(s.start[2], s.end[2]) < top - EPS]
    if not cutting:
        cutting = feeds
    xs, ys = [], []
    for s in cutting:
        R = tools[s.tool]["diameter"] / 2
        for p in (s.start, s.end):
            xs += [p[0] - R, p[0] + R]
            ys += [p[1] - R, p[1] + R]
    base = float(zs.min()) - 1.0
    return top, base, min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin


def make_stock(segments, tools, res=0.25, max_cells=900_000):
    top, base, xmin, xmax, ymin, ymax = infer_domain(segments, tools)
    w, h = xmax - xmin, ymax - ymin
    if (w / res) * (h / res) > max_cells:            # keep huge parts tractable
        res = math.sqrt(w * h / max_cells)
    nx, ny = int(math.ceil(w / res)), int(math.ceil(h / res))
    return Stock(xmin, ymin, res, top, base, np.full((ny, nx), top, dtype=np.float32))


def _window(stock, xa, xb, ya, yb):
    ny, nx = stock.Z.shape
    i0 = max(int((xa - stock.x0) / stock.res), 0)
    i1 = min(int((xb - stock.x0) / stock.res) + 2, nx)
    j0 = max(int((ya - stock.y0) / stock.res), 0)
    j1 = min(int((yb - stock.y0) / stock.res) + 2, ny)
    if i0 >= i1 or j0 >= j1:
        return None
    xs = stock.x0 + (np.arange(i0, i1) + 0.5) * stock.res
    ys = stock.y0 + (np.arange(j0, j1) + 0.5) * stock.res
    X, Y = np.meshgrid(xs, ys)
    return (slice(j0, j1), slice(i0, i1)), X, Y


def stamp(stock, p0, p1, R, kind):
    """Lower the height map by one straight cutter move from p0 to p1."""
    (x0, y0, z0), (x1, y1, z1) = p0, p1
    if min(z0, z1) >= stock.top - EPS and kind not in ("drill", "chamfer", "ball"):
        return
    win = _window(stock, min(x0, x1) - R, max(x0, x1) + R, min(y0, y1) - R, max(y0, y1) + R)
    if win is None:
        return
    sl, X, Y = win
    dx, dy = x1 - x0, y1 - y0
    L2 = dx * dx + dy * dy
    Zw = stock.Z[sl]
    if L2 < EPS:                                         # vertical plunge
        r = np.hypot(X - x0, Y - y0)
        m = r <= R
        surf = min(z0, z1) + profile(kind, r, R)
        Zw[m] = np.minimum(Zw[m], surf[m])
        return
    if kind in ("flat", "face"):
        # exact: the lowest tip height over the part of the move that covers the cell
        L = math.sqrt(L2)
        t = ((X - x0) * dx + (Y - y0) * dy) / L2
        perp2 = (X - x0) ** 2 + (Y - y0) ** 2 - (t * L) ** 2
        half = np.sqrt(np.maximum(R * R - perp2, 0.0)) / L
        lo, hi = np.clip(t - half, 0, 1), np.clip(t + half, 0, 1)
        m = (perp2 <= R * R) & (t - half <= 1) & (t + half >= 0)
        surf = np.minimum(z0 + (z1 - z0) * lo, z0 + (z1 - z0) * hi)
        Zw[m] = np.minimum(Zw[m], surf[m].astype(np.float32))
        return
    # shaped cutters on a linear move: sample tool positions along the move
    n = max(2, int(math.ceil(math.sqrt(L2) / (stock.res * 0.75))) + 1)
    for t in np.linspace(0, 1, n):
        cx, cy, cz = x0 + dx * t, y0 + dy * t, z0 + (z1 - z0) * t
        r = np.hypot(X - cx, Y - cy)
        m = r <= R
        surf = cz + profile(kind, r, R)
        Zw[m] = np.minimum(Zw[m], surf[m])


def tool_blocks(segments):
    """Consecutive runs of segments that use the same tool."""
    blocks = []
    for s in segments:
        if not blocks or blocks[-1][0] != s.tool:
            blocks.append((s.tool, []))
        blocks[-1][1].append(s)
    return blocks


def simulate(segments, tools, res=0.25):
    """Run the whole program; record per-block removal masks for process analysis."""
    stock = make_stock(segments, tools, res)
    cell_area = stock.res ** 2
    for idx, (t, segs) in enumerate(tool_blocks(segments)):
        R = tools[t]["diameter"] / 2
        kind = tools[t]["kind"]
        before = stock.Z.copy()
        for s in segs:
            if s.kind == "feed":
                stamp(stock, s.start, s.end, R, kind)
        removed = before - stock.Z
        mask = removed > 0.02
        stock.blocks.append(dict(index=idx, tool=t, mask=mask,
                                 volume=float(removed.sum() * cell_area),
                                 min_z=float(stock.Z[mask].min()) if mask.any() else stock.top))
    return stock
