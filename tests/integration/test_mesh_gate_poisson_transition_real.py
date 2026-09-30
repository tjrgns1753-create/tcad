#!/usr/bin/env python3
"""Poisson / Laplace controls on meshes made by structured_lateral_refine (Batch 7H-E6H). Criteria, fixed before any run:
docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/CRITERIA.md (section B) and CRITERIA_ERRATUM_1.md. A NUMERICAL-EQUATION
check on small meshes -- not PN / DD / current validation.

usage: test_mesh_gate_poisson_transition_real.py [out_dir]   (writes poisson_transition.json there)

Domain 2 um x 0.5 um, length scale 1e-4 cm/um, eps = 1, rho = 8 eps / L^2 (L = 2e-4 cm), exact psi = rho x (L - x) / (2 eps), max 1 V.
Base grid n = 8, 16, 32, 64 columns (h = 2 / n um), n / 4 rows. Families: one-sided (center 1.0 um, rings [h, h/2]) and two-sided
(centers 2h, 5h, ring [h]); uniform control = the n = 8 base grid. DEVSIM public API only."""
import json
import math
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "docs/audits/2026-10-01-batch7h-e6h-conformity-poisson"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AUDIT / "scripts"))

EPS, L_UM, H_UM = 1.0, 2.0, 0.5
L_CM = L_UM * 1.0e-4
RHO = 8.0 * EPS / (L_CM ** 2)
MATCH_TOL = 1.0e-9          # DEVSIM vs independent numpy Voronoi solve, relative to max exact
LINEAR_TOL = 1.0e-9         # linear precision and uniform-mesh quadratic
MIN_ORDER = 1.5             # observed order between consecutive resolutions


def build(family, n):
    from tcad.device.devsim.mesh_refine import structured_lateral_refine
    h = L_UM / n
    xs = [h * i for i in range(n + 1)]
    ys = [h * j for j in range(n // 4 + 1)]
    nx = n
    P = np.array([[x, y, 0.0] for y in ys for x in xs])
    T = []
    for j in range(len(ys) - 1):
        for i in range(nx):
            a, b = j * (nx + 1) + i, j * (nx + 1) + i + 1
            T += [(a, b, b + nx + 1), (a, b + nx + 1, a + nx + 1)]
    T = np.array(T)
    G = np.full(len(T), 1, dtype=np.int32)
    if family == "uniform":
        return P, T, h
    if family == "one_sided":
        c, r = [1.0], [h, h / 2]
    else:
        c, r = [2 * h, 5 * h], [h]
    P1, T1, _, _ = structured_lateral_refine(P, T, G, c, r)
    return P1, T1, h


def presence(family, P, T, n, h):
    from conformity_e6h import count_apex_triangles
    out = {"apex_triangles": count_apex_triangles(P, T)}
    if family == "one_sided":
        out["expected_apex"] = 6 * (n // 4)
        out["ok"] = out["apex_triangles"] == out["expected_apex"]
    elif family == "two_sided":
        out["expected_apex"] = 2 * (n // 4)
        x = P[:, 0]
        strip = sum(1 for t in T.tolist() if all(3 * h <= x[v] <= 4 * h for v in t))
        ids = {(float(a), float(b)): k for k, (a, b) in enumerate(P[:, :2].tolist())}
        u, v = ids.get((3 * h, h / 2)), ids.get((4 * h, h / 2))
        edge = False
        if u is not None and v is not None:
            edge = any({u, v} <= set(t) for t in T.tolist())
        out.update({"triangles_in_coarse_strip": strip, "expected_in_coarse_strip": n, "midline_edge_present": edge})
        out["ok"] = out["apex_triangles"] == out["expected_apex"] and strip == n and edge
    else:
        out["ok"] = out["apex_triangles"] == 0
    return out


def solve_case(dv, P, T, mode, tag):
    """mode 'poisson' (rho, psi=0 both ends) or 'linear' (rho=0, psi=0 / 1 V). Returns dict with arrays matched to mesh indices."""
    import meshio
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.backends.viennaps import session
    si = int(session.require_viennaps().Material.Si)
    path = Path(tempfile.mkdtemp(prefix="e6h_poisson_")) / f"{tag}.vtu"
    meshio.write(str(path), meshio.Mesh(P, [("triangle", T)], cell_data={"Material": [np.full(len(T), si, dtype=np.int32)]}))
    calls = {"solve": 0}
    real_solve = dv.solve

    def counted(*a, **kw):
        calls["solve"] += 1
        return real_solve(*a, **kw)
    dv.solve = counted
    imported = None
    try:
        pr = build_process_result({"final_mesh": str(path), "snapshots": []})
        imported = import_process_result(pr, mesh_name=f"{tag}_mesh", device_name=f"{tag}_device", contact_regions=["Si"],
                                         contact_axis="x", length_scale_to_cm=1.0e-4)
        rep = imported.area_conservation["Si"]
        dev, reg = imported.device, "Si"
        rho = RHO if mode == "poisson" else 0.0
        v_right = 0.0 if mode == "poisson" else 1.0
        dv.set_parameter(device=dev, region=reg, name="eps_mms", value=EPS)
        dv.set_parameter(device=dev, region=reg, name="rho_mms", value=rho)
        dv.node_solution(device=dev, region=reg, name="Potential")
        dv.edge_from_node_model(device=dev, region=reg, node_model="Potential")
        dv.edge_model(device=dev, region=reg, name="Flux", equation="eps_mms*(Potential@n0-Potential@n1)*EdgeInverseLength")
        dv.edge_model(device=dev, region=reg, name="Flux:Potential@n0", equation="eps_mms*EdgeInverseLength")
        dv.edge_model(device=dev, region=reg, name="Flux:Potential@n1", equation="-eps_mms*EdgeInverseLength")
        dv.node_model(device=dev, region=reg, name="Source", equation="-rho_mms")
        dv.node_model(device=dev, region=reg, name="Source:Potential", equation="0")
        dv.equation(device=dev, region=reg, name="PotentialEquation", variable_name="Potential", edge_model="Flux", node_model="Source")
        for contact, v in (("Si_xmin", 0.0), ("Si_xmax", v_right)):
            dv.contact_node_model(device=dev, contact=contact, name=f"{contact}_bc", equation=f"Potential-({v!r})")
            dv.contact_node_model(device=dev, contact=contact, name=f"{contact}_bc:Potential", equation="1")
            dv.contact_equation(device=dev, contact=contact, name="PotentialEquation", node_model=f"{contact}_bc")
        dv.solve(type="dc", absolute_error=1.0e-12, relative_error=1.0e-12, maximum_iterations=30)
        x = np.array(dv.get_node_model_values(device=dev, region=reg, name="x"))
        y = np.array(dv.get_node_model_values(device=dev, region=reg, name="y"))
        psi = np.array(dv.get_node_model_values(device=dev, region=reg, name="Potential"))
        return {"x_cm": x, "y_cm": y, "psi": psi, "solves": calls["solve"], "area_pass": bool(rep["pass"]),
                "area_relative_uncertainty": rep["relative_uncertainty"]}
    finally:
        dv.solve = real_solve
        if imported is not None:
            dv.delete_device(device=imported.device)
            dv.delete_mesh(mesh=imported.mesh)


def key(x_um, y_um):
    return int(round(float(x_um) * 1e9)), int(round(float(y_um) * 1e9))


def run(out_dir):
    from conformity_e6h import check_conformity
    from op_analysis import solve as numpy_solve
    from tcad.device.devsim import backend
    dv = backend.require_devsim()
    results, failures = [], []
    plan = [("uniform", 8)] + [(f, n) for f in ("one_sided", "two_sided") for n in (8, 16, 32, 64)]
    for family, n in plan:
        P, T, h = build(family, n)
        rec = {"family": family, "n": n, "h_um": h, "triangles": int(len(T)), "nodes": int(len(P))}
        rec["conformity"] = check_conformity(P, T)
        rec["presence"] = presence(family, P, T, n, h)
        Pcm = P.copy()
        Pcm[:, :2] *= 1.0e-4
        for mode in ("poisson", "linear"):
            sol = solve_case(dv, P, T, mode, f"{family}_{n}_{mode}")
            order = {key(a * 1e4, b * 1e4): i for i, (a, b) in enumerate(zip(sol["x_cm"], sol["y_cm"]))}
            idx = np.array([order[key(a, b)] for a, b in P[:, :2].tolist()])
            psi = sol["psi"][idx]                          # psi in mesh-node order
            x = Pcm[:, 0] - Pcm[:, 0].min()
            if mode == "poisson":
                exact = RHO * x * (L_CM - x) / (2 * EPS)
                u_np = numpy_solve(Pcm, T, RHO, EPS)[0]
            else:
                exact = x / L_CM
                u_np = None
            scale = float(np.max(np.abs(exact)))
            err = np.abs(psi - exact)
            k = int(np.argmax(err))
            r = {"solves": sol["solves"], "area_pass": sol["area_pass"], "max_exact": scale, "max_abs_error": float(err.max()),
                 "max_rel_error": float(err.max() / scale), "max_error_node_um": [float(P[k, 0]), float(P[k, 1])]}
            if u_np is not None:
                r["max_rel_diff_vs_numpy_voronoi"] = float(np.max(np.abs(psi - u_np)) / scale)
            rec[mode] = r
        results.append(rec)
        print(family, n, json.dumps({k: rec[k] for k in ("triangles", "nodes")}), "poisson rel err", rec["poisson"]["max_rel_error"],
              "vs numpy", rec["poisson"]["max_rel_diff_vs_numpy_voronoi"], "linear rel err", rec["linear"]["max_rel_error"], flush=True)
    # acceptance
    for rec in results:
        tag = f"{rec['family']} n={rec['n']}"
        if not rec["conformity"]["pass"]:
            failures.append(f"{tag}: conformity {rec['conformity']}")
        if not rec["presence"]["ok"]:
            failures.append(f"{tag}: transition presence {rec['presence']}")
        for mode in ("poisson", "linear"):
            r = rec[mode]
            if not r["area_pass"] or r["solves"] < 1:
                failures.append(f"{tag} {mode}: area gate {r['area_pass']} solves {r['solves']}")
        if rec["poisson"]["max_rel_diff_vs_numpy_voronoi"] > MATCH_TOL:
            failures.append(f"{tag}: DEVSIM differs from numpy Voronoi solve by {rec['poisson']['max_rel_diff_vs_numpy_voronoi']:.3e}")
        if rec["linear"]["max_rel_error"] > LINEAR_TOL:
            failures.append(f"{tag}: linear precision error {rec['linear']['max_rel_error']:.3e}")
        if rec["family"] == "uniform" and rec["poisson"]["max_rel_error"] > LINEAR_TOL:
            failures.append(f"{tag}: uniform quadratic error {rec['poisson']['max_rel_error']:.3e}")
    orders = {}
    for fam in ("one_sided", "two_sided"):
        seq = [r for r in results if r["family"] == fam]
        errs = [r["poisson"]["max_rel_error"] for r in seq]
        orders[fam] = [math.log2(a / b) if b > 0 else float("inf") for a, b in zip(errs[:-1], errs[1:])]
        if not all(b < a for a, b in zip(errs[:-1], errs[1:])) or not all(o >= MIN_ORDER for o in orders[fam]):
            failures.append(f"{fam}: errors {errs} orders {orders[fam]}")
    summary = {"results": results, "observed_orders": orders, "failures": failures, "pass": not failures,
               "constants": {"EPS": EPS, "RHO": RHO, "L_cm": L_CM, "MATCH_TOL": MATCH_TOL, "LINEAR_TOL": LINEAR_TOL, "MIN_ORDER": MIN_ORDER}}
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "poisson_transition.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(summary, f, indent=1)
    assert list(dv.get_device_list()) == []
    print("observed orders:", orders)
    if failures:
        print("FAILURES:\n" + "\n".join(failures))
        return 1
    print("MESH GATE POISSON TRANSITION CONTROL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
