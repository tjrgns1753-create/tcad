"""Batch 7H-E6F: one remote size check of the blue candidate (refine_blue.py, queue version) at the GUI default scale. Pure geometry;
no DEVSIM import, no solve. Input: the E6A wafer_volume.vtu (GUI-default wafer, 40000 triangles, sha-gated) with the GUI-default
implant-windows doping (acceptor background 1e17, windows [-1.6,-0.6] and [0.6,1.6] um at 1e20 donor) -> the production
derive_implant_windows_refinement predicates, applied one pass each as the production graded path does. The 400000-triangle cap is
checked from the closure's child count BEFORE any output array is built; the run stops at 540 s wall (before starting a pass) inside the
600 s job budget. The old module (byte copy of production) is run on the same input for scale only. Every pass is written to JSON at
once. Exact geometric checks are NOT run here (NOT_VERIFIED for this case); they were done on the small fixtures.
usage: big_blue_e6f.py [--validate-only]"""
import hashlib
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import refine_blue  # noqa: E402
import refine_old  # noqa: E402

WAFER = os.path.join(ROOT, "docs/audits/2026-09-28-batch7h-e6a-mesh-family/data/remote_run_36388479824/outputs/e6a_out/wafer_volume.vtu")
WAFER_SHA = None   # recorded, compared with the local value printed by --validate-only
CAP = 400000
DEADLINE_S = 540.0
OUT = os.path.join(ROOT, "e6f_big_out")


def main():
    import meshio
    from tcad.mesh.interface import MaterialRegion, ProcessResult
    from tcad.physics.doping import apply_implant_windows_doping
    from tcad.device.devsim.mesh_import import derive_implant_windows_refinement
    sha = hashlib.sha256(open(WAFER, "rb").read()).hexdigest()
    mods = {n: hashlib.sha256(open(os.path.join(HERE, f), "rb").read().replace(b"\r\n", b"\n")).hexdigest()
            for n, f in (("refine_old", "refine_old.py"), ("refine_blue", "refine_blue.py"))}
    if "--validate-only" in sys.argv:
        print({"wafer_sha256": sha, "modules_lf_sha256": mods})
        return 0
    os.makedirs(OUT, exist_ok=True)
    res = {"wafer_sha256": sha, "modules_lf_sha256": mods, "cap_triangles": CAP, "deadline_s": DEADLINE_S, "exact_geometry": "NOT_VERIFIED",
           "blue": {"passes": [], "state": None}, "old": {"passes": []}}
    path = os.path.join(OUT, "e6f_big_result.json")

    def save():
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1)
    m = meshio.read(WAFER)
    P0, T0, G0 = m.points, m.cells[0].data, m.cell_data["Material"][0]
    pr = ProcessResult(volume_mesh_path=WAFER, material_field="Material", material_regions=[MaterialRegion(name="Si", tag=int(G0[0]))])
    wr = apply_implant_windows_doping(pr, region="Si", axis="x", donor_background_cm3=0.0, acceptor_background_cm3=1e17,
                                      windows=[{"min_um": -1.6, "max_um": -0.6, "donor_conc_cm3": 1e20, "acceptor_conc_cm3": 0.0},
                                               {"min_um": 0.6, "max_um": 1.6, "donor_conc_cm3": 1e20, "acceptor_conc_cm3": 0.0}],
                                      chemical_state="ACTIVE")
    preds = derive_implant_windows_refinement(wr.doping, P0, T0)
    res["input"] = {"triangles": int(len(T0)), "points": int(len(P0)), "predicates": len(preds)}
    save()
    t_all = time.time()
    P, T, G = P0, T0, G0
    for k, p in enumerate(preds):
        if time.time() - t_all > DEADLINE_S:
            res["blue"]["state"] = f"TIMEOUT before pass {k}"
            break
        t = time.time()
        c = np.asarray(P, np.float64)[np.asarray(T)].mean(axis=1)
        marked = [bool(p(x)) for x in c]
        st = {"pass": k, "marked_by_predicate": int(sum(marked))}
        try:
            P, T, G = refine_blue.refine_once_blue(P, T, G, marked, cap=CAP, stats=st)
            st["refined_outside_predicate"] = st["red"] + st["green"] + st["blue"] - st["marked_by_predicate"]
            st["wall_s"] = round(time.time() - t, 2)
            res["blue"]["passes"].append(st)
            save()
            print(json.dumps(st), flush=True)
        except refine_blue.ResourceLimit as e:
            st["refined_outside_predicate"] = st.get("red", 0) + st.get("green", 0) + st.get("blue", 0) - st["marked_by_predicate"]
            st["wall_s"] = round(time.time() - t, 2)
            st["resource_limit"] = str(e)
            res["blue"]["passes"].append(st)
            res["blue"]["state"] = f"RESOURCE_LIMIT at pass {k}"
            save()
            print(json.dumps(st), flush=True)
            break
    else:
        res["blue"]["state"] = "COMPLETED"
    res["blue"]["wall_s"] = round(time.time() - t_all, 2)
    save()
    t = time.time()
    P, T, G = P0, T0, G0
    for k, p in enumerate(preds):
        P, T, G = refine_old.refine_mesh_near(P, T, G, p, levels=1)
        res["old"]["passes"].append({"pass": k, "output_triangles": int(len(T)), "output_points": int(len(P))})
    res["old"]["wall_s"] = round(time.time() - t, 2)
    save()
    print(json.dumps(res), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
