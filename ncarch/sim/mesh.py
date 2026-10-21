"""Height map -> watertight triangle mesh (STL export) and compact web payload."""
from __future__ import annotations

import base64

import numpy as np


def downsample(Z, max_side):
    f = int(np.ceil(max(Z.shape) / max_side))
    if f <= 1:
        return Z, 1
    ny, nx = (Z.shape[0] // f) * f, (Z.shape[1] // f) * f
    # min-pooling keeps holes and slots visible after downsampling
    return Z[:ny, :nx].reshape(ny // f, f, nx // f, f).min(axis=(1, 3)), f


def heightmap_mesh(stock, max_side=300):
    """Top surface + four side walls + base, as (vertices, faces)."""
    Z, f = downsample(stock.Z, max_side)
    ny, nx = Z.shape
    res = stock.res * f
    xs = stock.x0 + (np.arange(nx) + 0.5) * res
    ys = stock.y0 + (np.arange(ny) + 0.5) * res
    X, Y = np.meshgrid(xs, ys)
    top = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    bot = np.column_stack([X.ravel(), Y.ravel(), np.full(X.size, stock.base)])
    verts = np.vstack([top, bot])
    nb = X.size
    idx = np.arange(nb).reshape(ny, nx)
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, :-1], idx[1:, 1:]
    faces = [np.column_stack([a.ravel(), b.ravel(), d.ravel()]),
             np.column_stack([a.ravel(), d.ravel(), c.ravel()])]
    # base (reversed winding)
    faces += [np.column_stack([a.ravel() + nb, d.ravel() + nb, b.ravel() + nb]),
              np.column_stack([a.ravel() + nb, c.ravel() + nb, d.ravel() + nb])]
    # walls along the boundary loop
    ring = np.concatenate([idx[0, :], idx[1:, -1], idx[-1, -2::-1], idx[-2:0:-1, 0]])
    r0, r1 = ring, np.roll(ring, -1)
    faces += [np.column_stack([r0, r0 + nb, r1]), np.column_stack([r1, r0 + nb, r1 + nb])]
    return verts, np.vstack(faces)


def export_stl(stock, path, max_side=300):
    import trimesh
    v, f = heightmap_mesh(stock, max_side)
    mesh = trimesh.Trimesh(vertices=v, faces=f, process=False)
    mesh.fix_normals()
    mesh.export(path)


def web_payload(stock, max_side=180):
    """Height map as base64 int16 (0.01 mm units relative to stock top)."""
    Z, f = downsample(stock.Z, max_side)
    q = np.clip(np.round((Z - stock.top) * 100), -32768, 32767).astype("<i2")
    return dict(nx=int(Z.shape[1]), ny=int(Z.shape[0]), res=float(stock.res * f),
                x0=float(stock.x0), y0=float(stock.y0), top=float(stock.top),
                base=float(stock.base), z=base64.b64encode(q.tobytes()).decode())
