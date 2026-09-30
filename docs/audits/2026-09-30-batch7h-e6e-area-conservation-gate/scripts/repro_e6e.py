"""Batch 7H-E6E step 1: does the UNMODIFIED production import_process_result() accept the E6D G2 mesh?
Remote only (GitHub-hosted runner). Each mesh (E6D G0 = E6A L5, G1, G2; raw files unchanged, sha-gated) is imported in its own process with
the same arguments the E6D stage used; devsim.solve and every DEVSIM node/edge write API are trapped (counted, and a call raises).
Records: whether a device is returned or an exception raised, sum(NodeVolume) vs the exact triangle area of the file's own coordinates.
usage: repro_e6e.py [--validate-only]        (driver)   |   repro_e6e.py one <out dir> <name>   (worker)"""
import hashlib
import os
import subprocess
import sys
import time
import traceback
from fractions import Fraction

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
AUD = os.path.join(ROOT, "docs", "audits")
OUT = os.path.join(ROOT, "e6e_repro_out")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402

E6A = os.path.join(AUD, "2026-09-28-batch7h-e6a-mesh-family", "data", "remote_run_36388479824", "outputs", "e6a_out")
E6D = os.path.join(AUD, "2026-09-29-batch7h-e6d-noncore-refinement", "data", "remote_run_36538742843", "outputs", "e6d_out")
MESHES = {"G0": (os.path.join(E6A, "level_L5.vtu"), "907f688e71af3bc0ebd15ea20bfbcd9fec5e9ade1d867e50f0b24da6c48e8c70"),
          "G1": (os.path.join(E6D, "mesh_G1.vtu"), "48bcf8ea231c5c59a09a2c7089bd6e61af8688c57b73c723d6753305753f4f02"),
          "G2": (os.path.join(E6D, "mesh_G2.vtu"), "d9229e8378eb3348523875825dbaf5e9479c968d444c3888dc157a78586c7dae")}
WRITE_APIS = ("solve", "set_node_values", "set_node_value", "node_model", "edge_model", "node_solution", "equation", "contact_equation")
UM = 1e-4


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def exact_area_um2(P, T):
    """Sum of |orientation| / 2 with the exact binary values of the file's float32 x, y (Fraction); per material tag."""
    X = [Fraction(float(v)) for v in P[:, 0]]
    Y = [Fraction(float(v)) for v in P[:, 1]]
    tot = Fraction(0)
    for a, b, c in T.tolist():
        tot += abs((X[b] - X[a]) * (Y[c] - Y[a]) - (Y[b] - Y[a]) * (X[c] - X[a]))
    return tot / 2


def one(outd, name):
    import numpy as np
    import meshio
    import devsim as dv
    res = {"name": name, "process_id": os.getpid(), "calls": {k: 0 for k in WRITE_APIS}, "status": None}
    real = {k: getattr(dv, k) for k in WRITE_APIS}

    def trap(k):
        def f(*a, **kw):
            res["calls"][k] += 1
            raise RuntimeError(f"E6E repro forbids devsim.{k}")
        return f
    for k in WRITE_APIS:
        setattr(dv, k, trap(k))
    imp = None
    try:
        path, want = MESHES[name]
        res["input_sha256"], res["input_sha_ok"] = sha(path), sha(path) == want
        if not res["input_sha_ok"]:
            res["status"] = "INPUT_IDENTITY_FAIL"
            return finish(outd, res, dv, real, imp)
        m = meshio.read(path)
        blk = next(c for c in m.cells if c.type == "triangle")
        tags = m.cell_data["Material"][m.cells.index(blk)]
        area = {}
        for t in sorted(set(int(v) for v in tags)):
            area[t] = exact_area_um2(m.points, blk.data[tags == t])
        from tcad.mesh.viennaps_adapter import build_process_result
        from tcad.device.devsim.mesh_import import import_process_result
        pr = build_process_result({"final_mesh": path, "snapshots": []})
        t0 = time.time()
        try:
            imp = import_process_result(pr, mesh_name=f"e6e_{name}_mesh", device_name=f"e6e_{name}_device", contact_regions=["Si"],
                                        contact_axis="x", length_scale_to_cm=UM)
            res["import"] = {"returned_device": True, "device": imp.device, "regions": imp.regions, "contacts": imp.contacts,
                             "wall_s": time.time() - t0}
        except Exception as e:  # noqa: BLE001
            res["import"] = {"returned_device": False, "exception_type": type(e).__name__, "exception": ce.USER_PATH.sub("<USERPROFILE>", repr(e))[:500]}
            res["devices_after_exception"] = list(dv.get_device_list())
            res["status"] = "IMPORT_RAISED"
            return finish(outd, res, dv, real, imp)
        regs = {}
        for r in imp.regions:
            nv = np.array(dv.get_node_model_values(device=imp.device, region=r, name="NodeVolume"), dtype=np.float64)
            tag = next(t.tag for t in pr.material_regions if t.name == r)
            a_cm2 = float(area[tag]) * UM * UM
            regs[r] = {"n_nodes": int(len(nv)), "sum_NodeVolume_cm2": float(nv.sum()), "exact_triangle_area_um2": f"{area[tag].numerator}/{area[tag].denominator}",
                       "triangle_area_cm2": a_cm2, "relative_difference": float(nv.sum() / a_cm2 - 1.0), "min_NodeVolume": float(nv.min()),
                       "all_finite": bool(np.isfinite(nv).all())}
        res["regions"] = regs
        res["status"] = "IMPORTED"
    except Exception as e:  # noqa: BLE001
        res["status"] = "WORKER_ERROR"
        res["error"] = ce.USER_PATH.sub("<USERPROFILE>", repr(e))[:500]
        res["traceback"] = ce.USER_PATH.sub("<USERPROFILE>", traceback.format_exc()[-3000:])
    return finish(outd, res, dv, real, imp)


def finish(outd, res, dv, real, imp):
    for k, f in real.items():
        setattr(dv, k, f)
    if imp is not None:
        try:
            dv.delete_device(device=imp.device)
            dv.delete_mesh(mesh=imp.mesh)
            res["cleanup"] = "ok"
        except Exception as e:  # noqa: BLE001
            res["cleanup"] = ce.USER_PATH.sub("<USERPROFILE>", repr(e))[:300]
    res["devices_left"] = list(dv.get_device_list())
    ce.dump_strict(res, os.path.join(outd, f"repro_{res['name']}.json"))
    print(f"[e6e-repro] {res['name']}: status={res['status']} import={res.get('import')} regions={res.get('regions')} calls={res['calls']}",
          flush=True)
    return 0 if res["status"] in ("IMPORTED", "IMPORT_RAISED") else 1


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "one":
        return one(os.path.abspath(sys.argv[2]), sys.argv[3])
    if "--validate-only" in sys.argv:
        for n, (p, w) in MESHES.items():
            print(f"[e6e-repro] {n} sha ok: {sha(p) == w}", flush=True)
        return 0
    if not (os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted"):
        print("[e6e-repro] refusing to run: not a GitHub-hosted runner", flush=True)
        return 2
    os.makedirs(OUT, exist_ok=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    code = subprocess.run(["git", "diff", "--quiet", "023bcb90f8b8a0972d6df84f097ca6387f0ab82a", "--", "tcad", "tests",
                           "tcad_2d_stagewise.py", "examples"], cwd=ROOT).returncode
    rc = {}
    for n in MESHES:
        p = subprocess.run([sys.executable, __file__, "one", OUT, n], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=1800)
        print(p.stdout[-20000:], flush=True)
        if p.stderr.strip():
            print("[e6e-repro][stderr]", p.stderr[-3000:], flush=True)
        rc[n] = p.returncode
    import devsim
    import numpy
    summ = {"head": head, "production_code_identical_to_023bcb90_rc": code, "worker_rc": rc, "devsim_version": getattr(devsim, "__version__", None),
            "numpy_version": numpy.__version__, "python": sys.version.split()[0],
            "files": {f: ce.sha_file(os.path.join(OUT, f)) for f in sorted(os.listdir(OUT))}}
    ce.dump_strict(summ, os.path.join(OUT, "repro_summary.json"))
    print(f"[e6e-repro] summary {summ}", flush=True)
    return 0 if all(v == 0 for v in rc.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
