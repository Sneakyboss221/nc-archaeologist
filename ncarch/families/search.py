"""'Have we made something like this before?' - cosine kNN over fingerprints."""
from __future__ import annotations

import numpy as np


def _unit(X):
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)


def similar(X, i=None, query=None, k=5):
    """Top-k most similar rows to row i (excluded) or to an external query vector."""
    U = _unit(X)
    q = U[i] if query is None else _unit(query[None, :])[0]
    sims = U @ q
    if i is not None:
        sims[i] = -np.inf
    idx = np.argsort(-sims)[:k]
    return [(int(j), float(sims[j])) for j in idx]


def all_neighbours(X, k=5):
    U = _unit(X)
    S = U @ U.T
    np.fill_diagonal(S, -np.inf)
    idx = np.argsort(-S, axis=1)[:, :k]
    return idx, np.take_along_axis(S, idx, axis=1)
