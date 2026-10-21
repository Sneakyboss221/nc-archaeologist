"""Group-Technology part-family discovery from program fingerprints."""
from __future__ import annotations

import numpy as np
from sklearn.cluster import HDBSCAN, AgglomerativeClustering
from sklearn.manifold import TSNE
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

DEFAULT_WEIGHTS = dict(geometry=0.5, process=0.5, scale=0.0)   # chosen on the dev set


def build_matrix(geo, proc, scale=None, weights=None):
    """Standardise each block, weight it, and normalise by block size so a long
    block does not dominate just because it has more dimensions."""
    w = dict(DEFAULT_WEIGHTS, **(weights or {}))
    blocks, scalers = [], {}
    for name, M in (("geometry", geo), ("process", proc), ("scale", scale)):
        if M is None or w[name] == 0:
            continue
        sc = StandardScaler().fit(M)
        Z = np.nan_to_num(sc.transform(M))
        blocks.append(Z * w[name] / np.sqrt(M.shape[1]))
        scalers[name] = sc
    return np.hstack(blocks), scalers


def transform(scalers, geo, proc, scale=None, weights=None):
    """Project new fingerprints into an existing archive's feature space."""
    w = dict(DEFAULT_WEIGHTS, **(weights or {}))
    blocks = []
    for name, M in (("geometry", geo), ("process", proc), ("scale", scale)):
        if name in scalers:
            M = np.atleast_2d(M)
            blocks.append(np.nan_to_num(scalers[name].transform(M)) * w[name] / np.sqrt(M.shape[1]))
    return np.hstack(blocks)


def choose_k(X, k_range=range(4, 13)):
    best = None
    for k in k_range:
        lab = AgglomerativeClustering(n_clusters=k, linkage="ward").fit_predict(X)
        s = silhouette_score(X, lab)
        if best is None or s > best[1]:
            best = (k, s, lab)
    return best


def discover(X, min_cluster_size=15):
    """Return dict with HDBSCAN labels (-1 = outlier), agglomerative labels and k."""
    hdb = HDBSCAN(min_cluster_size=min_cluster_size, min_samples=5, copy=True).fit(X)
    k, sil, agg = choose_k(X)
    return dict(hdbscan=hdb.labels_, agglomerative=agg, k=k, silhouette=float(sil))


def embed_2d(X, seed=0):
    perp = min(30, max(5, (len(X) - 1) // 3))
    return TSNE(n_components=2, perplexity=perp, random_state=seed, init="pca").fit_transform(X)
