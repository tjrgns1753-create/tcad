"""Batch 7H-C section 9: linear Laplace / Ohmic (sigma = 1 S/cm, dV = 1 V) on
L3 before / after with E1, E2 and E1 + signed edge_couple_model override.
Each configuration runs in its own subprocess via dev_run.py."""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-23-batch7h-b-nodevolume-mechanism", "scripts"))
import formulas as fm  # noqa: E402

I_AN = 0.5  # sigma * H/L * dV with H/L = 2/4


def zone(x_um):
    d = abs(x_um)
    return "band" if d < 0.1 else ("ring" if d < 0.3 else "outer")


def main():
    mesh = json.load(open(os.path.join(DATA, "l3_meshes.json"), encoding="utf-8"))
    P = np.array(mesh["points_um"])
    runs = {}
    for m in ("L3_before", "L3_after"):
        for tag, cfg in (("E1", {"flux": "E1"}), ("E2", {"flux": "E2"}), ("E1_signed", {"flux": "E1", "overrides": {"edge_couple_model": "signed"}})):
            c = {"exp": "laplace", "mesh": m, **cfg}
            p = subprocess.run([sys.executable, os.path.join(HERE, "dev_run.py"), json.dumps(c)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=1800, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            r = json.loads(p.stdout.split("===RESULT_JSON===", 1)[1].strip().splitlines()[0])
            runs[f"{m}_{tag}"] = r
            print(m, tag, "error" if "error" in r else "ok", r.get("error", "")[:200])
    summary = {}
    for key, r in runs.items():
        if "error" in r:
            summary[key] = {"error": r["error"]}
            continue
        m = key.rsplit("_E", 1)[0]
        tris = mesh[m]
        obt = np.zeros(len(P), dtype=int)
        for t in tris:
            if min(fm.tri_parts(P[t] * 1e-4)[0]) < 0:
                for v in t:
                    obt[v] += 1
        g = r["regions"]["R"]
        res = {int(k): v for k, v in g["residual_at_analytic_free"].items()}
        err = {int(k): v for k, v in g["err_free_V"].items()}
        by_zone = {z: {"n_free": 0, "residual_L1": 0.0, "residual_max_abs": 0.0, "err_max_abs_V": 0.0} for z in ("band", "ring", "outer")}
        for i, v in res.items():
            z = zone(P[i, 0])
            by_zone[z]["n_free"] += 1
            by_zone[z]["residual_L1"] += abs(v)
            by_zone[z]["residual_max_abs"] = max(by_zone[z]["residual_max_abs"], abs(v))
            by_zone[z]["err_max_abs_V"] = max(by_zone[z]["err_max_abs_V"], abs(err[i]))
        tot = sum(abs(v) for v in res.values())
        on_obt = sum(abs(v) for i, v in res.items() if obt[i] > 0)
        nz = [i for i, v in res.items() if abs(v) > 1e-12]
        Il, Ir = r["contact_current"]["left"], r["contact_current"]["right"]
        summary[key] = {"Linf_free_V": g["Linf_free_V"], "L2_free_V": g["L2_free_V"], "residual_max_abs": g["residual_at_analytic_free_max_abs"],
                        "residual_L1": tot, "fraction_residual_L1_on_obtuse_incident_nodes": on_obt / tot if tot else None,
                        "n_free_nodes_residual_gt_1e-12": len(nz), "n_of_those_obtuse_incident": sum(1 for i in nz if obt[i] > 0),
                        "by_zone": by_zone, "I_left_A_per_cm": Il, "I_right_A_per_cm": Ir, "KCL_sum": Il + Ir,
                        "I_rel_err_vs_0.5": abs(abs(Ir) - I_AN) / I_AN,
                        "sum_NodeVolume_over_area": g["sum_NodeVolume_cm2"] / g["area_cm2"],
                        "n_negative_signed_edge_couples": r["override_info"].get("n_negative_signed_edge_couples_R")}
        print(key, {k: v for k, v in summary[key].items() if k != "by_zone"})
        print("   by_zone", summary[key]["by_zone"])
    with open(os.path.join(DATA, "l3_flux_results.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
