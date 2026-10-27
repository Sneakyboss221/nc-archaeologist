"""FastAPI backend for the NC-Archaeologist dashboard.

    uvicorn ncarch.api:app --port 8000          (archive folder from $NCARCH_OUT, default out_test)
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .families.cluster import build_matrix, transform
from .families.search import similar
from .pipeline import analyze_text

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("NCARCH_OUT", ROOT / "out_test"))

app = FastAPI(title="NC-Archaeologist")


@app.middleware("http")
async def no_cache(request, call_next):
    # always serve the current dashboard files (no stale cached JS after an update)
    resp = await call_next(request)
    if not request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


class Archive:
    def __init__(self, out):
        self.out = out
        self.index = json.loads((out / "index.json").read_text())
        fp = np.load(out / "fingerprints.npz")
        self.names = [str(n) for n in fp["names"]]
        self.X, self.scalers = build_matrix(fp["geo"], fp["proc"])
        self.labels = np.array([p["family"] for p in sorted(self.index["programs"],
                                                            key=lambda p: self.names.index(p["id"]))])
        self.centroids = {int(c): self.X[self.labels == c].mean(axis=0) for c in np.unique(self.labels)}
        self.uploads = {}
        self.xgb, self.xgb_families = None, []
        model_path, meta_path = out / "xgb_family.json", out / "xgb_family_meta.json"
        if model_path.exists() and meta_path.exists():
            try:   # supervised family classifier (experiments/xgboost_family.py); optional
                import xgboost
                self.xgb = xgboost.XGBClassifier()
                self.xgb.load_model(str(model_path))
                self.xgb_families = json.loads(meta_path.read_text())["families"]
            except Exception:
                self.xgb = None
        self.families = self._label_families()

    def _label_families(self):
        """Name each discovered family after its most characteristic features."""
        progs = {p["id"]: p for p in self.index["programs"]}
        fams = []
        for c in sorted(self.centroids):
            members = [n for n, l in zip(self.names, self.labels) if l == c]
            feats, ops = Counter(), Counter()
            for n in members:
                rec = json.loads((self.out / "programs" / f"{n}.json").read_text())
                for t in {f["type"] for f in rec["features"] if f["type"] != "outline"}:
                    feats[t] += 1
                if rec["pattern"] and rec["pattern"]["kind"] == "bolt_circle":
                    feats["bolt circle"] += 1
            top = [t.replace("_", " ") for t, k in feats.most_common(3) if k >= 0.4 * len(members)]
            ct = [progs[n]["cycle_time_s"] for n in members]
            fams.append(dict(id=int(c), size=len(members), label=" + ".join(top[:2]) or "mixed",
                             signature=top, median_cycle_time_s=float(np.median(ct))))
        return fams

    def record(self, pid):
        if pid in self.uploads:
            return self.uploads[pid]
        p = self.out / "programs" / f"{pid}.json"
        if not p.exists():
            raise HTTPException(404, f"unknown program {pid}")
        return json.loads(p.read_text())

    def vector(self, pid):
        if pid in self.uploads:
            return self.uploads[pid]["_x"]
        return self.X[self.names.index(pid)]


_archive = None


def archive():
    global _archive
    if _archive is None:
        _archive = Archive(OUT)
    return _archive


def _public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_") and k not in ("geo", "proc", "scale")}


@app.get("/api/index")
def get_index():
    a = archive()
    return dict(programs=a.index["programs"], families=a.families, k=a.index["k"],
                n_outliers=a.index["n_outliers"], failed=a.index.get("failed", []), archive=a.out.name)


@app.get("/api/program/{pid}")
def get_program(pid: str):
    a = archive()
    rec = _public(a.record(pid))
    rec["family"] = next((p["family"] for p in a.index["programs"] if p["id"] == pid),
                         a.uploads.get(pid, {}).get("family"))
    return rec


@app.get("/api/fingerprint/{pid}")
def get_fingerprint(pid: str):
    rec = archive().record(pid)
    return dict(geo=rec["geo"], proc=rec["proc"])


@app.get("/api/similar/{pid}")
def get_similar(pid: str, k: int = 6):
    a = archive()
    q = a.vector(pid)
    out = []
    for j, s in similar(a.X, query=q, k=k + 1):
        if a.names[j] != pid:
            out.append(dict(id=a.names[j], score=round(s, 3), family=int(a.labels[j])))
    return out[:k]


@app.get("/api/compare")
def compare(a_id: str, b_id: str):
    a = archive()
    va, vb = a.vector(a_id), a.vector(b_id)
    cos = float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-12))
    return dict(similarity=round(cos, 3), a=_public(a.record(a_id)), b=_public(a.record(b_id)))


def _identify(text, label):
    """Analyse a new program and place it in the archive's families."""
    a = archive()
    name = f"upload-{len(a.uploads) + 1}-{label}"
    try:
        rec = analyze_text(text, name)
    except Exception as e:
        raise HTTPException(422, f"could not analyse program: {e}")
    rec["text"] = text
    x = transform(a.scalers, np.array(rec["geo"]), np.array(rec["proc"]))[0]
    rec["_x"] = x
    dists = {c: float(np.linalg.norm(x - m)) for c, m in a.centroids.items()}
    fam = min(dists, key=dists.get)
    # how typical is this distance for members of that family?
    member_d = np.linalg.norm(a.X[a.labels == fam] - a.centroids[fam], axis=1)
    rec["family"] = int(fam)
    rec["family_confidence"] = round(float((member_d >= dists[fam]).mean()), 3)
    if a.xgb is not None:
        proba = a.xgb.predict_proba(np.hstack([rec["geo"], rec["proc"]])[None, :])[0]
        top = np.argsort(-proba)[:3]
        rec["xgb"] = [dict(family=a.xgb_families[i].replace("_", " "), p=round(float(proba[i]), 3)) for i in top]
    a.uploads[name] = rec
    sims = [dict(id=a.names[j], score=round(s, 3), family=int(a.labels[j])) for j, s in similar(a.X, query=x, k=6)]
    return dict(program=_public(rec), similar=sims)


@app.post("/api/identify")
async def identify(file: UploadFile = File(...)):
    text = (await file.read()).decode("utf-8", errors="replace")
    return _identify(text, Path(file.filename or "program").stem)


class TextIn(BaseModel):
    text: str
    name: str = "playground"


@app.post("/api/analyze")
def analyze(body: TextIn):
    """Playground: analyse G-code typed or edited in the browser."""
    return _identify(body.text, body.name)


SAMPLES = ROOT / "samples"
SAMPLE_INFO = {
    "same_part/flange_minimal.nc": "Flange, comment-free dialect (tool sizes must be inferred)",
    "same_part/flange_fanuc.nc": "Flange, Fanuc dialect with N-numbers and G83 drilling",
    "same_part/boss_inch_inc.nc": "Boss, inch units + incremental moves",
    "same_part/boss_haas.nc": "Boss, Haas dialect with R-form arcs",
    "handwritten/fanuc_cutter_comp.nc": "Hand-written plate with cutter compensation (warning expected)",
    "handwritten/haas_subprogram.nc": "Hand-written tray using a subprogram (expanded automatically)",
    "handwritten/helical_no_comments.nc": "Hand-written pocket with helical entry, no tool comments",
    "handwritten/macro_bolt_circle.nc": "Hand-written Fanuc Macro B bolt circle (executed)",
    "handwritten/lathe_program.nc": "A lathe program (should be flagged as not milling)",
    "real/3D_Chips.ngc": "REAL (LinuxCNC): 3D carving, 4,700 lines, parametric",
    "real/mmount.ngc": "REAL (LinuxCNC): stepper-motor mount, macros, 3 fixture stations",
    "real/cds.ngc": "REAL (LinuxCNC): Circle-Diamond-Square test part (inch)",
    "real/polar.ngc": "REAL (LinuxCNC): 26 holes with polar coordinates",
    "real/hole-circle.ngc": "REAL (LinuxCNC): 6-hole bolt circle, polar + repeat",
}
REAL = ROOT / "data_real" / "linuxcnc"


def _sample_path(p):
    return REAL / p[5:] if p.startswith("real/") else SAMPLES / p


@app.get("/api/samples")
def samples():
    return [dict(path=p, label=l) for p, l in SAMPLE_INFO.items() if _sample_path(p).exists()]


@app.post("/api/identify_sample")
def identify_sample(path: str):
    if path not in SAMPLE_INFO:
        raise HTTPException(404, "unknown sample")
    return _identify(_sample_path(path).read_text(errors="replace"), Path(path).stem)


@app.get("/api/playground_template")
def playground_template():
    return dict(text=(SAMPLES / "playground_starter.nc").read_text())


_dialects = None


@app.get("/api/dialects")
def dialects(part: str = "flange"):
    """The same part posted in four dialects, with pairwise fingerprint similarity."""
    global _dialects
    if _dialects is None:
        _dialects = {}
    if part not in _dialects:
        a = archive()
        recs = []
        for st in ("fanuc", "haas", "minimal", "inch_inc"):
            p = SAMPLES / "same_part" / f"{part}_{st}.nc"
            if not p.exists():
                raise HTTPException(404, f"missing sample {p.name}")
            r = analyze_text(p.read_text(), f"{part}_{st}")
            r["text"] = p.read_text()
            r["dialect_name"] = st
            r["_x"] = transform(a.scalers, np.array(r["geo"]), np.array(r["proc"]))[0]
            recs.append(r)
        U = np.array([r["_x"] / np.linalg.norm(r["_x"]) for r in recs])
        others = np.array([v / np.linalg.norm(v) for v in a.X])
        _dialects[part] = dict(
            programs=[{k: v for k, v in _public(r).items() if k not in ("toolpath",)} for r in recs],
            similarity=np.round(U @ U.T, 3).tolist(),
            mean_to_archive=round(float((U @ others.T).mean()), 3))
    return _dialects[part]


@app.get("/api/results")
def results():
    p = ROOT / "results" / "metrics.json"
    if not p.exists():
        raise HTTPException(404, "run experiments first")
    return json.loads(p.read_text())


@app.get("/api/stl/{pid}")
def get_stl(pid: str):
    """STL of the recovered part, generated on first request (meshes are ~7 MB each)."""
    a = archive()
    p = a.out / "stl" / f"{pid}.stl"
    if not p.exists():
        p.parent.mkdir(exist_ok=True)
        analyze_text(a.record(pid)["text"], pid, stl_path=str(p))
    return FileResponse(p, media_type="model/stl", filename=f"{pid}.stl")


app.mount("/figs", StaticFiles(directory=ROOT / "paper" / "figs"), name="figs")
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
