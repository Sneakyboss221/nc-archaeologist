"""End-to-end pipeline: a folder of legacy NC programs -> recovered parts,
process sheets, fingerprints, part families and similarity index.

    python -m ncarch.pipeline data/programs out
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from .analysis.fingerprint import geometry_vector, process_vector, scale_vector
from .analysis.geometry import describe, recognize
from .analysis.process import analyze_process
from .families.cluster import build_matrix, discover, embed_2d
from .families.search import all_neighbours
from .gcode.parser import parse
from .sim.mesh import export_stl, web_payload
from .sim.stock import simulate
from .sim.tools import resolve_tools


def toolpath_payload(segments, max_points=12000):
    """Polylines grouped by tool and move type, thinned for the browser.

    `ln` holds the G-code line number of every point, so a replay can show
    which line is being executed.
    """
    step = max(1, len(segments) // max_points)
    lines, cur = [], None
    for k, s in enumerate(segments):
        key = (s.tool, s.kind)
        if cur is None or cur["key"] != key:
            cur = dict(key=key, tool=s.tool, rapid=s.kind == "rapid",
                       pts=[round(v, 2) for v in s.start], ln=[s.line])
            lines.append(cur)
        if k % step == 0 or k == len(segments) - 1 or s.kind == "rapid":
            cur["pts"] += [round(v, 2) for v in s.end]
            cur["ln"].append(s.line)
    for ln in lines:
        del ln["key"]
    return lines


def analyze_text(text, name="program", res=0.25, stl_path=None, keep_stock=False):
    t0 = time.perf_counter()
    stages = []

    def stage(name, detail):
        nonlocal t0
        now = time.perf_counter()
        stages.append(dict(name=name, detail=detail, ms=round(1000 * (now - t0), 1)))
        t0 = now

    t_start = t0
    pr = parse(text)
    if not any(s.kind == "feed" for s in pr.segments):
        raise ValueError("no cutting moves found")
    n_feed = sum(s.kind == "feed" for s in pr.segments)
    stage("Parse G-code", f"{pr.n_lines} lines → {len(pr.segments)} straight moves "
                          f"({n_feed} cutting, {len(pr.segments) - n_feed} rapid)")
    tools = resolve_tools(pr)
    for t, info in tools.items():
        if info["source"] == "default":
            pr.warn(f"T{t}: diameter unknown (no comment, no raster passes); assumed {info['diameter']:.0f} mm")
    stage("Identify cutters", ", ".join(f"T{t} Ø{v['diameter']:g} {v['kind']} ({v['source']})"
                                        for t, v in tools.items()))
    stock = simulate(pr.segments, tools, res=res)
    ny, nx = stock.Z.shape
    stage("Simulate material removal", f"{nx}×{ny} grid at {stock.res:g} mm = {nx * ny:,} height cells")
    sheet, summary = analyze_process(pr, tools, stock)
    stage("Build process sheet", " → ".join(r["operation"].replace("_", " ") for r in sheet)
          + f" · cycle time {summary['cycle_time_s']:.0f} s")
    feats, pattern, face_d = recognize(stock, sheet)
    stage("Recognise features", describe(feats, pattern))
    rec = dict(
        id=name, n_lines=pr.n_lines, warnings=pr.warnings,
        dialect=dict(inch=pr.used_inch, incremental=pr.used_incremental,
                     canned_cycles=pr.used_canned, arcs=pr.used_arcs),
        tools={str(k): v for k, v in tools.items()}, process=sheet, summary=summary,
        features=feats, pattern=pattern, description=describe(feats, pattern),
        geo=geometry_vector(stock, feats, pattern, face_d, sheet).tolist(),
        proc=process_vector(sheet, summary).tolist(),
        scale=scale_vector(stock, summary).tolist(),
        heightmap=web_payload(stock), toolpath=toolpath_payload(pr.segments),
        n_segments=len(pr.segments), notes=pr.notes,
        grid=dict(nx=int(nx), ny=int(ny), res=float(stock.res)))
    stage("Compute fingerprint", f"{len(rec['geo'])} geometry + {len(rec['proc'])} process numbers")
    rec["stages"] = stages
    rec["runtime_s"] = round(time.perf_counter() - t_start, 3)
    if stl_path:
        export_stl(stock, stl_path)
    if keep_stock:
        return rec, stock
    return rec


def _job(args):
    path, out_dir, res, stl = args
    name = Path(path).stem
    try:
        rec = analyze_text(Path(path).read_text(errors="replace"), name, res,
                           stl_path=str(Path(out_dir) / "stl" / f"{name}.stl") if stl else None)
        rec["text"] = Path(path).read_text(errors="replace")
        (Path(out_dir) / "programs" / f"{name}.json").write_text(json.dumps(rec))
        return name, rec["geo"], rec["proc"], rec["scale"], None
    except Exception as e:  # keep going: a broken legacy file must not stop the archive
        return name, None, None, None, f"{type(e).__name__}: {e}"


def build_index(out_dir, names, geo, proc, scale, weights=None):
    X, _ = build_matrix(np.array(geo), np.array(proc), np.array(scale), weights)
    fam = discover(X)
    xy = embed_2d(X)
    nb, ns = all_neighbours(X, k=6)
    labels = fam["agglomerative"]
    centroids = {int(c): X[labels == c].mean(axis=0).tolist() for c in np.unique(labels)}
    items = []
    for i, n in enumerate(names):
        rec = json.loads((Path(out_dir) / "programs" / f"{n}.json").read_text())
        items.append(dict(id=n, family=int(labels[i]), hdbscan=int(fam["hdbscan"][i]),
                          x=float(xy[i, 0]), y=float(xy[i, 1]),
                          description=rec["description"], n_warnings=len(rec["warnings"]),
                          cycle_time_s=rec["summary"]["cycle_time_s"],
                          similar=[dict(id=names[j], score=round(float(s), 3)) for j, s in zip(nb[i], ns[i])]))
    index = dict(k=fam["k"], silhouette=fam["silhouette"], n_outliers=int((fam["hdbscan"] == -1).sum()),
                 programs=items)
    (Path(out_dir) / "index.json").write_text(json.dumps(index))
    np.savez(Path(out_dir) / "fingerprints.npz", names=np.array(names), geo=np.array(geo),
             proc=np.array(proc), scale=np.array(scale), X=X, labels=labels)
    (Path(out_dir) / "centroids.json").write_text(json.dumps(centroids))
    return index


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("programs")
    ap.add_argument("out")
    ap.add_argument("--res", type=float, default=0.25)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--stl", action="store_true", help="also export an STL per program (~7 MB each)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    (out / "programs").mkdir(parents=True, exist_ok=True)
    (out / "stl").mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in Path(a.programs).iterdir() if p.suffix.lower() in (".nc", ".ngc", ".tap", ".gcode", ".txt"))
    t0 = time.time()
    names, geo, proc, scale, failed = [], [], [], [], []
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for name, g, p, s, err in ex.map(_job, [(str(f), str(out), a.res, a.stl) for f in files], chunksize=4):
            if err:
                failed.append(dict(id=name, error=err))
                continue
            names.append(name)
            geo.append(g)
            proc.append(p)
            scale.append(s)
    print(f"analysed {len(names)} programs ({len(failed)} failed) in {time.time() - t0:.1f}s")
    index = build_index(out, names, geo, proc, scale)
    index["failed"] = failed
    (out / "index.json").write_text(json.dumps(index))
    print(f"found {index['k']} part families (silhouette {index['silhouette']:.3f}), "
          f"{index['n_outliers']} HDBSCAN outliers")


if __name__ == "__main__":
    main()
