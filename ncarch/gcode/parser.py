"""G-code parser: tokenizer + modal state machine for 3-axis milling programs.

Produces a flat list of straight-line `Segment`s in millimetres and absolute
machine coordinates. Arcs are linearised, canned drilling cycles are expanded,
and anything the parser cannot execute faithfully is recorded in `warnings`.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .arcs import arc_center_from_r, linearize_arc

WORD_RE = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
COMMENT_RE = re.compile(r"\(([^)]*)\)")
MACRO_RE = re.compile(r"#|\b(IF|WHILE|GOTO|DO|END\d)\b")

INCH = 25.4
SUPPORTED_G = {0, 1, 2, 3, 4, 17, 20, 21, 28, 40, 43, 49, 53, 54, 55, 56, 57,
               58, 59, 80, 81, 82, 83, 90, 91, 94, 98, 99}
SUPPORTED_M = {0, 1, 3, 4, 5, 6, 7, 8, 9, 30, 2}
TOOL_TYPES = [("BALL", "ball"), ("DRILL", "drill"), ("SPOT", "drill"),
              ("CHAMFER", "chamfer"), ("FACE", "face"), ("FLAT", "flat"),
              ("END", "flat"), ("EM", "flat")]


@dataclass
class Segment:
    start: tuple
    end: tuple
    kind: str          # "rapid" | "feed"
    tool: int
    feed: float        # mm/min (0 for rapids)
    spindle: float
    line: int
    arc: bool = False


@dataclass
class ToolInfo:
    number: int
    diameter: float | None = None   # mm, None if the program does not say
    kind: str = "flat"
    source: str = "default"         # "comment" | "inferred" | "default"


@dataclass
class ParseResult:
    segments: list = field(default_factory=list)
    tools: dict = field(default_factory=dict)
    tool_order: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    n_lines: int = 0
    used_inch: bool = False
    used_incremental: bool = False
    used_canned: bool = False
    used_arcs: bool = False
    pecks: int = 0                   # extra peck retracts (cycle time only)
    notes: list = field(default_factory=list)   # informational, e.g. expanded subprograms

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)


def _parse_tool_comment(text, inch):
    """Extract (tool number, diameter mm, kind) from a comment like
    'T3 D6.0 FLAT ENDMILL', 'TOOL 2 - 8MM DRILL' or 'T4 0.25 IN BALL'."""
    up = text.upper()
    num = None
    m = re.search(r"\bT(?:OOL)?\s*#?\s*(\d+)", up)
    if m:
        num = int(m.group(1))
    dia = None
    m = re.search(r"\b(?:D|DIA|DIAM|DIAMETER|Ø)\s*=?\s*(\d*\.?\d+)\s*(MM|IN|\")?", up)
    if not m:
        m = re.search(r"(\d*\.?\d+)\s*(MM|IN|\")", up)
    if m:
        dia = float(m.group(1))
        unit = m.group(2)
        if unit in ("IN", '"') or (unit is None and inch):
            dia *= INCH
    kind = None
    for key, k in TOOL_TYPES:
        if re.search(r"\b" + key, up):
            kind = k
            break
    return num, dia, kind


FANUC_SUB_RE = re.compile(r"^\s*O(\d+)\b", re.I)
FANUC_CALL_RE = re.compile(r"\bM98\s*P(\d+)(?:\s*L(\d+))?", re.I)
LCNC_RE = re.compile(r"^\s*o(\d+)\s+(sub|endsub|call)\b", re.I)
LATHE_CUES = [re.compile(r"\bT\d{4}\b"), re.compile(r"\bG9[67]\b"), re.compile(r"\bG18\b"),
              re.compile(r"\bG7[0-2]\b")]


def expand_subprograms(text, notes):
    """Inline subprograms defined in the same file.

    Supports Fanuc/Haas `M98 P<n> [L<count>]` with `O<n> ... M99` bodies placed
    after the main program, and LinuxCNC `o<n> sub ... o<n> endsub` with `o<n> call`.
    """
    lines = text.splitlines()
    subs, main = {}, []
    cur, cur_kind = None, None
    seen_end = False
    for ln in lines:
        m = LCNC_RE.match(ln)
        if m and m.group(2).lower() == "sub":
            cur, cur_kind = "o" + m.group(1), "lcnc"
            subs[cur] = []
            continue
        if m and m.group(2).lower() == "endsub":
            cur = None
            continue
        if cur is None and seen_end and FANUC_SUB_RE.match(ln):
            cur, cur_kind = "P" + str(int(FANUC_SUB_RE.match(ln).group(1))), "fanuc"
            subs[cur] = []
            continue
        if cur is not None:
            if cur_kind == "fanuc" and re.search(r"\bM99\b", ln, re.I):
                cur = None
                continue
            subs[cur].append(ln)
            continue
        if re.search(r"\bM(?:30|0?2)\b", ln, re.I):
            seen_end = True
        main.append(ln)

    def inline(block, depth):
        out = []
        for ln in block:
            m = LCNC_RE.match(ln)
            f = FANUC_CALL_RE.search(ln)
            key, reps = None, 1
            if m and m.group(2).lower() == "call":
                key = "o" + m.group(1)
            elif f:
                p = f.group(1)
                key = "P" + str(int(p[-4:]) if len(p) > 4 else int(p))
                reps = int(f.group(2)) if f.group(2) else (int(p[:-4]) if len(p) > 4 else 1)
            if key and key in subs and depth < 5:
                notes.append(f"Subprogram {key.lstrip('P')} expanded")
                for _ in range(reps):
                    out += inline(subs[key], depth + 1)
                continue
            out.append(ln)
        return out

    if not subs:
        return text
    return "\n".join(inline(main, 0))


def parse(text: str, chord_tol: float = 0.05) -> ParseResult:
    res = ParseResult()
    notes = []
    text = expand_subprograms(text, notes)
    res.notes = sorted(set(notes))
    if sum(bool(c.search(text.upper())) for c in LATHE_CUES) >= 2:
        res.warn("Looks like a lathe (turning) program: milling reconstruction is not meaningful")
    pos = [0.0, 0.0, 50.0]         # assume tool starts clear above the part
    motion = 0
    inch = False
    incremental = False
    feed = 0.0
    spindle = 0.0
    tool = 0
    pending_tool = None
    retract_initial = True       # G98 (initial plane) vs G99 (R plane)
    cyc = {}                     # modal canned-cycle words
    comp_active = False

    def u(v):
        return v * INCH if inch else v

    def emit(target, kind, arc=False):
        if any(abs(a - b) > 1e-9 for a, b in zip(pos, target)):
            res.segments.append(Segment(tuple(pos), tuple(target), kind, tool,
                                        feed if kind == "feed" else 0.0,
                                        spindle, lineno, arc))
            pos[:] = target

    lines = text.splitlines()
    res.n_lines = len(lines)
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line == "%":
            continue
        comments = COMMENT_RE.findall(line)
        if ";" in line:
            line, _, c = line.partition(";")
            comments.append(c)
        code = COMMENT_RE.sub(" ", line).upper()
        if line.startswith("/"):
            res.warn("Block-delete lines (/) present; executed as normal lines")
            code = code[1:]
        if MACRO_RE.search(code):
            res.warn("Macro variables / control flow (#, IF, WHILE) not executed; geometry may be incomplete")
            continue

        words = WORD_RE.findall(code)
        line_t = next((int(float(n)) for l, n in words if l == "T"), None)
        if line_t is None and "G20" in code:
            inch = True
        for c in comments:
            n, d, k = _parse_tool_comment(c, inch)
            # only a comment that names its tool, or sits on the tool-change line,
            # describes a tool; free-text notes like "(POCKET: 10 MM END MILL)" do not
            tn = n if n is not None else line_t
            if tn is not None and (d is not None or k is not None):
                info = res.tools.setdefault(tn, ToolInfo(tn))
                if d is not None:
                    info.diameter, info.source = d, "comment"
                if k is not None:
                    info.kind = k
        if not words:
            continue
        g_codes, m_codes, vals = [], [], {}
        for letter, num in words:
            if letter == "G":
                g_codes.append(float(num))
            elif letter == "M":
                m_codes.append(int(float(num)))
            else:
                vals[letter] = float(num)

        new_motion = None
        for g in g_codes:
            gi = int(round(g))
            if abs(g - gi) > 1e-6:          # G91.1 etc.
                res.warn(f"Unsupported code G{g} ignored")
                continue
            if gi not in SUPPORTED_G:
                if gi in (18, 19):
                    res.warn("Non-XY plane (G18/G19) arcs approximated as straight lines")
                elif gi in (41, 42):
                    pass
                else:
                    res.warn(f"Unsupported code G{gi} ignored")
            if gi in (0, 1, 2, 3, 81, 82, 83):
                new_motion = gi
            elif gi == 80:
                new_motion = None
                motion = 0 if motion >= 80 else motion
                cyc = {}
            elif gi == 20:
                inch = True
                res.used_inch = True
            elif gi == 21:
                inch = False
            elif gi == 90:
                incremental = False
            elif gi == 91:
                incremental = True
                if not any(int(round(x)) == 28 for x in g_codes):   # "G91 G28 Z0" is just homing
                    res.used_incremental = True
            elif gi == 98:
                retract_initial = True
            elif gi == 99:
                retract_initial = False
            elif gi in (41, 42):
                comp_active = True
                res.warn("Controller-side cutter compensation (G41/G42): coordinates are part edge, "
                         "geometry approximate (offset by one tool radius)")
            elif gi == 40:
                comp_active = False
            elif gi == 28:
                emit([pos[0], pos[1], max(pos[2], 50.0)], "rapid")
        if re.match(r"^\s*O\d+\s+(CALL|SUB|ENDSUB)", code):
            res.warn("O-word subroutine not defined in this file; geometry may be incomplete")
            continue
        for m in m_codes:
            if m in (98, 99):
                res.warn("Subprogram calls (M98/M99) to programs outside this file not expanded; "
                         "geometry may be incomplete")
            elif m not in SUPPORTED_M:
                res.warn(f"Unsupported code M{m} ignored")
            if m == 5:
                spindle = 0.0
        if "S" in vals:
            spindle = vals["S"]
        if "F" in vals:
            feed = u(vals["F"])
        if "T" in vals:
            pending_tool = int(vals["T"])
            res.tools.setdefault(pending_tool, ToolInfo(pending_tool))
        if 6 in m_codes:
            if pending_tool is not None:
                tool = pending_tool
            res.tools.setdefault(tool, ToolInfo(tool))
            res.tool_order.append(tool)
            continue
        if any(m == 98 for m in m_codes):
            continue
        if new_motion is not None:
            motion = new_motion

        has_xyz = any(k in vals for k in "XYZ")
        if 53 in [int(round(g)) for g in g_codes] or 28 in [int(round(g)) for g in g_codes]:
            continue  # machine-coordinate / home moves: not part geometry

        if motion in (81, 82, 83):
            res.used_canned = True
            for k in ("Z", "R", "Q"):
                if k in vals:
                    cyc[k] = u(vals[k])
            if not (("X" in vals) or ("Y" in vals) or new_motion is not None):
                continue
            init_z = pos[2]
            if incremental:
                x = pos[0] + u(vals.get("X", 0.0))
                y = pos[1] + u(vals.get("Y", 0.0))
                r_plane = init_z + cyc.get("R", 0.0)
                z_bot = r_plane + cyc.get("Z", 0.0)
            else:
                x = u(vals["X"]) if "X" in vals else pos[0]
                y = u(vals["Y"]) if "Y" in vals else pos[1]
                r_plane = cyc.get("R", init_z)
                z_bot = cyc.get("Z", init_z)
            emit([x, y, init_z], "rapid")
            emit([x, y, r_plane], "rapid")
            if motion == 83 and cyc.get("Q"):
                res.pecks += max(0, int(math.ceil(abs(r_plane - z_bot) / abs(cyc["Q"]))) - 1)
            emit([x, y, z_bot], "feed")
            emit([x, y, init_z if retract_initial else r_plane], "rapid")
            continue

        if not has_xyz and not ("I" in vals or "J" in vals or "R" in vals):
            continue
        if incremental:
            target = [pos[0] + u(vals.get("X", 0.0)), pos[1] + u(vals.get("Y", 0.0)),
                      pos[2] + u(vals.get("Z", 0.0))]
        else:
            target = [u(vals["X"]) if "X" in vals else pos[0],
                      u(vals["Y"]) if "Y" in vals else pos[1],
                      u(vals["Z"]) if "Z" in vals else pos[2]]

        if motion == 0:
            emit(target, "rapid")
        elif motion == 1:
            emit(target, "feed")
        elif motion in (2, 3):
            res.used_arcs = True
            cw = motion == 2
            try:
                if "R" in vals:
                    center = arc_center_from_r(pos[0], pos[1], target[0], target[1], u(vals["R"]), cw)
                else:
                    center = (pos[0] + u(vals.get("I", 0.0)), pos[1] + u(vals.get("J", 0.0)))
                for p in linearize_arc(tuple(pos), tuple(target), center, cw, chord_tol):
                    emit(list(p), "feed", arc=True)
            except ValueError:
                res.warn("Malformed arc treated as straight line")
                emit(target, "feed")

    if comp_active:
        res.warn("Cutter compensation left active at end of program")
    # every tool that cut something should have an entry
    for s in res.segments:
        res.tools.setdefault(s.tool, ToolInfo(s.tool))
    return res


def parse_file(path, **kw) -> ParseResult:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return parse(f.read(), **kw)
