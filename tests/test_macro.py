import math

import pytest

from ncarch.gcode.macro import evaluate
from ncarch.gcode.parser import parse


def feeds(res):
    return [s for s in res.segments if s.kind == "feed"]


def test_expressions():
    p = {1: 2.0, "scale": 10.0}
    assert evaluate("[#1 * 3 + 1]", p) == pytest.approx(7.0)
    assert evaluate("[#<scale> * -2.5]", p) == pytest.approx(-25.0)
    assert evaluate("[COS[60] + SQRT[16]]", p) == pytest.approx(4.5)
    assert evaluate("[ATAN[1]/[1]]", p) == pytest.approx(45.0)
    assert evaluate("[#1 GT 1 AND #1 LT 3]", p) == 1.0
    assert evaluate("[7 MOD 3]", p) == pytest.approx(1.0)


def test_named_parameters_in_words():
    res = parse("#<s> = 2.0\nG0 X0 Y0 Z5\nG1 Z[#<s> * -1.5] F100\nG1 X[#<s>*10]\n")
    assert feeds(res)[-1].end == pytest.approx((20, 0, -3))


def test_linuxcnc_repeat_and_polar_spiral():
    res = parse("G21 G90\nG0 X10 Y0 Z1\nG1 Z-1 F100\no100 repeat [4]\nG91 G1 @-1 ^90\no100 endrepeat\nG90\n")
    pts = [s.end for s in feeds(res)][1:]
    assert len(pts) == 4
    for k, (x, y, _) in enumerate(pts, start=1):
        r, a = math.hypot(x, y), math.degrees(math.atan2(y, x)) % 360
        assert r == pytest.approx(10 - k, abs=1e-6)
        diff = (a - 90 * k + 180) % 360 - 180          # angular difference, wraps 359.999 -> 0
        assert diff == pytest.approx(0, abs=1e-6)


def test_polar_canned_cycle_with_repeat_count():
    # LinuxCNC hole-circle idiom: six holes, 60 degrees apart
    res = parse("G21 G17 G90\nG0 X40 Y0 Z0\nG91 G81 R2 Z-12 ^60 L6 F100\n")
    holes = [s.end[:2] for s in feeds(res)]
    assert len(holes) == 6
    for x, y in holes:
        assert math.hypot(x, y) == pytest.approx(40, abs=1e-6)


def test_fanuc_while_bolt_circle():
    prog = """G21 G90
T4 M06 (T4 D6.8 DRILL)
G0 X0 Y0 Z10.
#1=6
#2=40.
#3=0
WHILE[#3LT#1]DO1
#4=#3*360/#1
G81 X[#2*COS[#4]] Y[#2*SIN[#4]] Z-12. R2. F150
#3=#3+1
END1
G80
"""
    res = parse(prog)
    holes = [s.end[:2] for s in feeds(res)]
    assert len(holes) == 6
    assert holes[1] == pytest.approx((20.0, 40 * math.sin(math.radians(60))), abs=1e-6)
    assert not any("Macro" in w for w in res.warnings)


def test_linuxcnc_sub_with_arguments_and_if():
    prog = """G21 G90
o100 sub
  o110 if [#2 GT 0]
    G0 X#1 Y0 Z1
    G1 Z[-#2] F100
    G0 Z1
  o110 endif
o100 endsub
o100 call [5] [3]
o100 call [9] [0]
o100 call [12] [4]
"""
    res = parse(prog)
    bottoms = [s.end for s in feeds(res)]
    assert bottoms == [pytest.approx((5, 0, -3)), pytest.approx((12, 0, -4))]


def test_undefined_external_sub_is_flagged():
    res = parse("G0 X0 Y0 Z1\no<probe> call\nG1 Z-1 F100\n")
    assert any("could not be executed" in w for w in res.warnings)
