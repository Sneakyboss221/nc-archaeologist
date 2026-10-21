"""Real-world check on openly licensed programs from the LinuxCNC project (GPL-2.0).

    python -m experiments.real_world

These programs were not produced by our generator. Each one is run through the
full pipeline. Results go to results/real_world.json and a figure to
paper/figs/real_world.{pdf,png}. The `expected` column is taken from each
file's own comments, so the check needs no ground truth of ours.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ncarch.pipeline import analyze_text

SRC = Path("data_real/linuxcnc")

# what each file says it is (from its header comments), and what to check
EXPECTED = {
    "3D_Chips.ngc": "3D carving of a 100x100x50 mm block with a 10 mm ball-nose cutter",
    "arcspiral.ngc": "engraved arc spiral (inch)",
    "cds.ngc": "'Circle Diamond Square' test part on 4x4x2 in stock (stock top at Z=2 in)",
    "comp-g1.ngc": "cutter-compensation demo, tool defined only in the controller's tool table",
    "daisy.ngc": "macro-generated daisy pattern (o-word subroutine with arguments)",
    "g881.ngc": "remap subroutine for a custom G81 (not a part program)",
    "gmoccapy_2_tools_with_cutter_radius_compensation.ngc": "two circles milled with cutter compensation, two tools",
    "hole-circle.ngc": "6 bolt holes on a 3 in (76.2 mm) circle, polar coordinates + L repeat",
    "lathe_pawn.ngc": "lathe program (chess pawn): should be flagged, not milled",
    "mmount.ngc": "stepper-motor mount, multi-station fixture (G55-G57), macros",
    "polar.ngc": "3 + 1 + 5 + 17 = 26 holes using polar coordinates",
    "skeleton.ngc": "empty program template (no cutting moves)",
    "spiral.ngc": "spiral engraving, o-word repeat loop of 800 polar steps",
    "tort.ngc": "LinuxCNC interpreter torture test (random arcs/lines, not a real part)",
    "x-trim.ngc": "plasma trim, requires external subroutine touchoff.ngc",
}
FIGURE = ["3D_Chips.ngc", "mmount.ngc", "cds.ngc", "polar.ngc", "hole-circle.ngc", "spiral.ngc"]


def main():
    rows, stocks = [], {}
    for p in sorted(SRC.glob("*.ngc")):
        row = dict(file=p.name, expected=EXPECTED.get(p.name, ""), lines=len(p.read_text(errors="replace").splitlines()))
        try:
            rec, stock = analyze_text(p.read_text(errors="replace"), p.stem, keep_stock=True)
            stocks[p.name] = (stock, rec)
            row.update(status="analysed", moves=rec["n_segments"], description=rec["description"],
                       operations=[r["operation"] for r in rec["process"]], notes=rec["notes"],
                       warnings=[w for w in rec["warnings"] if "diameter unknown" not in w],
                       default_tools=sum("diameter unknown" in w for w in rec["warnings"]),
                       runtime_s=rec["runtime_s"])
        except Exception as e:
            row.update(status="rejected", reason=f"{type(e).__name__}: {e}")
        rows.append(row)
        print(f"{p.name:55s} {row['status']:9s} {row.get('description', row.get('reason', ''))[:80]}")
    Path("results").mkdir(exist_ok=True)
    commit = (SRC / ".source_commit").read_text().strip() if (SRC / ".source_commit").exists() else ""
    summary = dict(source="LinuxCNC nc_files (GPL-2.0)", commit=commit, n=len(rows),
                   analysed=sum(r["status"] == "analysed" for r in rows),
                   with_macros_executed=sum(any("Macro program executed" in n for n in r.get("notes", [])) for r in rows),
                   flagged=sum(bool(r.get("warnings")) for r in rows), rows=rows)
    Path("results/real_world.json").write_text(json.dumps(summary, indent=2))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 7, "font.family": "serif"})
    fig, axs = plt.subplots(2, 3, figsize=(7.16, 4.3))
    for ax, name in zip(axs.flat, FIGURE):
        stock, rec = stocks[name]
        D = stock.depth()
        ext = [stock.x0, stock.x0 + D.shape[1] * stock.res, stock.y0, stock.y0 + D.shape[0] * stock.res]
        ax.imshow(D, origin="lower", extent=ext, cmap="viridis")
        ax.set_title(name.replace(".ngc", ""), fontsize=8)
        ax.set_xticks([]), ax.set_yticks([])
        desc = rec["description"]
        ax.set_xlabel(desc if len(desc) < 46 else desc[:44] + "…", fontsize=6)
    fig.tight_layout()
    Path("paper/figs").mkdir(parents=True, exist_ok=True)
    fig.savefig("paper/figs/real_world.pdf"), fig.savefig("paper/figs/real_world.png", dpi=200)
    print(f"analysed {summary['analysed']}/{summary['n']}; macros executed in {summary['with_macros_executed']}")


if __name__ == "__main__":
    main()
