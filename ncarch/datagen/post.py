"""Post-processors: operations -> G-code text in four controller "dialects".

The same part can come out looking completely different as text, which is
exactly the situation in a real shop archive.
"""
from __future__ import annotations

import math

from ..gcode.arcs import linearize_arc
from .cam import SAFE

STYLES = ["fanuc", "haas", "minimal", "inch_inc"]
KIND_TEXT = {"face": ("FACE MILL", "FACE MILL"), "flat": ("FLAT ENDMILL", "FLAT EM"),
             "drill": ("DRILL", "DRILL")}


class Poster:
    def __init__(self, style, theta=0.0, ox=0.0, oy=0.0):
        self.style = style
        self.c, self.s = math.cos(theta), math.sin(theta)
        self.ox, self.oy = ox, oy
        self.inch = style == "inch_inc"
        self.lines = []
        self.last = {}            # last written absolute value per axis (output units)
        self.motion = None
        self.feed = None
        self.pos = None           # machine coords, mm (unrounded)
        self.q = 1e-4 if self.inch else 1e-3

    # ------------------------------------------------------------ formatting
    def xf(self, x, y):
        return self.ox + self.c * x - self.s * y, self.oy + self.s * x + self.c * y

    def _units(self, v):
        return v / 25.4 if self.inch else v

    def _fmt(self, v):
        if self.style == "haas":
            return f"{v:.4f}"
        if self.style == "inch_inc":
            return f"{v:.4f}"
        s = f"{v:.3f}".rstrip("0")
        return s if not s.endswith(".") or self.style == "fanuc" else s + "0"

    def emit(self, text):
        self.lines.append(text)

    def comment(self, text):
        if self.style in ("fanuc", "haas", "inch_inc"):
            self.emit(f"({text})")

    def _axes(self, x, y, z, force=False):
        """Words for the axes that changed; absolute or incremental."""
        words = []
        for ax, v in (("X", x), ("Y", y), ("Z", z)):
            if v is None:
                continue
            q = round(self._units(v) / self.q)          # integer in output resolution
            prev = self.last.get(ax)
            if prev is not None and prev == q and not force:
                continue
            if self.incremental:
                if prev is None:
                    raise RuntimeError("incremental move before absolute position known")
                words.append(f"{ax}{self._fmt((q - prev) * self.q)}")
            else:
                words.append(f"{ax}{self._fmt(q * self.q)}")
            self.last[ax] = q
        return words

    incremental = False

    def _motion_word(self, g):
        if self.style == "minimal" and g == self.motion:
            return []
        self.motion = g
        return [f"G{g}" if self.style != "haas" else f"G{g:02d}"]

    # ------------------------------------------------------------ moves
    def rapid(self, x, y, z):
        mx, my = self.xf(x, y)
        w = self._axes(mx, my, z)
        if w:
            self.emit(" ".join(self._motion_word(0) + w))
        self.pos = (mx, my, z)

    def linear(self, x, y, z, f, machine=False):
        mx, my = (x, y) if machine else self.xf(x, y)
        w = self._axes(mx, my, z)
        if not w:
            return
        if f != self.feed:
            w.append(f"F{self._fmt(self._units(f)) if self.inch else int(f)}")
            self.feed = f
        self.emit(" ".join(self._motion_word(1) + w))
        self.pos = (mx, my, z)

    def arc(self, x, y, z, cx, cy, cw, f):
        mx, my = self.xf(x, y)
        mcx, mcy = self.xf(cx, cy)
        if self.style == "minimal":
            for px, py, pz in linearize_arc(self.pos, (mx, my, z), (mcx, mcy), cw, tol=0.02):
                self.linear(px, py, pz, f, machine=True)
            return
        sx, sy = self.pos[0], self.pos[1]
        w = self._axes(mx, my, z)
        if not w:             # full circle: end point equals start point
            w = self._axes(mx, my, None, force=True)
        g = 2 if cw else 3
        if self.style == "haas":
            r = math.hypot(sx - mcx, sy - mcy)
            w.append(f"R{self._fmt(self._units(r))}")
        else:
            w += [f"I{self._fmt(self._units(mcx - sx))}", f"J{self._fmt(self._units(mcy - sy))}"]
        if f != self.feed:
            w.append(f"F{self._fmt(self._units(f)) if self.inch else int(f)}")
            self.feed = f
        self.motion = None
        self.emit(" ".join([f"G{g}" if self.style != "haas" else f"G0{g}"] + w))
        self.motion = g
        self.pos = (mx, my, z)


def post(ops, style, rng, theta=0.0, ox=0.0, oy=0.0, part_no=1000):
    P = Poster(style, theta, ox, oy)
    tnums = {}
    lib = list(rng.permutation(range(1, 25)))
    for op in ops:
        key = (op["kind"], op["tool_d"])
        if key not in tnums:
            tnums[key] = int(lib[len(tnums)])

    # ---- header
    if style == "fanuc":
        P.emit("%")
        P.emit(f"O{part_no:04d} (PART {part_no})")
        P.emit("G21 G17 G40 G49 G80 G90")
    elif style == "haas":
        P.emit("%")
        P.emit(f"O0{part_no}")
        P.emit(f"(PART NUMBER {part_no})")
        P.emit("G00 G17 G21 G40 G49 G80 G90")
    elif style == "minimal":
        P.emit("G21 G90")
    else:
        P.emit("%")
        P.emit("G20 G17 G40 G80 G90")

    for op in ops:
        t = tnums[(op["kind"], op["tool_d"])]
        d = op["tool_d"]
        long_txt, short_txt = KIND_TEXT[op["kind"]]
        P.incremental = False
        P.last.pop("Z", None)
        P.motion = None
        P.feed = None
        if style == "fanuc":
            P.emit(f"T{t} M06")
            P.comment(f"T{t} - {d:.1f} MM {long_txt}")
        elif style == "haas":
            P.emit(f"T{t} M06 (D{d:g} {short_txt})")
        elif style == "minimal":
            P.emit(f"T{t} M6")
        else:
            P.emit(f"T{t} M6")
            P.comment(f"T{t} {d / 25.4:.4f} IN {long_txt}")
        P.emit(f"S{op['spindle']} M03")
        if style in ("fanuc", "haas"):
            P.emit("G54")
            P.emit(f"G43 H{t}")
        if style != "minimal":
            P.emit("M08")

        moves = op["path"].moves
        # first positioning move always absolute
        first = next(m for m in moves if m[0] in ("rapid", "feed", "drill"))
        P.rapid(first[1], first[2], SAFE)
        if style == "inch_inc":
            P.emit("G91")
            P.incremental = True
            P.motion = None

        drill_open = False
        for m in moves:
            if m[0] == "rapid":
                P.rapid(m[1], m[2], m[3])
            elif m[0] == "feed":
                zonly = P.pos is not None and abs(P.xf(m[1], m[2])[0] - P.pos[0]) < 1e-9 \
                    and abs(P.xf(m[1], m[2])[1] - P.pos[1]) < 1e-9
                P.linear(m[1], m[2], m[3], op["plunge"] if zonly else op["feed"])
            elif m[0] == "arc":
                P.arc(m[1], m[2], m[3], m[4], m[5], m[6], op["feed"])
            elif m[0] == "drill":
                _, x, y, zb, rp, peck = m
                if style in ("fanuc", "haas"):
                    mx, my = P.xf(x, y)
                    if not drill_open:
                        cyc = "G83" if rng.random() < 0.6 else "G81"
                        ret = "G98" if style == "fanuc" else "G99"
                        w = [ret, cyc] + P._axes(mx, my, None, force=True)
                        w += [f"Z{P._fmt(zb)}", f"R{P._fmt(rp)}"]
                        if cyc == "G83":
                            w.append(f"Q{P._fmt(peck)}")
                        w.append(f"F{op['plunge']}")
                        P.emit(" ".join(w))
                        drill_open = True
                    else:
                        w = P._axes(mx, my, None)
                        if w:
                            P.emit(" ".join(w))
                    P.pos = (mx, my, SAFE if style == "fanuc" else rp)
                else:
                    P.rapid(x, y, SAFE)
                    P.rapid(x, y, rp)
                    z = 0.0
                    while z - peck > zb:
                        z -= peck
                        P.linear(x, y, z, op["plunge"])
                        P.rapid(x, y, rp)
                        P.rapid(x, y, z + 0.5)
                    P.linear(x, y, zb, op["plunge"])
                    P.rapid(x, y, SAFE)
        if drill_open:
            P.emit("G80")
            P.last.pop("Z", None)
            P.motion = None
        if style == "inch_inc":
            P.emit("G90")
            P.incremental = False
        if style != "minimal":
            P.emit("M09")
        P.emit("M05")

    # ---- footer
    if style in ("fanuc", "haas", "inch_inc"):
        P.emit("G91 G28 Z0" if style != "haas" else "G28 G91 Z0.")
        P.emit("G90")
    P.emit("M30")
    if style != "minimal":
        P.emit("%")

    lines = P.lines
    if style == "fanuc":
        out, n = [], 10
        for ln in lines:
            if ln.startswith(("%", "O", "(")):
                out.append(ln)
            else:
                out.append(f"N{n} {ln}")
                n += 10
        lines = out
    tool_table = {int(v): dict(diameter=k[1], kind=k[0]) for k, v in tnums.items()}
    return "\n".join(lines) + "\n", tool_table
