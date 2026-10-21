"""Cutter profiles and tool-diameter inference for programs without tool comments."""
from __future__ import annotations

import math

import numpy as np

STANDARD_MM = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 25, 32, 40, 50, 63]
DEFAULT_DIA = 6.0
ASSUMED_STEPOVER_RATIO = 0.5   # typical CAM default: 40-60 % of D


def profile(kind, r, R):
    """Height of the cutter surface above its tip at radial distance r (r <= R)."""
    if kind == "ball":
        return R - np.sqrt(np.maximum(R * R - r * r, 0.0))
    if kind == "drill":
        return r / math.tan(math.radians(59))   # 118 deg point
    if kind == "chamfer":
        return r                                # 90 deg included angle
    return np.zeros_like(r)


def snap(d):
    return min(STANDARD_MM, key=lambda s: abs(s - d))


def _stepovers(segs, min_passes=3):
    """Pass spacing inside raster (zig-zag) runs.

    A raster run is >= 3 long, alternating, parallel passes at one Z joined by
    short link moves with no rapid in between. Requiring this pattern rejects
    look-alikes such as separate parallel slots or the two long sides of a
    profile loop, whose spacing says nothing about the cutter.
    """
    out = []
    run = []                      # passes in the current run: (start, end, ux, uy)

    def close():
        if len(run) >= min_passes:
            for a, b in zip(run, run[1:]):
                (ax, ay), ux, uy = a[0], a[2], a[3]
                bx, by = b[0]
                out.append(abs((bx - ax) * uy - (by - ay) * ux))
        run.clear()

    pending_link = 0.0
    for s in segs:
        (x0, y0, z0), (x1, y1, z1) = s.start, s.end
        L = math.hypot(x1 - x0, y1 - y0)
        if s.kind != "feed" or abs(z1 - z0) > 1e-6 or s.arc:
            close()
            pending_link = 0.0
            continue
        ux, uy = ((x1 - x0) / L, (y1 - y0) / L) if L > 1e-9 else (0.0, 0.0)
        if run:
            p = run[-1]
            plen = math.hypot(p[1][0] - p[0][0], p[1][1] - p[0][1])
            anti = ux * p[2] + uy * p[3] < -0.9998           # reversed direction
            if anti and L > 4.0 and abs(z0 - p[4]) < 1e-6 and pending_link > 0 \
                    and pending_link < 0.6 * min(L, plen):
                run.append(((x0, y0), (x1, y1), ux, uy, z0))
                pending_link = 0.0
                continue
            if L < 0.6 * plen and pending_link == 0.0:
                pending_link = L                             # candidate step-over link
                continue
            close()
        pending_link = 0.0
        if L > 4.0:
            run.append(((x0, y0), (x1, y1), ux, uy, z0))
    close()
    return [d for d in out if 0.3 < d < 40]


def resolve_tools(pr):
    """Fill in missing diameters/kinds in a ParseResult's tool table (in place).

    Returns {tool: dict(diameter, kind, source)}.
    """
    by_tool, all_by_tool = {}, {}
    for s in pr.segments:
        all_by_tool.setdefault(s.tool, []).append(s)
        if s.kind == "feed":
            by_tool.setdefault(s.tool, []).append(s)
    for t, info in pr.tools.items():
        segs = by_tool.get(t, [])
        xy_len = sum(math.hypot(s.end[0] - s.start[0], s.end[1] - s.start[1]) for s in segs)
        z_len = sum(abs(s.end[2] - s.start[2]) for s in segs)
        if info.kind == "flat" and segs and xy_len < 0.05 * max(z_len, 1e-9):
            info.kind = "drill"          # only plunges: behaves like a drill
        if info.diameter is None:
            steps = _stepovers(all_by_tool.get(t, []))
            cut_z = {round(min(s.start[2], s.end[2]), 3) for s in segs if min(s.start[2], s.end[2]) < 0}
            facing_like = len(cut_z) == 1 and max(cut_z, default=-99) > -1.6
            if len(steps) >= 2 and info.kind != "drill":
                info.diameter = float(snap(float(np.median(steps)) / ASSUMED_STEPOVER_RATIO))
                info.source = "inferred"
                if facing_like and info.diameter >= 25:
                    info.kind = "face"
            elif facing_like and (steps := _stepovers(all_by_tool.get(t, []), min_passes=2)):
                # one shallow level of long passes: a face mill, typically 60-75 % step-over
                info.diameter = float(snap(float(np.median(steps)) / 0.7))
                info.kind, info.source = "face", "inferred"
            else:
                info.diameter = DEFAULT_DIA
                info.source = "default"
    return {t: dict(diameter=round(i.diameter, 3), kind=i.kind, source=i.source) for t, i in pr.tools.items()}
