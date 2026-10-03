import sqlite3, numpy as np
DT = np.dtype([("sq", "<f4"), ("parent", "<i4", 3), ("inside", "u1"), ("observed", "u1"), ("site", "u1"), ("pad", "u1")])
def nvblox_grid(path, layers=(3, 4), voxel=0.05):
    db = sqlite3.connect(path)
    rows = db.execute("select index_x, index_y, index_z, data from esdf_layer_data where index_z = 0").fetchall()
    bx = np.array([r[0] for r in rows]); by = np.array([r[1] for r in rows])
    x0, y0 = bx.min() * 8, by.min() * 8
    W, H = (bx.max() + 1) * 8 - x0, (by.max() + 1) * 8 - y0
    dist = np.full((H, W), np.inf); obs = np.zeros((H, W), bool); ins = np.zeros((H, W), bool)
    for ix, iy, iz, data in rows:
        v = np.frombuffer(data, dtype=DT).reshape(8, 8, 8)
        sl = v[:, :, list(layers)]
        o = sl["observed"].astype(bool).any(axis=2)
        i = sl["inside"].astype(bool).any(axis=2)
        dd = np.where(sl["observed"].astype(bool), np.sqrt(sl["sq"]) * voxel, np.inf).min(axis=2)
        X = ix * 8 - x0; Y = iy * 8 - y0
        dist[Y:Y+8, X:X+8] = dd.T; obs[Y:Y+8, X:X+8] = o.T; ins[Y:Y+8, X:X+8] = i.T
    clearance = np.where(~obs, -1, np.where(ins, 0, np.minimum(np.round(dist * 1000), 32767))).astype(np.int16)
    clearance = clearance[::-1]
    origin_x = x0 * voxel
    origin_z = -(y0 + H) * voxel
    return (origin_x, origin_z), voxel, clearance
if __name__ == "__main__":
    import sys
    o, r, c = nvblox_grid(sys.argv[1])
    print(o, c.shape, (c == 0).sum(), (c > 0).sum(), (c == -1).sum())
    if len(sys.argv) > 2:
        d = np.load(sys.argv[2]); ref = d["clearance"]; print("ref", tuple(d["origin"]), ref.shape, (ref == 0).sum(), (ref > 0).sum())

TSDF = np.dtype([("d", "<f4"), ("w", "<f4")])
def tsdf_occupancy(path, voxel=0.05, band=(0.04, 0.45)):
    db = sqlite3.connect(path)
    rows = db.execute("select index_x, index_y, index_z, data from tsdf_layer_data").fetchall()
    pts = []; vals = []
    for ix, iy, iz, data in rows:
        v = np.frombuffer(data, dtype=TSDF).reshape(8, 8, 8)
        x, y, z = np.meshgrid(np.arange(8), np.arange(8), np.arange(8), indexing="ij")
        keep = v["w"] > 1e-4
        if not keep.any(): continue
        X = (ix * 8 + x[keep] + 0.5) * voxel; Y = (iy * 8 + y[keep] + 0.5) * voxel; Z = (iz * 8 + z[keep] + 0.5) * voxel
        pts.append(np.column_stack([X, Y, Z])); vals.append(v["d"][keep])
    P = np.concatenate(pts); D = np.concatenate(vals)
    surf = np.abs(D) < 0.6 * voxel
    zs = P[surf, 2]
    hist, edges = np.histogram(zs, bins=np.arange(zs.min(), zs.max() + voxel, voxel))
    floor = edges[np.argmax(hist)] + 0.5 * voxel
    h = P[:, 2] - floor
    inband = (h >= band[0]) & (h <= band[1])
    occ = inband & surf
    free = inband & (D > voxel)
    gx = np.floor(P[:, 0] / voxel).astype(int); gy = np.floor(P[:, 1] / voxel).astype(int)
    x0, y0 = gx.min(), gy.min(); W, H = gx.max() - x0 + 1, gy.max() - y0 + 1
    cells = np.full((H, W), -1, np.int8)
    cells[gy[free] - y0, gx[free] - x0] = 0
    cells[gy[occ] - y0, gx[occ] - x0] = 1
    cells = cells[::-1]
    return (x0 * voxel, -(y0 + H) * voxel), voxel, cells, floor
