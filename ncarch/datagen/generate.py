"""Build the synthetic benchmark: N programs per family, mixed dialects and setups.

    python -m ncarch.datagen.generate data --per-family 75 --seed 7

Writes data/programs/O####.nc (names carry no family information) and
data/gt/O####.json (ground truth, used only for evaluation).
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from .cam import plan
from .families import FAMILIES, make_spec
from .post import STYLES, post


def setup_transform(spec, rng):
    """Random fixturing: rotation on the table and work-offset origin."""
    r = rng.random()
    if r < 0.5:
        theta = 0.0
    elif r < 0.75:
        theta = float(rng.choice([0.5, 1.0, 1.5])) * math.pi
    else:
        theta = float(rng.uniform(0, 2 * math.pi))
    c, s = math.cos(theta), math.sin(theta)
    hw, hh = spec["stock_w"] / 2, spec["stock_h"] / 2
    corners = [(c * x - s * y, s * x + c * y) for x in (-hw, hw) for y in (-hh, hh)]
    if rng.random() < 0.5:        # zero at the stock centre
        ox, oy = 0.0, 0.0
    else:                         # zero at the lower-left corner of the stock
        ox, oy = -min(p[0] for p in corners), -min(p[1] for p in corners)
    return theta, ox + float(rng.uniform(-3, 3)), oy + float(rng.uniform(-3, 3))


def generate_one(family, style, rng, part_no):
    spec = make_spec(family, rng)
    ops, cam_params = plan(spec, rng)
    theta, ox, oy = setup_transform(spec, rng)
    text, tool_table = post(ops, style, rng, theta, ox, oy, part_no)
    profile_d = next((o["tool_d"] for o in ops if o["name"] == "profile"), None)
    gt = dict(family=family, style=style, spec=spec, theta=theta, ox=ox, oy=oy,
              tools=tool_table, profile_tool_d=profile_d, cam=cam_params,
              ops=[dict(name=o["name"], kind=o["kind"], tool_d=o["tool_d"]) for o in ops])
    return text, gt


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--per-family", type=int, default=75)
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    rng = np.random.default_rng(a.seed)
    out = Path(a.out)
    (out / "programs").mkdir(parents=True, exist_ok=True)
    (out / "gt").mkdir(parents=True, exist_ok=True)
    jobs = [(f, STYLES[i % len(STYLES)]) for f in FAMILIES for i in range(a.per_family)]
    numbers = rng.permutation(np.arange(1000, 1000 + 8 * len(jobs)))[:len(jobs)]
    order = rng.permutation(len(jobs))
    for k, idx in enumerate(order):
        fam, style = jobs[idx]
        part_no = int(numbers[k])
        text, gt = generate_one(fam, style, rng, part_no)
        name = f"O{part_no}"
        (out / "programs" / f"{name}.nc").write_text(text)
        (out / "gt" / f"{name}.json").write_text(json.dumps(gt, indent=1))
    print(f"wrote {len(jobs)} programs to {out / 'programs'}")


if __name__ == "__main__":
    main()
