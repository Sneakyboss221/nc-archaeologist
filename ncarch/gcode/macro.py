"""Parametric / macro G-code: expand to plain G-code before interpretation.

Supports LinuxCNC (RS274NGC) and Fanuc Macro B style programming:
  - numbered and named parameters: #1, #100, #<name>; assignments `#1 = [#2 * 3]`
  - expressions in brackets with + - * / ** MOD, EQ NE GT GE LT LE, AND OR XOR,
    SIN COS TAN ASIN ACOS ATAN(ATAN[y]/[x]) SQRT ABS ROUND FIX FUP LN EXP EXISTS
  - LinuxCNC o-words: sub / endsub / call [args] / return, if / elseif / else / endif,
    while / endwhile, do / while, repeat / endrepeat, break / continue
  - Fanuc: WHILE [cond] DOn ... ENDn, IF [cond] GOTOn, IF [cond] THEN #x = ..., GOTOn

The result is a list of plain lines (parameters substituted by numbers) that the
modal interpreter in parser.py reads as usual.
"""
from __future__ import annotations

import math
import re

MAX_STEPS = 3_000_000


class MacroError(Exception):
    pass


# ------------------------------------------------------------------ expressions
TOKEN_RE = re.compile(r"\s*(?:(\d+\.?\d*|\.\d+)|(#<[^>]+>)|(#)|(\*\*|[-+*/\[\]])|([A-Z_]+))", re.I)
FUNCS = {
    "SIN": lambda a: math.sin(math.radians(a)), "COS": lambda a: math.cos(math.radians(a)),
    "TAN": lambda a: math.tan(math.radians(a)), "ASIN": lambda a: math.degrees(math.asin(a)),
    "ACOS": lambda a: math.degrees(math.acos(a)), "SQRT": math.sqrt, "ABS": abs,
    "ROUND": lambda a: float(round(a)), "FIX": math.floor, "FUP": math.ceil,
    "LN": math.log, "EXP": math.exp,
}
BINARY = [  # (precedence, operators)
    (1, {"AND", "OR", "XOR"}),
    (2, {"EQ", "NE", "GT", "GE", "LT", "LE"}),
    (3, {"+", "-"}),
    (4, {"*", "/", "MOD"}),
    (5, {"**"}),
]


class Expr:
    def __init__(self, text, params):
        self.toks = []
        pos = 0
        text = text.strip()
        while pos < len(text):
            m = TOKEN_RE.match(text, pos)
            if not m or m.end() == pos:
                raise MacroError(f"cannot parse expression near '{text[pos:pos + 12]}'")
            num, named, hash_, op, word = m.groups()
            if num is not None:
                self.toks.append(("num", float(num)))
            elif named:
                self.toks.append(("name", named[2:-1].strip().lower().replace(" ", "")))
            elif hash_:
                self.toks.append(("#", None))
            elif op:
                self.toks.append(("op", op))
            else:
                self.toks.append(("word", word.upper()))
            pos = m.end()
        self.i = 0
        self.params = params

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def value(self):
        v = self.binary(1)
        if self.i != len(self.toks):
            raise MacroError("unexpected text after expression")
        return v

    def binary(self, level):
        if level > 5:
            return self.unary()
        left = self.binary(level + 1)
        ops = BINARY[level - 1][1]
        while True:
            kind, v = self.peek()
            if kind in ("op", "word") and v in ops:
                self.take()
                right = self.binary(level + 1)
                left = apply(v, left, right)
            else:
                return left

    def unary(self):
        kind, v = self.peek()
        if kind == "op" and v in "+-":
            self.take()
            x = self.unary()
            return -x if v == "-" else x
        return self.atom()

    def atom(self):
        kind, v = self.take()
        if kind == "num":
            return v
        if kind == "op" and v == "[":
            x = self.binary(1)
            if self.take() != ("op", "]"):
                raise MacroError("missing ]")
            return x
        if kind == "#":
            return self.params.get(round(self.atom()), 0.0)
        if kind == "name":
            if v not in self.params:
                raise MacroError(f"undefined parameter #<{v}>")
            return self.params[v]
        if kind == "word":
            if v == "EXISTS":
                self.take()                                   # [
                k, name = self.take()
                self.take()                                   # ]
                return 1.0 if k == "name" and name in self.params else 0.0
            if v == "ATAN":
                y = self.atom()
                if self.take() != ("op", "/"):
                    raise MacroError("ATAN needs [y]/[x]")
                return math.degrees(math.atan2(y, self.atom()))
            if v in FUNCS:
                return float(FUNCS[v](self.atom()))
        raise MacroError(f"unexpected token {v!r}")


OPS = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
       "/": lambda a, b: a / b if b else math.inf, "**": lambda a, b: a ** b,
       "MOD": lambda a, b: math.fmod(a, b) if b else 0.0,
       "EQ": lambda a, b: float(abs(a - b) < 1e-9), "NE": lambda a, b: float(abs(a - b) >= 1e-9),
       "GT": lambda a, b: float(a > b), "GE": lambda a, b: float(a >= b),
       "LT": lambda a, b: float(a < b), "LE": lambda a, b: float(a <= b),
       "AND": lambda a, b: float(bool(a) and bool(b)), "OR": lambda a, b: float(bool(a) or bool(b)),
       "XOR": lambda a, b: float(bool(a) != bool(b))}


def apply(op, a, b):
    return OPS[op](a, b)   # evaluate only the requested operator


def evaluate(text, params):
    return Expr(text, params).value()


# ------------------------------------------------------------------ helpers
COMMENT_RE = re.compile(r"\([^)]*\)")
O_RE = re.compile(r"^\s*O\s*(<[^>]+>|\d+)\s*(SUB|ENDSUB|CALL|RETURN|IF|ELSEIF|ELSE|ENDIF|WHILE|ENDWHILE|DO|"
                  r"REPEAT|ENDREPEAT|BREAK|CONTINUE)\b(.*)$", re.I)
ASSIGN_RE = re.compile(r"#\s*(<[^>]+>|\d+|\[[^\]]*\])\s*=\s*")
F_WHILE_RE = re.compile(r"^\s*(?:N\d+\s*)?WHILE\s*(\[.*\])\s*DO\s*(\d+)\s*$", re.I)
F_END_RE = re.compile(r"^\s*(?:N\d+\s*)?END\s*(\d+)\s*$", re.I)
F_IF_RE = re.compile(r"^\s*(?:N\d+\s*)?IF\s*(\[.*\])\s*(GOTO\s*(\d+)|THEN\s*(.*))\s*$", re.I)
F_GOTO_RE = re.compile(r"^\s*(?:N\d+\s*)?GOTO\s*(\d+)\s*$", re.I)
N_RE = re.compile(r"^\s*N(\d+)", re.I)


def needs_macro(text):
    up = COMMENT_RE.sub("", text).upper()
    return ("#" in up or "[" in up or "WHILE" in up        # parameters, bracket expressions, Fanuc loops
            or bool(re.search(r"^[ \t]*O[ \t]*(<[^>]+>|\d+)[ \t]+(SUB|CALL|IF|WHILE|DO|REPEAT)\b", up, re.M)))


def _bracket_end(s, i):
    """Index just past the bracket expression starting at s[i] == '['."""
    depth = 0
    for k in range(i, len(s)):
        if s[k] == "[":
            depth += 1
        elif s[k] == "]":
            depth -= 1
            if depth == 0:
                return k + 1
    raise MacroError("unbalanced brackets")


def _param_ref_end(s, i):
    """End of a parameter reference starting at s[i] == '#'."""
    j = i + 1
    while j < len(s) and s[j] == " ":
        j += 1
    if j < len(s) and s[j] == "<":
        return s.index(">", j) + 1
    if j < len(s) and s[j] == "[":
        return _bracket_end(s, j)
    if j < len(s) and s[j] == "#":
        return _param_ref_end(s, j)
    m = re.match(r"\d+", s[j:])
    if not m:
        raise MacroError("bad parameter reference")
    return j + m.end()


def substitute(code, params):
    """Replace every bracket expression / parameter reference by its value."""
    out, i = [], 0
    while i < len(code):
        c = code[i]
        if c == "[":
            j = _bracket_end(code, i)
            out.append(_fmt(evaluate(code[i:j], params)))
            i = j
        elif c == "#":
            j = _param_ref_end(code, i)
            out.append(_fmt(evaluate(code[i:j], params)))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _fmt(v):
    return f"{v:.6f}".rstrip("0").rstrip(".") if abs(v) < 1e9 else "0"


def _split_args(rest):
    args, i = [], 0
    rest = rest.strip()
    while i < len(rest):
        if rest[i] == "[":
            j = _bracket_end(rest, i)
            args.append(rest[i:j])
            i = j
        else:
            i += 1
    return args


# ------------------------------------------------------------------ executor
def execute(text, notes):
    """Run the macro layer; returns plain G-code lines. Raises MacroError on failure."""
    lines = text.splitlines()
    code = [COMMENT_RE.sub("", ln.split(";")[0]).strip() for ln in lines]

    # structure maps for o-words, keyed by (label, keyword)
    subs, match = {}, {}
    stack = []
    for i, c in enumerate(code):
        m = O_RE.match(c)
        if not m:
            continue
        label, kw = m.group(1).lower().replace(" ", ""), m.group(2).upper()
        if kw in ("SUB", "IF", "WHILE", "DO", "REPEAT"):
            if kw == "WHILE" and stack and stack[-1][0] == label and stack[-1][1] == "DO":
                do_i = stack.pop()[2]
                match[do_i] = i
                match[i] = do_i                               # do ... while
                continue
            stack.append((label, kw, i, []))
            if kw == "SUB":
                subs[label] = i
        elif kw in ("ELSEIF", "ELSE"):
            if stack and stack[-1][0] == label:
                stack[-1][3].append(i)
        elif kw in ("ENDSUB", "ENDIF", "ENDWHILE", "ENDREPEAT"):
            while stack and stack[-1][0] != label:
                stack.pop()
            if not stack:
                continue
            _, okw, start, branches = stack.pop()
            match[start] = i
            match[i] = start
            for b in branches:
                match[b] = i
            if okw == "IF":
                match[(start, "branches")] = branches
    # Fanuc WHILE/DO n ... END n
    fstack = {}
    for i, c in enumerate(code):
        if (m := F_WHILE_RE.match(c)):
            fstack.setdefault(m.group(2), []).append(i)
        elif (m := F_END_RE.match(c)) and fstack.get(m.group(1)):
            w = fstack[m.group(1)].pop()
            match[w] = i
            match[i] = w
    labels = {}
    for i, c in enumerate(code):
        if (m := N_RE.match(c)):
            labels.setdefault(int(m.group(1)), i)

    params = {}
    out = []
    frames = []
    repeat_count = {}
    pc, steps, loops = 0, 0, 0
    used = False

    def jump_after(i):
        return match[i] + 1

    while pc < len(code):
        steps += 1
        if steps > MAX_STEPS:
            raise MacroError("execution limit reached (infinite loop?)")
        c = code[pc]
        m = O_RE.match(c)
        if m:
            used = True
            label, kw, rest = m.group(1).lower().replace(" ", ""), m.group(2).upper(), m.group(3)
            if kw == "SUB":
                pc = jump_after(pc) if pc in match else pc + 1        # definitions are skipped
                continue
            if kw in ("ENDSUB", "RETURN"):
                if not frames:
                    pc += 1
                    continue
                pc, saved = frames.pop()
                for k in range(1, 31):
                    params[k] = saved.get(k, 0.0)
                continue
            if kw == "CALL":
                if label not in subs:
                    raise MacroError(f"subroutine o{label} is defined in another file")
                args = [evaluate(a, params) for a in _split_args(rest)]
                frames.append((pc + 1, {k: params.get(k, 0.0) for k in range(1, 31)}))
                for k in range(1, 31):
                    params[k] = args[k - 1] if k <= len(args) else 0.0
                pc = subs[label] + 1
                continue
            if kw == "IF":
                branches = [pc] + match.get((pc, "branches"), [])
                pc = match[pc]                                       # default: endif
                for b in branches:
                    bm = O_RE.match(code[b])
                    bkw = bm.group(2).upper()
                    if bkw == "ELSE" or evaluate(bm.group(3), params):
                        pc = b + 1
                        break
                continue
            if kw in ("ELSEIF", "ELSE"):
                pc = match.get(pc, pc) + 1 if pc in match else pc + 1
                continue
            if kw == "WHILE":
                if pc in match and match[pc] < pc:                   # end of do...while
                    pc = match[pc] + 1 if evaluate(rest, params) else pc + 1
                    loops += 1
                    continue
                if evaluate(rest, params):
                    pc += 1
                else:
                    pc = jump_after(pc)
                continue
            if kw == "ENDWHILE":
                pc = match[pc]
                loops += 1
                continue
            if kw == "REPEAT":
                if pc not in repeat_count:
                    repeat_count[pc] = int(evaluate(rest, params))
                if repeat_count[pc] <= 0:
                    del repeat_count[pc]
                    pc = jump_after(pc)
                else:
                    repeat_count[pc] -= 1
                    pc += 1
                continue
            if kw == "ENDREPEAT":
                pc = match[pc]
                loops += 1
                continue
            if kw in ("BREAK", "CONTINUE"):
                raise MacroError("break/continue not supported")
            pc += 1
            continue

        if (m := F_WHILE_RE.match(c)):
            used = True
            pc = pc + 1 if evaluate(m.group(1), params) else jump_after(pc)
            continue
        if F_END_RE.match(c) and pc in match:
            pc = match[pc]
            loops += 1
            continue
        if (m := F_IF_RE.match(c)):
            used = True
            if evaluate(m.group(1), params):
                if m.group(3):
                    pc = labels[int(m.group(3))]
                    continue
                c = m.group(4)
            else:
                pc += 1
                continue
        elif (m := F_GOTO_RE.match(c)):
            pc = labels[int(m.group(1))]
            continue

        # assignments (possibly several on one line), then the remaining words
        if "#" in c:
            used = True
            pieces = list(ASSIGN_RE.finditer(c))
            if pieces and pieces[0].start() == len(c) - len(c.lstrip()):
                for k, a in enumerate(pieces):
                    end = pieces[k + 1].start() if k + 1 < len(pieces) else len(c)
                    target = a.group(1)
                    value = evaluate(c[a.end():end], params)
                    if target.startswith("<"):
                        params[target[1:-1].strip().lower().replace(" ", "")] = value
                    else:
                        params[round(evaluate(target, params) if target.startswith("[") else float(target))] = value
                pc += 1
                continue
        if "[" in c or "#" in c:
            used = True
            line = substitute(c, params)
            comments = " ".join(f"({x})" for x in re.findall(r"\(([^)]*)\)", lines[pc]))
            out.append(f"{line} {comments}".strip())
        else:
            out.append(lines[pc])
        pc += 1

    if used:
        named = sum(isinstance(k, str) for k in params)
        notes.append(f"Macro program executed ({len(params)} parameters, {named} named; {loops} loop iterations)")
    return out
