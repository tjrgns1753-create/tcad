"""Batch 7H-D4 worker: ONE configuration per process -> run JSON + compressed node-state archive.

Reuses the 7H-D3 worker (build, record, readback, geometry check, timed solve) and the 7H-D2 modules READ-ONLY;
nothing there is modified. Differences from worker_d3.run (required by the D4 PLAN):
  * fixture identity reads the file that actually holds the key (fixtures_d2.json for h = 0.00125 um);
  * node arrays Potential / Electrons / Holes at every recorded point go to <out>.npz (float64, compressed);
  * sha256 of the DEVSIM node x, y arrays and element list, and of the archive, are written to the JSON.
cfg: {"id", "kind": "2d", "fam", "variant", "h", "P": "P12"|"P4", "mirror": false}
usage: worker_d4.py '<cfg json>' <output json path>
"""
import hashlib
import json
import os
import sys
import time
import traceback

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-24-batch7h-d3-precision-pair-mirror", "scripts"))
import worker_d3 as w3  # noqa: E402  (7H-D3, read-only; also registers P12 in memory)

c2, w2, cd = w3.c2, w3.w2, w3.cd
REL = {"d1": "docs/audits/2026-09-23-batch7h-d1-pn-convergence/data/fixtures_d1.json",
       "d2": "docs/audits/2026-09-23-batch7h-d2-current-precision/data/fixtures_d2.json"}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fixture_identity(cfg):
    key = f"{cfg['fam']}_h{cfg['h']}"
    for tag, path in (("d2", os.path.join(c2.DATA, "fixtures_d2.json")), ("d1", os.path.join(c2.D1DATA, "fixtures_d1.json"))):
        if not os.path.exists(path):
            continue
        raw = open(path, "rb").read()
        f = json.loads(raw)
        if key not in f:
            continue
        P = np.array(f[key]["points_um"])
        tris = f[key]["triangles"]
        q = f[key]["quality"]
        coord, conn = sha(np.ascontiguousarray(P).tobytes()), sha(json.dumps(sorted(sorted(t) for t in tris)).encode())
        return {"kind": "2d", "key": key, "file": REL[tag], "file_sha256_raw": sha(raw), "n_nodes": int(len(P)),
                "n_triangles": int(len(tris)), "stored_n_nodes": q["n_nodes"], "stored_n_triangles": q["n_triangles"],
                "coordinates_sha256": coord, "stored_coordinates_sha256": q["coordinates_sha256"],
                "connectivity_sha256": conn, "stored_connectivity_sha256": q["connectivity_sha256"],
                "identical_to_stored": bool(coord == q["coordinates_sha256"] and conn == q["connectivity_sha256"]
                                            and len(P) == q["n_nodes"] and len(tris) == q["n_triangles"])}
    raise KeyError(f"fixture {key} not found")


def key(pnt):
    return pnt.replace("+", "p").replace("-", "m").replace(".", "_")


def run(cfg, npz_path):
    import devsim as dv
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    t_run = time.perf_counter()
    info = dv.get_parameter(name="info")
    out = {"cfg": cfg, "fixture": fixture_identity(cfg), "flags_at_start": c2.read_flags(dv),
           "flags_set": c2.set_precision(dv, cfg["P"]),
           "devsim": {k: info.get(k) for k in ("version", "extended_precision", "direct_solver", "math_libraries")},
           "steps": {}}
    arrays, mesh = {}, None
    p_bias, n_bias = "left_bias", "right_bias"
    for bi, branch in enumerate((w3.FWD, w3.REV)):
        tag_a, tag_b = ("A", "B0") if bi == 0 else ("Arev", "B0rev")
        out["variant_info"] = w2.build(dv, cfg)
        if bi == 0:
            out["geometry"] = w3.geometry_check(dv, cfg)
            x, y = w2.nv(dv, "x"), w2.nv(dv, "y")
            el = np.array(dv.get_element_node_list(device="d", region=cd.REGION), dtype=np.int64)
            mesh = {"x_sha256": sha(x.tobytes()), "y_sha256": sha(y.tobytes()), "elements_sha256": sha(el.tobytes()), "n_nodes": int(len(x))}
            arrays["x"], arrays["y"] = x, y
        setup_semiconductor_potential_equation("d", cd.REGION, ["left", "right"], 300.0)
        a = w3.tsolve(dv, "poisson", tag_a)
        out["steps"][tag_a] = {"info": a}
        if not a["ok"]:
            break
        setup_drift_diffusion_equation("d", cd.REGION, ["left", "right"])
        w2.diag_models(dv)

        def capture(pnt):
            arrays[f"psi_{key(pnt)}"] = w2.nv(dv, "Potential")
            arrays[f"n_{key(pnt)}"] = w2.nv(dv, "Electrons")
            arrays[f"p_{key(pnt)}"] = w2.nv(dv, "Holes")

        b = w3.tsolve(dv, "drift_diffusion", tag_b)
        rec = {"info": b}
        if b["ok"]:
            rec.update(w3.record(dv, cfg, 0.0, p_bias, n_bias))
            capture(tag_b)
        out["steps"][tag_b] = rec
        if not b["ok"]:
            break
        for v in branch:
            dv.set_parameter(device="d", name=p_bias, value=v)
            r = w3.tsolve(dv, "drift_diffusion", f"C{v:+.3f}")
            rec = {"info": r}
            if r["ok"] and v in w3.RECORD:
                rec.update(w3.record(dv, cfg, v, p_bias, n_bias))
                capture(f"C{v:+.3f}")
            out["steps"][f"C{v:+.3f}"] = rec
            if not r["ok"]:
                break
        dv.delete_device(device="d")
        dv.delete_mesh(mesh="m_d")
    np.savez_compressed(npz_path, **arrays)
    out["node_state"] = {**mesh, "npz": os.path.basename(npz_path), "npz_sha256": sha(open(npz_path, "rb").read()),
                         "arrays": sorted(arrays)}
    out["flags_at_end"] = c2.read_flags(dv)
    out["devices_left"] = list(dv.get_device_list())
    out["wall_s"] = round(time.perf_counter() - t_run, 3)
    return out


if __name__ == "__main__":
    cfg, path = json.loads(sys.argv[1]), sys.argv[2]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    try:
        res = run(cfg, path[:-5] + ".npz")
    except Exception as e:  # noqa: BLE001 - recorded, not hidden
        res = {"cfg": cfg, "error": w3.scrub(repr(e))[:500], "traceback": w3.scrub(traceback.format_exc())[-1500:]}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f)
    print(f"\n[worker_d4] wrote {os.path.basename(path)} error={'error' in res}", flush=True)
