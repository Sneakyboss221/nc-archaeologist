import math

import pytest

from ncarch.gcode.parser import parse


def ends(res, kind=None):
    return [s.end for s in res.segments if kind is None or s.kind == kind]


def test_absolute_and_incremental():
    res = parse("G21 G90\nG0 X10 Y10 Z5\nG91\nG1 X5 F100\nG1 Y-2\n")
    assert ends(res)[-1] == pytest.approx((15, 8, 5))
    assert res.used_incremental


def test_inch_conversion():
    res = parse("G20 G90\nG0 X1 Y2 Z0.1\nG1 Z-0.1 F10\n")
    assert ends(res)[-1] == pytest.approx((25.4, 50.8, -2.54))
    assert res.segments[-1].feed == pytest.approx(254.0)


def test_modal_motion_and_comments():
    res = parse("G0 X0 Y0 Z1 (rapid)\nG1 Z-1 F200 ; plunge\nX10\nY10\n")
    feeds = [s for s in res.segments if s.kind == "feed"]
    assert len(feeds) == 3
    assert feeds[-1].end == pytest.approx((10, 10, -1))


def test_arc_ij_quarter_circle():
    res = parse("G0 X10 Y0 Z0\nG3 X0 Y10 I-10 J0 F100\n")
    pts = [s.end for s in res.segments if s.arc]
    assert len(pts) >= 8
    for x, y, _ in pts:
        assert math.hypot(x, y) == pytest.approx(10, abs=0.06)
    assert pts[-1] == pytest.approx((0, 10, 0))


def test_arc_r_form_matches_ij():
    a = parse("G0 X10 Y0 Z0\nG2 X0 Y-10 R10 F100\n")
    for x, y, _ in [s.end for s in a.segments if s.arc]:
        assert math.hypot(x, y) == pytest.approx(10, abs=0.06)
        assert x >= -1e-6 and y <= 1e-6   # short CW arc stays in 4th quadrant


def test_full_circle():
    res = parse("G0 X5 Y0 Z-1\nG2 X5 Y0 I-5 J0 F100\n")
    pts = [s.end for s in res.segments if s.arc]
    xs = [p[0] for p in pts]
    assert min(xs) == pytest.approx(-5, abs=0.06)


def test_canned_cycle_g81_g98():
    res = parse("G0 X0 Y0 Z10\nG98 G81 X5 Y5 Z-8 R2 F100\nX15\nG80\n")
    plunges = [s for s in res.segments if s.kind == "feed"]
    assert len(plunges) == 2
    assert plunges[0].end == pytest.approx((5, 5, -8))
    assert plunges[1].end == pytest.approx((15, 5, -8))
    assert ends(res)[-1][2] == pytest.approx(10)   # back to initial plane


def test_g83_pecks_counted():
    res = parse("G0 X0 Y0 Z5\nG99 G83 X0 Y0 Z-10 R1 Q2 F80\nG80\n")
    assert res.pecks == 5


def test_tool_comment_and_change():
    res = parse("T3 M6 (T3 D8.0 FLAT ENDMILL)\nG0 X0 Y0 Z1\nG1 Z-1 F100\n")
    assert res.tools[3].diameter == pytest.approx(8.0)
    assert res.tools[3].kind == "flat"
    assert res.segments[-1].tool == 3
    assert res.tool_order == [3]


def test_inch_tool_comment():
    res = parse("G20\nT2 M6 (T2 0.25 IN DRILL)\n")
    assert res.tools[2].diameter == pytest.approx(6.35)
    assert res.tools[2].kind == "drill"


def test_section_comments_are_not_tool_definitions():
    res = parse("(--- POCKET: 10 MM END MILL ---)\nT1 M6 (T1 D50 FACE MILL)\n"
                "(NEXT: 8.5 MM DRILL)\nT2 M6\n")
    assert res.tools[1].diameter == pytest.approx(50.0)
    assert res.tools[1].kind == "face"
    assert res.tools[2].diameter is None


def test_warnings_for_unsupported_features():
    res = parse("G41 D1 G1 X10 F100\n#100=5\nM98 P1000\nG40\n")
    text = " ".join(res.warnings)
    assert "cutter compensation" in text.lower()
    assert "subprogram" in text.lower()
    assert any("Macro program executed" in n for n in res.notes)   # parameters are now executed
