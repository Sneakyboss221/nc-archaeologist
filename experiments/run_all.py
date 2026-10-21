"""All experiments for the paper. Every reported number is produced here.

    python -m experiments.run_all --data data_test --out out_test --results results

Expects `python -m ncarch.pipeline <data>/programs <out>` to have been run.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import HDBSCAN, AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score

from ncarch.datagen.cam import plan
from ncarch.datagen.families import FAMILIES, gt_depth, make_spec
from ncarch.datagen.generate import setup_transform
from ncarch.datagen.post import STYLES, post
from ncarch.families.cluster import build_matrix, choose_k, embed_2d
from ncarch.families.search import all_neighbours
from ncarch.gcode.parser import parse
from ncarch.pipeline import analyze_text
from ncarch.sim.stock import simulate
from ncarch.sim.tools import STANDARD_MM, resolve_tools

GT_TO_REC = dict(hole="hole", rect_pocket="pocket", circ_pocket="circular_pocket", slot="slot",
                 step="step", ring_pocket="pocket_island")


# ------------------------------------------------------------------ helpers
def load_gt(data, names):
    return [json.loads((Path(data) / "gt" / f"{n}.json").read_text()) for n in names]


def to_local(gt, X, Y):
    c, s = math.cos(-gt["theta"]), math.sin(-gt["theta"])
    dx, dy = X - gt["ox"], Y - gt["oy"]
    return c * dx - s * dy, s * dx + c * dy


def to_machine(gt, x, y):
    c, s = math.cos(gt["theta"]), math.sin(gt["theta"])
    return gt["ox"] + c * x - s * y, gt["oy"] + s * x + c * y


def purity(y, lab):
    tot = 0
    for c in np.unique(lab):
        tot += Counter(y[lab == c]).most_common(1)[0][1]
    return tot / len(y)


def retrieval(X, y, k=5):
    nb, _ = all_neighbours(X, k=len(X) - 1)
    p_at_k = float((y[nb[:, :k]] == y[:, None]).mean())
    aps = []
    for i in range(len(y)):
        rel = (y[nb[i]] == y[i]).astype(float)
        if rel.sum() == 0:
            continue
        prec = np.cumsum(rel) / (np.arange(len(rel)) + 1)
        aps.append(float((prec * rel).sum() / rel.sum()))
    return p_at_k, float(np.mean(aps))


def cluster_metrics(X, y, k_true):
    lab = AgglomerativeClustering(n_clusters=k_true, linkage="ward").fit_predict(X)
    k_auto, sil, lab_auto = choose_k(X)
    hdb = HDBSCAN(min_cluster_size=15, min_samples=5, copy=True).fit_predict(X)
    inl = hdb >= 0
    p5, mAP = retrieval(X, y)
    return dict(ari=adjusted_rand_score(y, lab), nmi=normalized_mutual_info_score(y, lab),
                purity=purity(y, lab), k_auto=int(k_auto), silhouette=float(sil),
                ari_auto=adjusted_rand_score(y, lab_auto),
                hdbscan_ari_inliers=adjusted_rand_score(y[inl], hdb[inl]) if inl.any() else 0.0,
                hdbscan_outlier_frac=float((~inl).mean()), hdbscan_k=int(len(set(hdb[inl]))),
                p_at_5=p5, mAP=mAP), lab


# ------------------------------------------------- 1+2: reconstruction, features
def _recon_job(args):
    path, gt, res = args
    text = Path(path).read_text()
    rec, stock = analyze_text(text, Path(path).stem, res=res, keep_stock=True)
    xs, ys = stock.cell_centers()
    X, Y = np.meshgrid(xs, ys)
    LX, LY = to_local(gt, X, Y)
    spec = gt["spec"]
    G = gt_depth(spec, LX, LY, gt["profile_tool_d"])
    inside = (np.abs(LX) <= spec["stock_w"] / 2) & (np.abs(LY) <= spec["stock_h"] / 2)
    D = stock.depth()
    err = (D - G)[inside]
    fd = spec["face_depth"]
    rm, gm = (D > fd + 0.3) & inside, (G > fd + 0.3) & inside
    iou = float((rm & gm).sum() / max((rm | gm).sum(), 1))
    # holes: position-matched diameter error
    gt_holes = [f for f in spec["features"] if f["type"] == "hole"]
    rec_holes = [f for f in rec["features"] if f["type"] == "hole"]
    used, hole_err, matched = set(), [], 0
    for h in gt_holes:
        mx, my = to_machine(gt, h["x"], h["y"])
        best = None
        for j, r in enumerate(rec_holes):
            d = math.hypot(r["x"] - mx, r["y"] - my)
            if j not in used and d < 3.0 and (best is None or d < best[0]):
                best = (d, j)
        if best:
            used.add(best[1])
            matched += 1
            hole_err.append((rec_holes[best[1]]["diameter"] - h["d"], best[0]))
    # count-based feature recognition per type
    counts = {}
    gt_c = Counter(GT_TO_REC[f["type"]] for f in spec["features"])
    if spec["outline"] is not None:
        gt_c["outline"] += 1
    rec_c = Counter(f["type"] for f in rec["features"])
    for t in set(gt_c) | set(rec_c):
        tp = min(gt_c[t], rec_c[t])
        counts[t] = (tp, rec_c[t] - tp, gt_c[t] - tp)
    known = all(v["source"] == "comment" for v in rec["tools"].values())
    return dict(id=rec["id"], family=gt["family"], style=gt["style"], tools_known=known,
                rms=float(np.sqrt(np.mean(err ** 2))), mae=float(np.mean(np.abs(err))), iou=iou,
                holes_gt=len(gt_holes), holes_rec=len(rec_holes), holes_matched=matched,
                hole_err=hole_err, counts=counts, runtime=rec["runtime_s"],
                warnings=len(rec["warnings"]))


def reconstruction(data, names, gts, res=0.25):
    jobs = [(str(Path(data) / "programs" / f"{n}.nc"), g, res) for n, g in zip(names, gts)]
    with ProcessPoolExecutor() as ex:
        rows = list(ex.map(_recon_job, jobs, chunksize=4))
    out = {}
    for tag, sel in [("all", lambda r: True), ("tools_from_comments", lambda r: r["tools_known"]),
                     ("tools_inferred", lambda r: not r["tools_known"])]:
        rs = [r for r in rows if sel(r)]
        if not rs:
            continue
        he = [e for r in rs for e in r["hole_err"]]
        out[tag] = dict(n=len(rs), rms_mm=float(np.mean([r["rms"] for r in rs])),
                        median_rms_mm=float(np.median([r["rms"] for r in rs])),
                        mae_mm=float(np.mean([r["mae"] for r in rs])),
                        iou=float(np.mean([r["iou"] for r in rs])),
                        hole_recall=sum(r["holes_matched"] for r in rs) / max(sum(r["holes_gt"] for r in rs), 1),
                        hole_precision=sum(r["holes_matched"] for r in rs) / max(sum(r["holes_rec"] for r in rs), 1),
                        hole_diam_mae_mm=float(np.mean([abs(e[0]) for e in he])) if he else None,
                        hole_pos_mae_mm=float(np.mean([e[1] for e in he])) if he else None)
    per_type = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        for t, (tp, fp, fn) in r["counts"].items():
            per_type[t][0] += tp
            per_type[t][1] += fp
            per_type[t][2] += fn
    feat = {t: dict(tp=v[0], fp=v[1], fn=v[2], precision=v[0] / max(v[0] + v[1], 1),
                    recall=v[0] / max(v[0] + v[2], 1)) for t, v in sorted(per_type.items())}
    per_family = {f: float(np.mean([r["iou"] for r in rows if r["family"] == f])) for f in FAMILIES}
    per_style = {s: float(np.mean([r["iou"] for r in rows if r["style"] == s])) for s in STYLES}
    return dict(summary=out, features=feat, iou_per_family=per_family, iou_per_style=per_style,
                runtime_mean_s=float(np.mean([r["runtime"] for r in rows])),
                runtime_p95_s=float(np.percentile([r["runtime"] for r in rows], 95))), rows


# --------------------------------------------------------- 3-5: families, ablation
def strip_numbers(text):
    """Text baseline 2: only the command words (G/M/T codes), coordinates removed."""
    return " ".join(re.findall(r"[GMT]\d+", text.upper()))


def families(data, out, names, gts):
    fp = np.load(Path(out) / "fingerprints.npz")
    order = [list(fp["names"]).index(n) for n in names]
    geo, proc, scale = fp["geo"][order], fp["proc"][order], fp["scale"][order]
    y = np.unique([g["family"] for g in gts], return_inverse=True)[1]
    texts = [(Path(data) / "programs" / f"{n}.nc").read_text() for n in names]
    variants = {}
    T1 = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2).fit_transform(texts)
    variants["text_tfidf_raw"] = T1
    T2 = TfidfVectorizer(token_pattern=r"\S+", ngram_range=(1, 3), min_df=2).fit_transform(
        [strip_numbers(t) for t in texts])
    variants["text_tfidf_codes"] = T2
    from sklearn.decomposition import TruncatedSVD
    res = {}
    for name, T in variants.items():
        X = TruncatedSVD(n_components=50, random_state=0).fit_transform(T)
        res[name], tlab = cluster_metrics(X, y, len(FAMILIES))
        res[name]["ari_vs_dialect"] = adjusted_rand_score([g["style"] for g in gts], tlab)
    for name, w in [("process_only", dict(geometry=0, process=1)),
                    ("geometry_only", dict(geometry=1, process=0)),
                    ("full", dict(geometry=0.5, process=0.5))]:
        X, _ = build_matrix(geo, proc, None, w)
        res[name], lab = cluster_metrics(X, y, len(FAMILIES))
        if name == "full":
            full_X, full_lab = X, lab
    # dialect invariance of retrieval: neighbours from the same family but another dialect
    styles = np.array([g["style"] for g in gts])
    nb, _ = all_neighbours(full_X, k=5)
    cross = [(y[j] == y[i]) for i in range(len(y)) for j in nb[i] if styles[j] != styles[i]]
    res["full"]["cross_dialect_neighbour_precision"] = float(np.mean(cross))
    res["full"]["cross_dialect_neighbour_share"] = float(np.mean(styles[nb] != styles[:, None]))
    per_style = {s: float((y[nb[styles == s]] == y[styles == s][:, None]).mean()) for s in STYLES}
    res["full"]["p_at_5_per_dialect"] = per_style
    return res, full_X, full_lab, y


# ------------------------------------------------------- 6: tool diameter inference
def tool_inference(data, names, gts):
    exact = one_step = n = 0
    inferred = defaults = 0
    for n_, gt in zip(names, gts):
        if gt["style"] != "minimal":
            continue
        pr = parse((Path(data) / "programs" / f"{n_}.nc").read_text())
        tools = resolve_tools(pr)
        for t, info in tools.items():
            true = gt["tools"].get(str(t))
            if true is None or true["kind"] == "drill":
                continue
            n += 1
            if info["source"] == "inferred":
                inferred += 1
                d, td = info["diameter"], true["diameter"]
                exact += abs(d - td) < 1e-6
                i1 = min(range(len(STANDARD_MM)), key=lambda i: abs(STANDARD_MM[i] - d))
                i2 = min(range(len(STANDARD_MM)), key=lambda i: abs(STANDARD_MM[i] - td))
                one_step += abs(i1 - i2) <= 1
            else:
                defaults += 1
    return dict(milling_tools=n, inferred=inferred, fell_back_to_default=defaults,
                exact_of_inferred=exact / max(inferred, 1), within_one_size_of_inferred=one_step / max(inferred, 1),
                coverage=inferred / max(n, 1))


# ------------------------------------------------------- 7: same part, four dialects
def dialect_invariance(X_ref_scalers=None, per_family=5, seed=99):
    """Post the same part in all four dialects with independent fixturing and
    compare fingerprint similarity within a part vs. across families."""
    rng = np.random.default_rng(seed)
    recs, part_id, fam = [], [], []
    for f in FAMILIES:
        for p in range(per_family):
            spec = make_spec(f, rng)
            ops, _ = plan(spec, rng)
            for st in STYLES:
                theta, ox, oy = setup_transform(spec, rng)
                text, _ = post(ops, st, rng, theta, ox, oy, 5000 + len(recs))
                r = analyze_text(text, f"{f}_{p}_{st}")
                recs.append(r)
                part_id.append(f"{f}_{p}")
                fam.append(f)
    geo = np.array([r["geo"] for r in recs])
    proc = np.array([r["proc"] for r in recs])
    X, _ = build_matrix(geo, proc, None, dict(geometry=0.5, process=0.5))
    U = X / np.linalg.norm(X, axis=1, keepdims=True)
    S = U @ U.T
    pid, fam = np.array(part_id), np.array(fam)
    same_part = (pid[:, None] == pid[None, :]) & ~np.eye(len(pid), dtype=bool)
    same_fam = (fam[:, None] == fam[None, :]) & ~same_part & ~np.eye(len(pid), dtype=bool)
    other = fam[:, None] != fam[None, :]
    descs = defaultdict(set)
    for r, p in zip(recs, part_id):
        descs[p].add(r["description"])
    return dict(n_parts=len(set(part_id)), n_programs=len(recs),
                sim_same_part=float(S[same_part].mean()), sim_same_family=float(S[same_fam].mean()),
                sim_other_family=float(S[other].mean()),
                identical_description_rate=float(np.mean([len(v) == 1 for v in descs.values()])))


# ------------------------------------------------------- 8: resolution / runtime
def resolution_study(data, names, gts, n=48):
    rng = np.random.default_rng(0)
    pick = rng.choice(len(names), size=min(n, len(names)), replace=False)
    out = {}
    for res in (0.5, 0.25, 0.1):
        jobs = [(str(Path(data) / "programs" / f"{names[i]}.nc"), gts[i], res) for i in pick]
        t0 = time.time()
        with ProcessPoolExecutor() as ex:
            rows = list(ex.map(_recon_job, jobs, chunksize=2))
        he = [abs(e[0]) for r in rows for e in r["hole_err"]]
        out[str(res)] = dict(rms_mm=float(np.mean([r["rms"] for r in rows])),
                             iou=float(np.mean([r["iou"] for r in rows])),
                             hole_diam_mae_mm=float(np.mean(he)) if he else None,
                             runtime_per_program_s=float(np.mean([r["runtime"] for r in rows])))
    return out


# ------------------------------------------------------- 9: hand-written programs
def handwritten(folder):
    rows = []
    for p in sorted(Path(folder).glob("*.nc")):
        try:
            r = analyze_text(p.read_text(), p.stem)
            rows.append(dict(file=p.name, lines=r["n_lines"], description=r["description"],
                             operations=[x["operation"] for x in r["process"]],
                             warnings=r["warnings"], cycle_time_s=r["summary"]["cycle_time_s"]))
        except Exception as e:
            rows.append(dict(file=p.name, error=f"{type(e).__name__}: {e}"))
    return rows


# ------------------------------------------------------------------ figures
def figures(results, X, lab, y, names, gts, data, figdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 8, "font.family": "serif", "axes.spines.top": False,
                         "axes.spines.right": False})
    figdir = Path(figdir)
    figdir.mkdir(parents=True, exist_ok=True)
    cmap = plt.get_cmap("tab10")
    fam_names = sorted(set(g["family"] for g in gts))

    # t-SNE map coloured by true family, marker by dialect
    xy = embed_2d(X)
    markers = dict(fanuc="o", haas="s", minimal="^", inch_inc="D")
    fig, ax = plt.subplots(figsize=(3.5, 3.0))
    styles = np.array([g["style"] for g in gts])
    for fi, f in enumerate(fam_names):
        for st, mk in markers.items():
            m = (y == fi) & (styles == st)
            ax.scatter(xy[m, 0], xy[m, 1], s=7, marker=mk, color=cmap(fi), alpha=0.75, linewidths=0,
                       label=f.replace("_", " ") if st == "fanuc" else None)
    ax.set_xticks([]), ax.set_yticks([])
    ax.legend(fontsize=6, ncol=2, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.02))
    ax.set_title("Fingerprint map (t-SNE); colour = true family, marker = dialect", fontsize=7)
    fig.tight_layout()
    fig.savefig(figdir / "tsne.pdf"), fig.savefig(figdir / "tsne.png", dpi=200)
    plt.close(fig)

    # confusion matrix (clusters matched to families by Hungarian assignment)
    C = np.zeros((len(fam_names), len(fam_names)), int)
    for a, b in zip(y, lab):
        C[a, b] += 1
    r, c = linear_sum_assignment(-C)
    C = C[:, c[np.argsort(r)]]
    fig, ax = plt.subplots(figsize=(3.5, 3.1))
    ax.imshow(C, cmap="Blues")
    for i in range(C.shape[0]):
        for j in range(C.shape[1]):
            if C[i, j]:
                ax.text(j, i, C[i, j], ha="center", va="center", fontsize=6,
                        color="white" if C[i, j] > C.max() / 2 else "black")
    ax.set_yticks(range(len(fam_names)), [f.replace("_", " ") for f in fam_names], fontsize=6)
    ax.set_xticks(range(len(fam_names)), [f"C{i + 1}" for i in range(len(fam_names))], fontsize=6)
    ax.set_xlabel("discovered cluster"), ax.set_ylabel("true family")
    fig.tight_layout()
    fig.subplots_adjust(left=0.3)
    fig.savefig(figdir / "confusion.pdf"), fig.savefig(figdir / "confusion.png", dpi=200)
    plt.close(fig)

    # ablation bars
    fam_res = results["families"]
    order = ["text_tfidf_raw", "text_tfidf_codes", "process_only", "geometry_only", "full"]
    labels = ["Text\n(raw)", "Text\n(codes)", "Process\nonly", "Geometry\nonly", "Full\n(ours)"]
    fig, ax = plt.subplots(figsize=(3.5, 2.1))
    w = 0.27
    xs = np.arange(len(order))
    for k, (key, nm) in enumerate([("ari", "ARI"), ("nmi", "NMI"), ("p_at_5", "P@5")]):
        ax.bar(xs + (k - 1) * w, [fam_res[o][key] for o in order], w, label=nm, color=cmap(k))
    ax.set_xticks(xs, labels, fontsize=6.5)
    ax.set_ylim(0, 1.05)
    ax.legend(fontsize=6.5, frameon=False, ncol=3, loc="upper left")
    fig.tight_layout()
    fig.savefig(figdir / "ablation.pdf"), fig.savefig(figdir / "ablation.png", dpi=200)
    plt.close(fig)

    # resolution trade-off
    rs = results["resolution"]
    keys = sorted(rs, key=float)
    fig, ax1 = plt.subplots(figsize=(3.5, 2.0))
    ax1.plot([float(k) for k in keys], [rs[k]["rms_mm"] for k in keys], "o-", color=cmap(0), label="RMS depth error")
    ax1.set_xlabel("grid resolution (mm)"), ax1.set_ylabel("RMS error (mm)", color=cmap(0))
    ax2 = ax1.twinx()
    ax2.plot([float(k) for k in keys], [rs[k]["runtime_per_program_s"] for k in keys], "s--", color=cmap(3))
    ax2.set_ylabel("runtime / program (s)", color=cmap(3))
    ax2.spines["right"].set_visible(True)
    fig.tight_layout()
    fig.savefig(figdir / "resolution.pdf"), fig.savefig(figdir / "resolution.png", dpi=200)
    plt.close(fig)


def pipeline_figure(data, names, gts, figdir):
    """G-code toolpath -> height map -> recognised features for one program,
    plus the same part in four dialects."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle
    figdir = Path(figdir)
    i = next(k for k, g in enumerate(gts) if g["family"] == "flange" and g["style"] == "haas")
    text = (Path(data) / "programs" / f"{names[i]}.nc").read_text()
    rec, stock = analyze_text(text, names[i], keep_stock=True)
    pr = parse(text)
    fig, axs = plt.subplots(1, 3, figsize=(7.16, 2.5), gridspec_kw=dict(wspace=0.35))
    tools = sorted({s.tool for s in pr.segments})
    cm = plt.get_cmap("tab10")
    for s in pr.segments:
        if s.kind == "feed":
            axs[0].plot([s.start[0], s.end[0]], [s.start[1], s.end[1]], lw=0.4, color=cm(tools.index(s.tool)))
    axs[0].set_title("(a) parsed toolpath", fontsize=8)
    ext = [stock.x0, stock.x0 + stock.Z.shape[1] * stock.res, stock.y0, stock.y0 + stock.Z.shape[0] * stock.res]
    im = axs[1].imshow(stock.depth(), origin="lower", extent=ext, cmap="viridis")
    cb = fig.colorbar(im, ax=axs[1], fraction=0.046, pad=0.02)
    cb.ax.set_title("mm", fontsize=6)
    cb.ax.tick_params(labelsize=6)
    axs[1].set_title("(b) recovered height map", fontsize=8)
    axs[2].imshow(stock.depth() > rec["process"][0]["depth"] + 0.3, origin="lower", extent=ext, cmap="Greys", alpha=0.35)
    for f in rec["features"]:
        col = dict(hole="tab:red", circular_pocket="tab:blue", outline="tab:green").get(f["type"], "tab:orange")
        if f["type"] in ("hole", "circular_pocket"):
            axs[2].add_patch(Circle((f["x"], f["y"]), f["diameter"] / 2, fill=False, color=col, lw=1))
        if f["type"] == "outline":   # label the ring at its edge, not its centre
            axs[2].annotate("outline", (f["x"], f["y"] - f["width"] / 2), fontsize=5.5, color=col,
                            ha="center", va="top")
        else:
            axs[2].annotate(f["type"].replace("_", " "), (f["x"], f["y"]), fontsize=5.5, color=col,
                            ha="center", va="center")
    axs[2].set_title("(c) recognised features", fontsize=8)
    for a in axs:
        a.set_aspect("equal")
        a.set_xticks([]), a.set_yticks([])
    fig.subplots_adjust(left=0.02, right=0.98, top=0.88, bottom=0.04)
    fig.savefig(figdir / "pipeline.pdf"), fig.savefig(figdir / "pipeline.png", dpi=200)
    plt.close(fig)

    # same part, four dialects
    rng = np.random.default_rng(5)
    spec = make_spec("boss", rng)
    ops, _ = plan(spec, rng)
    fig, axs = plt.subplots(2, 4, figsize=(7.16, 3.3), gridspec_kw=dict(height_ratios=[1, 1.15]))
    for k, st in enumerate(STYLES):
        theta, ox, oy = setup_transform(spec, rng)
        txt, _ = post(ops, st, rng, theta, ox, oy, 4242)
        r, stck = analyze_text(txt, st, keep_stock=True)
        body = [ln for ln in txt.splitlines() if ln.strip()][4:13]
        axs[0, k].text(0.0, 1.0, "\n".join(ln[:30] for ln in body), family="monospace", fontsize=4.6,
                       va="top", transform=axs[0, k].transAxes)
        axs[0, k].set_title(st.replace("_", "+"), fontsize=8)
        axs[0, k].axis("off")
        axs[1, k].imshow(stck.depth(), origin="lower", cmap="viridis")
        axs[1, k].set_xticks([]), axs[1, k].set_yticks([])
        axs[1, k].set_xlabel(r["description"][:38], fontsize=5)
    fig.tight_layout()
    fig.savefig(figdir / "dialects.pdf"), fig.savefig(figdir / "dialects.png", dpi=200)
    plt.close(fig)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data_test")
    ap.add_argument("--out", default="out_test")
    ap.add_argument("--results", default="results")
    ap.add_argument("--figs", default="paper/figs")
    ap.add_argument("--handwritten", default="samples/handwritten")
    ap.add_argument("--figs-only", action="store_true", help="recompute family metrics + figures only")
    a = ap.parse_args(argv)
    Path(a.results).mkdir(exist_ok=True)
    if a.figs_only:
        idx = json.loads((Path(a.out) / "index.json").read_text())
        names = sorted(p["id"] for p in idx["programs"])
        gts = load_gt(a.data, names)
        results = json.loads((Path(a.results) / "metrics.json").read_text())
        fam, X, lab, y = families(a.data, a.out, names, gts)
        results["families"] = fam
        (Path(a.results) / "metrics.json").write_text(json.dumps(results, indent=2))
        figures(results, X, lab, y, names, gts, a.data, a.figs)
        pipeline_figure(a.data, names, gts, a.figs)
        print("figures rewritten")
        return
    idx = json.loads((Path(a.out) / "index.json").read_text())
    names = sorted(p["id"] for p in idx["programs"])
    gts = load_gt(a.data, names)
    results = dict(dataset=dict(n_programs=len(names), families=len(FAMILIES),
                                per_dialect=dict(Counter(g["style"] for g in gts)),
                                failed=idx.get("failed", [])))
    t = time.time()
    results["reconstruction"], rows = reconstruction(a.data, names, gts)
    print(f"[recon] {time.time() - t:.0f}s", json.dumps(results["reconstruction"]["summary"]["all"]))
    results["families"], X, lab, y = families(a.data, a.out, names, gts)
    print("[families]", {k: round(v["ari"], 3) for k, v in results["families"].items()})
    results["tool_inference"] = tool_inference(a.data, names, gts)
    print("[tools]", results["tool_inference"])
    results["dialect_invariance"] = dialect_invariance()
    print("[dialects]", results["dialect_invariance"])
    results["resolution"] = resolution_study(a.data, names, gts)
    print("[resolution]", results["resolution"])
    if Path(a.handwritten).exists():
        results["handwritten"] = handwritten(a.handwritten)
    (Path(a.results) / "metrics.json").write_text(json.dumps(results, indent=2))
    (Path(a.results) / "per_program.json").write_text(json.dumps(rows))
    figures(results, X, lab, y, names, gts, a.data, a.figs)
    pipeline_figure(a.data, names, gts, a.figs)
    print("wrote", Path(a.results) / "metrics.json")


if __name__ == "__main__":
    main()
