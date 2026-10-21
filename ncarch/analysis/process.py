"""Process analysis: split the program into tool blocks, classify each block's
operation from what it removed, and estimate cycle time."""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from ..sim.stock import tool_blocks
from .geometry import open_to_edge

RAPID_MM_MIN = 10_000.0
TOOL_CHANGE_S = 8.0
PECK_S = 1.0
OPS = ["facing", "pocketing", "pocket_island", "bore", "slotting", "step_milling",
       "profiling", "drilling", "other"]


def _length(segs, kind):
    return sum(math.dist(s.start, s.end) for s in segs if s.kind == kind)


def is_facing(segs, tool, blk, stock):
    feeds = [s for s in segs if s.kind == "feed" and min(s.start[2], s.end[2]) < stock.top - 1e-6]
    if not feeds or not blk["mask"].any():
        return False
    depth = stock.top - blk["min_z"]
    levels = {round(min(s.start[2], s.end[2]), 3) for s in feeds}
    return depth <= 1.6 and (blk["mask"].mean() > 0.45 or (len(levels) == 1 and tool["kind"] == "face"))


def estimate_footprint(segs, tool, stock):
    """Stock outline estimated from a facing toolpath.

    Facing passes overrun the stock by about one cutter radius at their ends,
    and the outer passes overhang the side edges by roughly half a radius. So
    the stock is the pass envelope contracted by R along the passes and grown
    by R/2 across them.
    """
    R = tool["diameter"] / 2
    passes = [s for s in segs if s.kind == "feed" and abs(s.end[2] - s.start[2]) < 1e-6
              and math.hypot(s.end[0] - s.start[0], s.end[1] - s.start[1]) > 4]
    if not passes:
        return None
    longest = max(passes, key=lambda s: math.hypot(s.end[0] - s.start[0], s.end[1] - s.start[1]))
    ang = math.atan2(longest.end[1] - longest.start[1], longest.end[0] - longest.start[0])
    ux, uy = math.cos(ang), math.sin(ang)
    P = np.array([p[:2] for s in passes for p in (s.start, s.end)])
    u = P @ [ux, uy]
    v = P @ [-uy, ux]
    xs, ys = stock.cell_centers()
    X, Y = np.meshgrid(xs, ys)
    cu, cv = X * ux + Y * uy, -X * uy + Y * ux
    return ((cu >= u.min() + R) & (cu <= u.max() - R) &
            (cv >= v.min() - R / 2) & (cv <= v.max() + R / 2))


def classify_block(segs, tool, blk, stock):
    """Return (operation, n_features, details) for one tool block."""
    feeds = [s for s in segs if s.kind == "feed"]
    xy = sum(math.hypot(s.end[0] - s.start[0], s.end[1] - s.start[1]) for s in feeds)
    zl = sum(abs(s.end[2] - s.start[2]) for s in feeds)
    if tool["kind"] == "drill" or (feeds and xy < 0.05 * max(zl, 1e-9)):
        spots = {(round(s.end[0], 2), round(s.end[1], 2)) for s in feeds if s.end[2] < s.start[2]}
        return "drilling", len(spots), {}
    mask = blk["mask"]
    if not mask.any():
        return "other", 0, {}
    cell = stock.res ** 2
    area = mask.sum() * cell
    if is_facing(segs, tool, blk, stock):
        return "facing", 1, {}
    inner = None
    if stock.footprint is not None:
        inner = ndimage.binary_erosion(stock.footprint, iterations=max(1, int(1.5 / stock.res)))
    touches = open_to_edge(mask, stock.res, inner)
    island = ndimage.binary_fill_holes(mask).sum() - mask.sum()
    if island > mask.sum():
        return "profiling", 1, {}
    if touches:
        return "step_milling", 1, {}
    lab, n = ndimage.label(mask)
    if island * cell > max(0.03 * area, 20.0):
        return "pocket_island", n, {}
    # elongated, tool-width regions are slots; round ones are bores
    D = tool["diameter"]
    kinds = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(lab == i)
        pts = np.column_stack([xs, ys]) * stock.res
        if len(pts) < 5:
            continue
        ev, evec = np.linalg.eigh(np.cov(pts.T))
        ev = np.maximum(ev, 1e-9)
        width = 4 * math.sqrt(ev[0])                  # ~full width of a uniform strip
        aspect = math.sqrt(ev[1] / ev[0])
        proj = (pts - pts.mean(axis=0)) @ evec
        ext = proj.max(axis=0) - proj.min(axis=0) + stock.res
        fill = len(pts) * cell / (ext[0] * ext[1])     # circle ~0.785, rectangle ~1
        circ_like = aspect < 1.15 and fill < 0.86
        if aspect > 2.5 and width < 1.6 * D:
            kinds.append("slotting")
        elif circ_like:
            kinds.append("bore")
        else:
            kinds.append("pocketing")
    op = max(set(kinds), key=kinds.count) if kinds else "pocketing"
    return op, n, {}


def analyze_process(pr, tools, stock):
    blocks = tool_blocks(pr.segments)
    stock.footprint = None
    for (t, segs), blk in zip(blocks, stock.blocks):
        if is_facing(segs, tools[t], blk, stock):
            fp = estimate_footprint(segs, tools[t], stock)
            if fp is not None and fp.mean() > 0.2:
                stock.footprint = fp
            break
    sheet = []
    total_t = 0.0
    for (t, segs), blk in zip(blocks, stock.blocks):
        tool = tools[t]
        op, count, _ = classify_block(segs, tool, blk, stock)
        feed_t = sum(math.dist(s.start, s.end) / s.feed for s in segs if s.kind == "feed" and s.feed > 0)
        rapid_t = _length(segs, "rapid") / RAPID_MM_MIN
        secs = 60 * (feed_t + rapid_t)
        total_t += secs
        feeds = [s.feed for s in segs if s.kind == "feed" and s.feed > 0]
        sheet.append(dict(seq=len(sheet) + 1, tool=int(t), diameter=round(tool["diameter"], 2),
                          tool_kind=tool["kind"], diameter_source=tool["source"], operation=op,
                          count=int(count), depth=round(stock.top - blk["min_z"], 2),
                          feed=round(float(np.median(feeds)), 1) if feeds else 0.0,
                          spindle=float(segs[0].spindle), time_s=round(secs, 1),
                          volume_mm3=round(blk["volume"], 1),
                          line_from=segs[0].line, line_to=segs[-1].line))
    n_changes = max(len(pr.tool_order) - 1, 0)
    total_t += n_changes * TOOL_CHANGE_S + pr.pecks * PECK_S
    vol = sum(b["volume"] for b in stock.blocks)
    summary = dict(cycle_time_s=round(total_t, 1), tool_changes=n_changes, n_tools=len(tools),
                   cut_length_mm=round(_length(pr.segments, "feed"), 1),
                   rapid_length_mm=round(_length(pr.segments, "rapid"), 1),
                   removed_volume_mm3=round(vol, 1),
                   mrr_cm3_min=round(vol / 1000 / max(total_t / 60, 1e-9), 2))
    return sheet, summary
