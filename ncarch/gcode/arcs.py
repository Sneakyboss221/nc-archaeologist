"""Circular interpolation (G2/G3) linearisation in the XY plane (G17)."""
from __future__ import annotations

import math


def arc_center_from_r(sx, sy, ex, ey, r, cw):
    """Centre of an arc given by its radius word R (negative R = arc > 180 deg)."""
    dx, dy = ex - sx, ey - sy
    d = math.hypot(dx, dy)
    if d < 1e-9:
        raise ValueError("R-form arc with coincident start and end")
    big = r < 0
    r = abs(r)
    if d > 2 * r:  # tolerate rounding in posted programs
        r = d / 2
    h = math.sqrt(max(r * r - (d / 2) ** 2, 0.0))
    mx, my = sx + dx / 2, sy + dy / 2
    # unit normal to the chord, pointing left of the direction of travel
    nx, ny = -dy / d, dx / d
    # for a CW arc shorter than 180 deg the centre lies to the right of the chord
    sign = -1 if cw else 1
    if big:
        sign = -sign
    return mx + sign * h * nx, my + sign * h * ny


def linearize_arc(start, end, center, cw, tol=0.05):
    """Return points (excluding start, including end) approximating the arc.

    The Z coordinate is interpolated linearly, so helical moves are handled too.
    """
    sx, sy, sz = start
    ex, ey, ez = end
    cx, cy = center
    r = math.hypot(sx - cx, sy - cy)
    if r < 1e-9:
        return [end]
    a0 = math.atan2(sy - cy, sx - cx)
    a1 = math.atan2(ey - cy, ex - cx)
    if cw:
        sweep = a0 - a1
        if sweep <= 1e-9:
            sweep += 2 * math.pi
    else:
        sweep = a1 - a0
        if sweep <= 1e-9:
            sweep += 2 * math.pi
    step = 2 * math.acos(max(-1.0, 1 - tol / r)) if tol < r else math.pi / 4
    n = max(2, int(math.ceil(sweep / step)))
    pts = []
    for i in range(1, n + 1):
        t = i / n
        a = a0 - sweep * t if cw else a0 + sweep * t
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a), sz + (ez - sz) * t))
    pts[-1] = end
    return pts
