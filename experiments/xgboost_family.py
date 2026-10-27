"""Supervised part-family classification with XGBoost.

Scenario: a shop has already labelled part of its archive. Train on the labelled
programs, then assign new programs to known families with a confidence.

    python -m experiments.xgboost_family

Protocol (same as the rest of the paper): hyper-parameters are chosen by 5-fold
cross-validation on the development set (data/, seed 7) only; the chosen model
is trained on the whole development set and evaluated once on the held-out
test set (data_test/, seed 11). Writes results/xgboost.json, the model to
out_test/xgb_family.json, and paper/figs/xgb_importance.{pdf,png}.
"""
from __future__ import annotations

import itertools
import json
import time
from pathlib import Path

import numpy as np
import xgboost as xgb
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, log_loss
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

from ncarch.analysis.fingerprint import FEATURE_NAMES, GEOMETRY_NAMES
from ncarch.datagen.families import FAMILIES
from ncarch.pipeline import analyze_text

GRID = dict(max_depth=[3, 4, 6], n_estimators=[200, 400], learning_rate=[0.05, 0.1])
FIXED = dict(subsample=0.8, colsample_bytree=0.8, objective="multi:softprob", eval_metric="mlogloss",
             tree_method="hist", random_state=0, n_jobs=-1)
GROUPS = [("depth histogram", "depth hist"), ("Hu moments", "Hu moment"), ("radial profile", "radial profile"),
          ("feature counts", "count: "), ("shape terms", None), ("process", None)]


def load(out_dir, data_dir):
    fp = np.load(Path(out_dir) / "fingerprints.npz")
    names = [str(n) for n in fp["names"]]
    X = np.hstack([fp["geo"], fp["proc"]])
    gts = [json.loads((Path(data_dir) / "gt" / f"{n}.json").read_text()) for n in names]
    y = np.array([FAMILIES.index(g["family"]) for g in gts])
    styles = np.array([g["style"] for g in gts])
    texts = [(Path(data_dir) / "programs" / f"{n}.nc").read_text() for n in names]
    return names, X, y, styles, texts


def model(**kw):
    return xgb.XGBClassifier(**FIXED, **kw)


def cv_select(X, y):
    """Grid search with stratified 5-fold CV on the development set only."""
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    scores = []
    for combo in itertools.product(*GRID.values()):
        params = dict(zip(GRID.keys(), combo))
        accs = []
        for tr, va in skf.split(X, y):
            m = model(**params).fit(X[tr], y[tr])
            accs.append(accuracy_score(y[va], m.predict(X[va])))
        scores.append((float(np.mean(accs)), float(np.std(accs)), params))
    scores.sort(key=lambda s: -s[0])
    return scores


def group_of(name):
    if name in GEOMETRY_NAMES:
        for g, prefix in GROUPS[:4]:
            if prefix and name.startswith(prefix):
                return g
        return "shape terms"
    return "process"


def main():
    t0 = time.time()
    _, Xd, yd, sd, td = load("out_dev", "data")
    _, Xt, yt, st, tt = load("out_test", "data_test")
    print(f"dev {Xd.shape}, test {Xt.shape}")

    scores = cv_select(Xd, yd)
    best_cv, best_sd, best = scores[0]
    print(f"best CV accuracy {best_cv:.4f} ± {best_sd:.4f} with {best}")

    clf = model(**best).fit(Xd, yd)
    proba = clf.predict_proba(Xt)
    pred = proba.argmax(1)
    top2 = float(np.mean([yt[i] in np.argsort(-proba[i])[:2] for i in range(len(yt))]))
    res = dict(
        protocol="5-fold stratified CV on the 600-program development set for hyper-parameters; "
                 "one evaluation on the 600-program held-out test set",
        grid=GRID, fixed={k: v for k, v in FIXED.items() if k != "n_jobs"}, chosen=best,
        cv_accuracy=best_cv, cv_std=best_sd,
        cv_all=[dict(accuracy=a, std=s, **p) for a, s, p in scores],
        test=dict(accuracy=accuracy_score(yt, pred), macro_f1=f1_score(yt, pred, average="macro"),
                  top2_accuracy=top2, log_loss=log_loss(yt, proba, labels=list(range(len(FAMILIES)))),
                  per_family_f1={FAMILIES[i]: float(v) for i, v in enumerate(f1_score(yt, pred, average=None))},
                  per_dialect_accuracy={s: float(accuracy_score(yt[st == s], pred[st == s])) for s in sorted(set(st))},
                  confusion=confusion_matrix(yt, pred).tolist(), families=FAMILIES,
                  mean_confidence_correct=float(proba.max(1)[pred == yt].mean()),
                  mean_confidence_wrong=float(proba.max(1)[pred != yt].mean()) if (pred != yt).any() else None),
    )

    # baselines on exactly the same split
    base = {}
    for name, cols in (("geometry only", slice(0, len(GEOMETRY_NAMES))), ("process only", slice(len(GEOMETRY_NAMES), None))):
        m = model(**best).fit(Xd[:, cols], yd)
        p = m.predict(Xt[:, cols])
        base[f"XGBoost, {name}"] = dict(accuracy=accuracy_score(yt, p), macro_f1=f1_score(yt, p, average="macro"))
    tf = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2).fit(td)
    svd = TruncatedSVD(n_components=50, random_state=0).fit(tf.transform(td))
    Td, Tt = svd.transform(tf.transform(td)), svd.transform(tf.transform(tt))
    p = model(**best).fit(Td, yd).predict(Tt)
    base["XGBoost, G-code text (TF-IDF)"] = dict(accuracy=accuracy_score(yt, p), macro_f1=f1_score(yt, p, average="macro"))
    sc = StandardScaler().fit(Xd)
    Ud = sc.transform(Xd); Ud /= np.linalg.norm(Ud, axis=1, keepdims=True) + 1e-12
    Ut = sc.transform(Xt); Ut /= np.linalg.norm(Ut, axis=1, keepdims=True) + 1e-12
    p = yd[np.argmax(Ut @ Ud.T, axis=1)]
    base["1-nearest neighbour, full fingerprint"] = dict(accuracy=accuracy_score(yt, p), macro_f1=f1_score(yt, p, average="macro"))
    res["baselines"] = base
    for k, v in base.items():
        print(f"  {k:42s} acc {v['accuracy']:.3f}  F1 {v['macro_f1']:.3f}")

    # gain-based feature importance
    gain = clf.get_booster().get_score(importance_type="gain")
    imp = np.zeros(len(FEATURE_NAMES))
    for k, v in gain.items():
        imp[int(k[1:])] = v
    imp = imp / imp.sum()
    order = np.argsort(-imp)
    res["importance_top"] = [dict(feature=FEATURE_NAMES[i], share=float(imp[i]), group=group_of(FEATURE_NAMES[i]))
                             for i in order[:15]]
    groups = {}
    for i, n in enumerate(FEATURE_NAMES):
        groups[group_of(n)] = groups.get(group_of(n), 0.0) + float(imp[i])
    res["importance_by_group"] = dict(sorted(groups.items(), key=lambda kv: -kv[1]))
    res["geometry_share"] = float(imp[:len(GEOMETRY_NAMES)].sum())

    # programs that belong to no known family: open-source LinuxCNC files
    real = []
    for p_ in sorted(Path("data_real/linuxcnc").glob("*.ngc")):
        try:
            r = analyze_text(p_.read_text(errors="replace"), p_.stem)
        except Exception:
            continue
        x = np.hstack([r["geo"], r["proc"]])[None, :]
        pr = clf.predict_proba(x)[0]
        real.append(dict(file=p_.name, top_family=FAMILIES[int(pr.argmax())], confidence=float(pr.max())))
    res["real_programs"] = real
    res["real_mean_confidence"] = float(np.mean([r["confidence"] for r in real])) if real else None
    res["test_mean_confidence"] = float(proba.max(1).mean())
    res["runtime_s"] = round(time.time() - t0, 1)

    Path("results").mkdir(exist_ok=True)
    Path("results/xgboost.json").write_text(json.dumps(res, indent=2))
    clf.save_model("out_test/xgb_family.json")
    Path("out_test/xgb_family_meta.json").write_text(json.dumps(dict(families=FAMILIES, features=FEATURE_NAMES,
                                                                     params=best)))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 7, "font.family": "serif", "axes.spines.top": False, "axes.spines.right": False})
    top = res["importance_top"][:12][::-1]
    palette = {"depth histogram": "#4e79a7", "Hu moments": "#f28e2b", "radial profile": "#59a14f",
               "feature counts": "#e15759", "shape terms": "#b07aa1", "process": "#9c755f"}
    fig, ax = plt.subplots(figsize=(3.5, 2.6))
    ax.barh([t["feature"] for t in top], [100 * t["share"] for t in top], color=[palette[t["group"]] for t in top])
    ax.set_xlabel("share of total gain (%)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in palette.values()]
    ax.legend(handles, palette.keys(), fontsize=5.5, frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig("paper/figs/xgb_importance.pdf"), fig.savefig("paper/figs/xgb_importance.png", dpi=200)
    t = res["test"]
    print(f"TEST accuracy {t['accuracy']:.4f}  macro-F1 {t['macro_f1']:.4f}  top-2 {t['top2_accuracy']:.4f}  "
          f"log-loss {t['log_loss']:.4f}  ({res['runtime_s']} s)")
    print("real-program mean confidence", res["real_mean_confidence"], "vs test", res["test_mean_confidence"])


if __name__ == "__main__":
    main()
