"""Write paper/numbers.tex from results/metrics.json so that every number in the
paper comes straight from the experiment output (no hand-typed results).

    python -m experiments.make_numbers
"""
from __future__ import annotations

import json
from pathlib import Path

M = json.loads(Path("results/metrics.json").read_text())
out = []


def cmd(name, value, fmt="{:.2f}"):
    v = value if isinstance(value, str) else fmt.format(value)
    out.append(f"\\newcommand{{\\{name}}}{{{v}}}")


def pct(x):
    return f"{100 * x:.1f}\\%"


ds = M["dataset"]
cmd("NProg", ds["n_programs"], "{:d}")
cmd("NFam", ds["families"], "{:d}")
cmd("NFailed", len(ds["failed"]), "{:d}")

R = M["reconstruction"]["summary"]
for tag, key in (("All", "all"), ("Known", "tools_from_comments"), ("Inf", "tools_inferred")):
    r = R[key]
    cmd(f"Rec{tag}N", r["n"], "{:d}")
    cmd(f"Rec{tag}RMS", r["rms_mm"])
    cmd(f"Rec{tag}MedRMS", r["median_rms_mm"])
    cmd(f"Rec{tag}IoU", r["iou"], "{:.3f}")
    cmd(f"Rec{tag}HoleRec", pct(r["hole_recall"]))
    cmd(f"Rec{tag}HolePrec", pct(r["hole_precision"]))
    cmd(f"Rec{tag}HoleD", r["hole_diam_mae_mm"])
    cmd(f"Rec{tag}HolePos", r["hole_pos_mae_mm"])
cmd("RunMean", M["reconstruction"]["runtime_mean_s"])
cmd("RunPNF", M["reconstruction"]["runtime_p95_s"])

F = M["families"]
names = dict(text_tfidf_raw="TextRaw", text_tfidf_codes="TextCodes", process_only="Proc",
             geometry_only="Geo", full="Full")
for k, n in names.items():
    for m in ("ari", "nmi", "purity", "p_at_5", "mAP"):
        cmd(f"{n}{m.replace('_', '').replace('5', 'five').upper()}", F[k][m], "{:.3f}")
cmd("TextRawDialect", F["text_tfidf_raw"]["ari_vs_dialect"], "{:.3f}")
cmd("TextCodesDialect", F["text_tfidf_codes"]["ari_vs_dialect"], "{:.3f}")
full = F["full"]
cmd("FullKAuto", full["k_auto"], "{:d}")
cmd("FullARIAuto", full["ari_auto"], "{:.3f}")
cmd("FullHDBARI", full["hdbscan_ari_inliers"], "{:.3f}")
cmd("FullHDBOut", pct(full["hdbscan_outlier_frac"]))
cmd("FullHDBK", full["hdbscan_k"], "{:d}")
cmd("CrossDialectPrec", pct(full["cross_dialect_neighbour_precision"]))
cmd("CrossDialectShare", pct(full["cross_dialect_neighbour_share"]))

T = M["tool_inference"]
cmd("TINTools", T["milling_tools"], "{:d}")
cmd("TICoverage", pct(T["coverage"]))
cmd("TIExact", pct(T["exact_of_inferred"]))
cmd("TIOneSize", pct(T["within_one_size_of_inferred"]))

D = M["dialect_invariance"]
cmd("DINParts", D["n_parts"], "{:d}")
cmd("DINProgs", D["n_programs"], "{:d}")
cmd("DISamePart", D["sim_same_part"], "{:.3f}")
cmd("DISameFam", D["sim_same_family"], "{:.3f}")
cmd("DIOther", D["sim_other_family"], "{:.3f}")
cmd("DIDesc", pct(D["identical_description_rate"]))

for res, tag in (("0.5", "Coarse"), ("0.25", "Mid"), ("0.1", "Fine")):
    r = M["resolution"][res]
    cmd(f"Res{tag}RMS", r["rms_mm"])
    cmd(f"Res{tag}IoU", r["iou"], "{:.3f}")
    cmd(f"Res{tag}Time", r["runtime_per_program_s"])
    cmd(f"Res{tag}HoleD", r["hole_diam_mae_mm"] or 0.0)

# feature recognition table rows
rows = []
for t, v in M["reconstruction"]["features"].items():
    if v["tp"] + v["fn"] == 0:
        continue
    rows.append(f"{t.replace('_', ' ')} & {v['tp'] + v['fn']} & {v['precision']:.3f} & {v['recall']:.3f} \\\\")
out.append("\\newcommand{\\FeatureRows}{" + "\n".join(rows) + "}")

# hand-written programs table rows
hw = []
for r in M.get("handwritten", []):
    f = r["file"].removesuffix(".nc").replace("_", "\\_\\allowbreak ")
    if "error" in r:
        hw.append(f"\\texttt{{{f}}} & rejected: {r['error'][:40]} \\\\")
        continue
    w = "; ".join(x.split(":")[0].split("(")[0].strip() for x in r["warnings"][:2]) or "none"
    hw.append(f"\\texttt{{{f}}} ({r['lines']} lines) & {r['description'].replace('Ø', '$\\varnothing$')} "
              f"\\newline \\footnotesize{{warnings: {w}}} \\\\")
out.append("\\newcommand{\\HandRows}{" + "\n".join(hw) + "}")

Path("paper/numbers.tex").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"wrote paper/numbers.tex ({len(out)} macros)")
