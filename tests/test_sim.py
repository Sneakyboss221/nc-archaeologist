import pytest

from ncarch.gcode.parser import parse
from ncarch.sim.stock import simulate
from ncarch.sim.tools import resolve_tools

POCKET = """G21 G90
T1 M6 (T1 D4.0 FLAT)
G0 X3 Y3 Z5
G1 Z-2 F100
"""


def run(prog, res=0.1):
    pr = parse(prog)
    tools = resolve_tools(pr)
    return pr, tools, simulate(pr.segments, tools, res=res)


def _pocket_program():
    # 10 x 10 pocket with a 4 mm cutter: tool centre covers [2, 8]^2
    lines = [POCKET]
    y = 2.0
    while y <= 8.0 + 1e-9:
        lines.append(f"G1 X2 Y{y:.3f}\nG1 X8 Y{y:.3f}")
        y += 1.0
    lines.append("G1 X8 Y2\nG1 X2 Y2\nG1 X2 Y8\nG1 X8 Y8\nG1 X8 Y2\nG0 Z5\n")
    return "\n".join(lines)


def test_pocket_volume():
    _, _, stock = run(_pocket_program())
    # sharp-cornered 10x10x2 pocket minus four R2 corner fillets
    fillet = (4 - 3.14159265) * 4 * 2   # 4 corners * (R^2 - pi R^2/4) * depth
    expected = 10 * 10 * 2 - fillet
    vol = stock.blocks[0]["volume"]
    assert vol == pytest.approx(expected, rel=0.02)


def test_drill_cone():
    _, tools, stock = run("T2 M6 (T2 D6 DRILL)\nG0 X0 Y0 Z5\nG1 Z-10 F50\nG0 Z5\n")
    assert tools[2]["kind"] == "drill"
    assert stock.Z.min() == pytest.approx(-10, abs=0.05)


def test_stepover_inference():
    prog = "T5 M6\nG0 X0 Y0 Z5\nG1 Z-1 F200\n"
    for i in range(8):        # zig-zag at 5 mm spacing -> 10 mm cutter
        y = i * 5
        prog += f"G1 X40 Y{y}\nG1 Y{y + 5}\n" if i % 2 == 0 else f"G1 X0 Y{y}\nG1 Y{y + 5}\n"
    pr = parse(prog)
    tools = resolve_tools(pr)
    assert tools[5]["source"] == "inferred"
    assert tools[5]["diameter"] == 10
