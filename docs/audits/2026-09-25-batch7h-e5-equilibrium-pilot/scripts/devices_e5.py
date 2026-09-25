"""Batch 7H-E5 device builders and measurement (PLAN sections 2-4). AUDIT-ONLY SHADOW devices -- built by a new script,
never through apply_doping or any GUI/CLI entry point. Reused, unmodified: production node-write pattern
(shadow_e1.py:144-145), production equilibrium setup functions (semiconductor_equation.py:50-91), production solver
tolerances (pn_junction_iv_sweep.py:88-93), 1D mesh method (common_d1.py:30-53), J0/J1 node-position formula
(meshes_d1.py:33-45, generalized here by X_HALF instead of D1's fixed 0.5)."""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
AUD = os.path.join(ROOT, "docs", "audits")
sys.path.insert(0, os.path.join(AUD, "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts"))
import common_e1 as ce  # noqa: E402
import shadow_e1 as se1  # noqa: E402  (E1, read-only: measure(), flags(), PARAMS)

UM = 1e-4
X_HALF_UM = 5.0
N_CONC = 1e18                        # donor_conc_cm3 = acceptor_conc_cm3 (common_e1.GUI["doping"])
H_UM = 0.003125                      # E4 candidate's own finest junction spacing (e4_result.json resolution.candidate.x0_line)
E4_VTU_SHA = "85ebcbaed085b07c1dc96e407faf3252a6dbbb9d9a428660ab979d1d1c421297"
E4_NPZ_SHA = "740a643ed6c965b11ea179993eff2701d87b3c0a9a5990ace71fb2e5df482329"
E4_VTU = os.path.join(AUD, "2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate", "data", "remote_run_36143535737",
                       "outputs", "e4_out", "candidate_e4.vtu")


def cols_right(h, x_half):
    """meshes_d1.py:37-40 (cols_right), generalized from X_HALF=0.5 to an arbitrary half-width."""
    n = int(round(x_half / h))
    return [(2 * k + 1) * x_half / (2 * n) for k in range(n)]


def grid_1d_um(h, kind, x_half=X_HALF_UM):
    """meshes_d1.py:42-45 (grid_1d), generalized. kind 'J1': +-(2k+1)h/2 and +-x_half; 'J0': k h (includes x=0)."""
    n = int(round(x_half / h))
    if kind == "J1":
        c = cols_right(h, x_half)
        return sorted([-x_half, x_half] + c + [-v for v in c])
    return [(k - n) * x_half / n for k in range(2 * n + 1)]


def build_1d(dv, xs_um, device):
    """common_d1.py:30-39 (build_1d), unmodified logic, contacts named left/right (D1's own convention)."""
    m = "m_" + device
    dv.create_1d_mesh(mesh=m)
    for i, x in enumerate(xs_um):
        tag = "left" if i == 0 else ("right" if i == len(xs_um) - 1 else None)
        h = (xs_um[1] - xs_um[0]) if i == 0 else (x - xs_um[i - 1])
        if tag:
            dv.add_1d_mesh_line(mesh=m, pos=x * UM, ps=h * UM, tag=tag)
        else:
            dv.add_1d_mesh_line(mesh=m, pos=x * UM, ps=h * UM)
    dv.add_1d_contact(mesh=m, name="left", tag="left", material="metal")
    dv.add_1d_contact(mesh=m, name="right", tag="right", material="metal")
    dv.add_1d_region(mesh=m, material="Si", region="Si", tag1="left", tag2="right")
    dv.finalize_mesh(mesh=m)
    dv.create_device(mesh=m, device=device)
    return ["left", "right"]


def write_doping(dv, device, region, kind):
    """doping_mapping.py:864,868 (Donors/Acceptors step() equations); DEVSIM step(0)=1 gives J0's dual assignment.
    kind: 'J0' (real production rule, includes a node exactly at x=0) or 'J1' (staggered comparison, no such node).
    Written via node_model+set_node_values (shadow_e1.py:144-145), never through apply_doping."""
    x = np.array(dv.get_node_model_values(device=device, region=region, name="x")) / UM
    if kind == "J1":
        assert not np.any(x == 0.0), "J1 mesh has a node on the junction"
        donors, acceptors = np.where(x > 0, N_CONC, 0.0), np.where(x < 0, N_CONC, 0.0)
    else:
        donors, acceptors = np.where(x >= 0, N_CONC, 0.0), np.where(x <= 0, N_CONC, 0.0)
    for name, vals in (("Donors", donors), ("Acceptors", acceptors), ("NetDoping", donors - acceptors)):
        dv.node_model(device=device, region=region, name=name, equation="0")
        dv.set_node_values(device=device, region=region, name=name, values=[float(v) for v in vals])
    return {"n_nodes": int(len(x)), "n_x0_nodes": int(np.sum(x == 0.0)), "kind": kind}


def import_e4_candidate(work):
    """PLAN section 2 D2D. Regenerates nothing -- reuses the already-portable, hash-verified 7H-E4 artifact directly,
    inspected the same way every E1-E4 script did (build_process_result reads the mesh's own Material tags)."""
    import shutil
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.mesh.viennaps_adapter import build_process_result
    vtu_sha = ce.sha_file(E4_VTU)
    ident = {"vtu_sha256": vtu_sha, "expected": E4_VTU_SHA, "equal": vtu_sha == E4_VTU_SHA}
    local = os.path.join(work, "candidate_e4.vtu")
    shutil.copyfile(E4_VTU, local)
    result = build_process_result({"final_mesh": local, "snapshots": []})
    imp = import_process_result(result, mesh_name="e5_d2d_mesh", device_name="e5_d2d_device",
                                contact_regions=["Si"], contact_axis="x", length_scale_to_cm=UM)
    return imp, ident


def solve_call(dv, calls, **kw):
    """One devsim.solve() call, counted and recorded. Never retried with unchanged settings (PLAN section 3.4)."""
    import time
    t = time.time()
    try:
        r = dv.solve(type="dc", info=True, **kw)
        ok, err = True, None
    except Exception as e:  # noqa: BLE001
        r, ok, err = None, False, repr(e)[:300]
    rec = {"k": kw, "ok": ok, "error": err, "wall_s": round(time.time() - t, 3)}
    if r:
        last = r["iterations"][-1]["devices"][0]
        rec.update({"converged": bool(r["converged"]), "n_iterations": len(r["iterations"]),
                    "final_device_relative_error": last["relative_error"], "final_device_absolute_error": last["absolute_error"],
                    "final_equations": {e["name"]: {"abs": e["absolute_error"], "rel": e["relative_error"]}
                                        for reg in last["regions"] for e in reg["equations"]}})
    else:
        rec["converged"] = False
    calls.append(rec)
    return rec


def measure_poisson(dv, device, region, contacts):
    """PLAN section 4, Poisson-only stage: Potential, y-symmetry (2D only), ElectricField, contact potentials."""
    x = np.array(dv.get_node_model_values(device=device, region=region, name="x")) / UM
    psi = np.array(dv.get_node_model_values(device=device, region=region, name="Potential"))
    ef = np.array(dv.get_edge_model_values(device=device, region=region, name="ElectricField"))
    out = {"psi_contact_V": {c: float(psi[x == (x.min() if c == contacts[0] else x.max())].mean()) for c in contacts},
           "max_abs_ElectricField_V_per_cm": float(np.max(np.abs(ef))), "psi_range_V": [float(psi.min()), float(psi.max())],
           "psi_finite": bool(np.all(np.isfinite(psi)))}
    try:
        y = np.array(dv.get_node_model_values(device=device, region=region, name="y")) / UM
        two_d = bool(np.any(y != y[0]))
    except Exception:  # noqa: BLE001
        two_d, y = False, None
    out["two_d"] = two_d
    if two_d:
        sym = {}
        for xc in (0.0, 0.05, -0.05, 0.15, -0.15):
            m = np.abs(x - xc) < 1e-6
            if m.sum() > 1:
                vals = psi[m]
                sym[f"{xc:+.3f}"] = {"n_y": int(m.sum()), "spread_V": float(vals.max() - vals.min())}
        out["y_symmetry"] = sym
        out["y_symmetry_max_spread_V"] = max((v["spread_V"] for v in sym.values()), default=None)
    return out


def cut_profile(dv, device, region, x_um_list):
    """Potential / ElectricField(magnitude, per-edge nearest) / NetDoping at specific x positions, at the mesh's own
    middle-y row for 2D (nearest actual node row to the mid-depth), or the single 1D line."""
    x = np.array(dv.get_node_model_values(device=device, region=region, name="x")) / UM
    psi = np.array(dv.get_node_model_values(device=device, region=region, name="Potential"))
    nd = np.array(dv.get_node_model_values(device=device, region=region, name="NetDoping"))
    try:
        y = np.array(dv.get_node_model_values(device=device, region=region, name="y")) / UM
        y_mid = sorted(np.unique(y))[len(np.unique(y)) // 2]
        row = np.abs(y - y_mid) < 1e-9
    except Exception:  # noqa: BLE001
        row, y_mid = np.ones(len(x), dtype=bool), None
    out = {"row_y_um": y_mid, "cuts": {}}
    for xc in x_um_list:
        m = row & (np.abs(x - xc) < 1e-6)
        if not m.any():
            j = np.argmin(np.abs(x[row] - xc))
            xr = x[row]
            m = row & (np.abs(x - xr[j]) < 1e-9)
        out["cuts"][f"{xc:+.2f}"] = {"x_actual_um": float(x[m].mean()), "n_nodes": int(m.sum()),
                                     "Potential_V": float(psi[m].mean()), "NetDoping_cm-3": float(nd[m].mean())}
    return out


def doping_integrals(dv, device, region, kind):
    """PLAN section 4: DEVSIM NodeVolume integral (real device quantity) + geometric continuum reference, kept separate."""
    x = np.array(dv.get_node_model_values(device=device, region=region, name="x")) / UM
    nv = np.array(dv.get_node_model_values(device=device, region=region, name="NodeVolume"))
    don = np.array(dv.get_node_model_values(device=device, region=region, name="Donors"))
    acc = np.array(dv.get_node_model_values(device=device, region=region, name="Acceptors"))
    out = {"kind": kind}
    for nm, c in (("donor", don), ("acceptor", acc)):
        out[f"{nm}_NodeVolume_integral"] = float((c * nv).sum())
    try:
        y = np.array(dv.get_node_model_values(device=device, region=region, name="y")) / UM
        depth = float(y.max() - y.min())
    except Exception:  # noqa: BLE001
        depth = 1.0
    out["geometric_continuum_reference"] = N_CONC * depth * X_HALF_UM * UM * UM
    out["all_finite"] = bool(np.all(np.isfinite(don)) and np.all(np.isfinite(acc)) and np.all(np.isfinite(nv)))
    return out


def analytic_reference(dv, device, region):
    """Sze & Ng depletion approximation, ch. 2 (already used in 7H-E1/E4's own PLANs), DEVSIM's own parameters
    (not textbook constants). Explicitly an idealized zero-width-junction estimate, never the PDE solution."""
    import math
    eps = float(dv.get_parameter(device=device, region=region, name="Permittivity"))
    vt = float(dv.get_parameter(device=device, region=region, name="V_t"))
    ni = float(dv.get_parameter(device=device, region=region, name="n_i"))
    q = float(dv.get_parameter(device=device, region=region, name="ElectronCharge"))
    na = nd = N_CONC
    vbi = vt * math.log(na * nd / ni ** 2)
    w_cm = math.sqrt(2 * eps * vbi / q * (na + nd) / (na * nd))
    ld_cm = math.sqrt(eps * vt / (q * N_CONC))
    return {"assumptions": "Sze & Ng, Physics of Semiconductor Devices 3rd ed. ch.2; abrupt symmetric junction, full "
                           "depletion, infinite neutral regions, DEVSIM's own eps/V_t/n_i/q (not textbook constants); "
                           "NOT the PDE solution, an idealized zero-width-junction estimate",
            "V_bi_V": vbi, "W_0V_um": w_cm / UM, "L_D_um": ld_cm / UM, "eps_F_cm": eps, "V_t_V": vt, "n_i_cm-3": ni}
