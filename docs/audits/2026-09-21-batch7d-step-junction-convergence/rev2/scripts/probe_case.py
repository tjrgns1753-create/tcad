"""Batch 7D Rev.2 -- run exactly ONE (geometry, level, representation, shifted) case in its own fresh process
(subprocess-per-case isolation, kept from Rev.1: devsim.solve() has no `device=` filter and solves every
registered device together, so one un-torn-down device corrupts every later case in the same process --
tcad/cli/run_pipeline.py's own comment already documents this). PUBLIC DEVSIM API ONLY; see
scan_public_api_only.py for the static allowlist check. Prints one JSON result line prefixed by a marker.

Fixes three defects Codex found in Rev.1:

P0-1 (2D shift was not a shift): the shifted junction position is now computed from the mesh's OWN real node
coordinates -- x0 = the node exactly at the intended junction, x1 = the nearest node strictly to the right of
x0, xj_shifted = (x0+x1)/2 -- with preflight assertions that fail the case (not silently skip) if the shift
did not land strictly between two real nodes, or if the resulting doping arrays are identical to the aligned
case at x0. The 1D case gets the identical treatment (it was never actually verified either).

P0-2 (Vbi was circular): CreateSiliconPotentialOnlyContact sets the CONTACT node's own Potential from the same
analytic V_t/n_i/NetDoping relation used to derive the analytic V_bi, so max(Potential)-min(Potential) over a
device that INCLUDES the contact nodes is not an independent check -- it is renamed contact_potential_span /
contact_boundary_consistency_error and reported only as boundary-consistency metadata, never as validation.
Independent (public-API, solved-INTERIOR) measurements are added instead: the public `ElectricField` edge model
DEVSIM's own CreateSiliconPotentialOnly() already creates (get_edge_model_list confirmed this; not derived by
this probe), and depletion-width recovery fractions (50/90/99%) computed from the solved Electrons/Holes/Donors/
Acceptors node profiles -- both genuinely test the interior discretized solve, not a restated boundary condition.

P1 (fake iteration counts): DEVSIM's public solve() API returns no iteration count. `_solve()` no longer invents
one; on success it reports {"converged": true, "iteration_limit": N, "actual_iterations": null,
"actual_iterations_status": "UNAVAILABLE_FROM_PUBLIC_API"}. Nothing here parses devsim's stdout for a real count
and nothing reads a private/internal symbol for it.

usage: python probe_case.py <geometry:1d|2d> <level> <representation:R1|R2> <shifted:0|1> <relative_error> <maximum_iterations> <label>
"""
import json
import math
import os
import sys
import tempfile
import warnings

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
os.makedirs(DATA, exist_ok=True)

import devsim  # noqa: E402
from devsim.python_packages.simple_physics import (  # noqa: E402
    CreateSiliconPotentialOnly, CreateSiliconPotentialOnlyContact,
    CreateSiliconDriftDiffusion, CreateSiliconDriftDiffusionAtContact,
    SetSiliconParameters, GetContactBiasName, ece_name, hce_name,
)
from devsim.python_packages.model_create import CreateSolution  # noqa: E402

ND, NA = 1.0e18, 1.0e18
BIAS_1D = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
BIAS_2D = [-0.3, 0.0, 0.3, 0.4]
RECIPE_2D = {"grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0, "silicon_depth_um": 2.0}
XJ_2D_UM, LENGTH_SCALE = 0.0, 1.0e-4
DEVICE_LEN_CM, XJ_1D_CM, FAR_H_CM = 1.0e-5, 0.5e-5, 1.0e-7
BASE_NEAR_H_CM = 8.0e-9


def near_h(level):
    return BASE_NEAR_H_CM / (2 ** level)


# ------------------------------------------------------------------------------------------------ mesh construction (public API)
def build_1d_device(level, device_name):
    h = near_h(level)
    devsim.create_1d_mesh(mesh="m")
    devsim.add_1d_mesh_line(mesh="m", pos=0.0, ps=FAR_H_CM, tag="top")
    devsim.add_1d_mesh_line(mesh="m", pos=XJ_1D_CM, ps=h, tag="mid")
    devsim.add_1d_mesh_line(mesh="m", pos=DEVICE_LEN_CM, ps=FAR_H_CM, tag="bot")
    devsim.add_1d_contact(mesh="m", name="top", tag="top", material="metal")
    devsim.add_1d_contact(mesh="m", name="bot", tag="bot", material="metal")
    devsim.add_1d_region(mesh="m", material="Si", region="reg", tag1="top", tag2="bot")
    devsim.finalize_mesh(mesh="m")
    devsim.create_device(mesh="m", device=device_name)
    return "reg", "m"


def build_2d_device(level, device_name, mesh_name, tmp):
    from tcad.backends.viennaps import session as vsession
    from tcad.backends.viennaps.io import save_volume_mesh
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.device.devsim.mesh_import import import_process_result

    domain = vsession.make_mask_spans(
        grid_delta_um=RECIPE_2D["grid_delta_um"], x_extent_um=RECIPE_2D["x_extent_um"], y_extent_um=RECIPE_2D["y_extent_um"],
        spans_um=[], mask_height_um=0.1, substrate_depth_um=RECIPE_2D["silicon_depth_um"] + 1.0,
    )
    mesh_path = save_volume_mesh(domain, os.path.join(tmp, "virgin_wafer"), floor_depth_um=RECIPE_2D["silicon_depth_um"])
    process_result = build_process_result({"final_mesh": mesh_path, "snapshots": []})
    imported = import_process_result(
        process_result, mesh_name=mesh_name, device_name=device_name,
        contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE,
        refine_near_um=XJ_2D_UM, refine_axis="x", refine_levels=level + 1,
    )
    return "Si", imported.mesh, imported.contacts


# ------------------------------------------------------------------------------------------------ real-node junction placement (fixes P0-1)
def locate_junction(x_native, intended_x):
    """x0 = the REAL node closest to `intended_x` (must land on it, not just near it); x1 = the nearest node
    STRICTLY to the right of x0 (the shift direction is fixed at "positive side" for the whole matrix, per
    instructions). Returns (x0, x1). Raises AssertionError -- fails the case, never silently continues -- if
    x0 is not actually at the intended coordinate, or if no node exists strictly to the right of x0. The
    tolerance (1e-6 relative to the device length, ~1e-11 cm here) is far tighter than the coarsest refinement
    level tested (>=8e-9 cm) and far looser than float32 mesh round-trip noise this project has already
    measured (~1e-8 relative) -- grounded in scale, not an arbitrary large number."""
    x0 = min(x_native, key=lambda v: abs(v - intended_x))
    tol = 1e-6 * max(abs(intended_x), 1e-5)
    assert abs(x0 - intended_x) < tol, (
        f"no real mesh node sits at the intended junction {intended_x}: nearest is {x0} (|diff|={abs(x0 - intended_x):.3e}, tol={tol:.3e})")
    righties = sorted(v for v in set(x_native) if v > x0)
    assert righties, f"no mesh node exists strictly to the right of x0={x0}"
    return x0, righties[0]


def set_doping(device, region, representation, xj_cm):
    if representation == "R1":
        acc_eq = f"{NA:.10e}*step(({xj_cm:.10e})-x)"
    elif representation == "R2":
        acc_eq = f"{NA:.10e}*(1-step(x-({xj_cm:.10e})))"
    else:
        raise ValueError(representation)
    devsim.node_model(device=device, region=region, name="Donors", equation=f"{ND:.10e}*step(x-({xj_cm:.10e}))")
    devsim.node_model(device=device, region=region, name="Acceptors", equation=acc_eq)
    devsim.node_model(device=device, region=region, name="NetDoping", equation="Donors-Acceptors")


def doping_at(device, region, x_native, x_target):
    """Exact node index at x_target (must be an existing node -- x0 always is, by construction)."""
    idx = min(range(len(x_native)), key=lambda i: abs(x_native[i] - x_target))
    assert abs(x_native[idx] - x_target) < 1e-9 * max(abs(x_target), 1e-9), f"x_target {x_target} is not an existing node"
    d = devsim.get_node_model_values(device=device, region=region, name="Donors")
    a = devsim.get_node_model_values(device=device, region=region, name="Acceptors")
    return d[idx], a[idx]


# ------------------------------------------------------------------------------------------------ solve (fixes P1)
def _solve(**kw):
    """Public devsim.solve() returns no iteration count -- never invented, never scraped from stdout, never
    read from a private symbol. On success: converged=True, actual_iterations=None,
    actual_iterations_status=UNAVAILABLE_FROM_PUBLIC_API, iteration_limit=the requested cap. On failure: the
    public exception message and the same iteration_limit."""
    limit = kw.get("maximum_iterations")
    try:
        devsim.solve(type="dc", **kw)
        return {"converged": True, "iteration_limit": limit, "actual_iterations": None,
                "actual_iterations_status": "UNAVAILABLE_FROM_PUBLIC_API", "error": None}
    except Exception as exc:  # noqa: BLE001 -- probe: record the failure, never fabricate a converged result
        return {"converged": False, "iteration_limit": limit, "actual_iterations": None,
                "actual_iterations_status": "UNAVAILABLE_FROM_PUBLIC_API", "error": str(exc)}


def vt_q_eps_ni(device, region):
    return (devsim.get_parameter(device=device, region=region, name="V_t"),
            devsim.get_parameter(device=device, region=region, name="ElectronCharge"),
            devsim.get_parameter(device=device, region=region, name="Permittivity"),
            devsim.get_parameter(device=device, region=region, name="n_i"))


def equilibrium(device, region, contacts, relative_error, maximum_iterations, taun=1e-8, taup=1e-8):
    SetSiliconParameters(device, region, 300)
    devsim.set_parameter(device=device, region=region, name="taun", value=taun)
    devsim.set_parameter(device=device, region=region, name="taup", value=taup)
    CreateSolution(device, region, "Potential")
    CreateSiliconPotentialOnly(device, region)
    for c in contacts:
        devsim.set_parameter(device=device, name=GetContactBiasName(c), value=0.0)
        CreateSiliconPotentialOnlyContact(device, region, c)
    stage1 = _solve(absolute_error=1.0, relative_error=relative_error, maximum_iterations=maximum_iterations)
    CreateSolution(device, region, "Electrons")
    CreateSolution(device, region, "Holes")
    devsim.set_node_values(device=device, region=region, name="Electrons", init_from="IntrinsicElectrons")
    devsim.set_node_values(device=device, region=region, name="Holes", init_from="IntrinsicHoles")
    CreateSiliconDriftDiffusion(device, region)
    for c in contacts:
        CreateSiliconDriftDiffusionAtContact(device, region, c)
    stage2 = _solve(absolute_error=1e10, relative_error=relative_error, maximum_iterations=maximum_iterations)
    return (stage1["converged"] and stage2["converged"]), {"stage1_potential_only": stage1, "stage2_drift_diffusion": stage2}


def currents(device, contacts):
    return {c: devsim.get_contact_current(device=device, contact=c, equation=ece_name)
            + devsim.get_contact_current(device=device, contact=c, equation=hce_name) for c in contacts}


def depletion_recovery(x, majority, background, xj_cm, side):
    """Distance from xj (along `side`, "+" or "-") to the nearest-to-xj point where `majority` first reaches
    `frac` of the LOCAL `background` concentration, for frac in (0.5, 0.9, 0.99) -- Codex's own three recovery
    fractions, none singled out as "the" answer."""
    pts = sorted(((xv, m, b) for xv, m, b in zip(x, majority, background)
                 if (xv > xj_cm if side == "+" else xv < xj_cm)), key=lambda t: abs(t[0] - xj_cm))
    out = {}
    for frac in (0.5, 0.9, 0.99):
        hit = next((abs(xv - xj_cm) for xv, m, b in pts if b > 0 and m >= frac * b), None)
        out[f"recovery_{int(frac * 100)}pct_cm"] = hit
    return out


def dump_nodes(device, region, path, extra=None):
    x = devsim.get_node_model_values(device=device, region=region, name="x")
    rows = {"x_cm": x}
    for name in ("Donors", "Acceptors", "NetDoping", "Potential", "Electrons", "Holes"):
        try:
            rows[name] = devsim.get_node_model_values(device=device, region=region, name=name)
        except Exception:
            rows[name] = None
    if extra:
        rows.update(extra)
    with open(path, "w", encoding="utf-8") as f:
        f.write(",".join(rows.keys()) + "\n")
        for i in range(len(x)):
            f.write(",".join(str(rows[k][i]) if rows[k] is not None else "" for k in rows) + "\n")


def run(geometry, level, representation, shifted, relative_error, maximum_iterations, label):
    tmp_ctx = tempfile.TemporaryDirectory()
    device_name, mesh_name = f"d_{label}", f"m_{label}"
    try:
        if geometry == "1d":
            region, mesh_name = build_1d_device(level, device_name)
            contacts = list(devsim.get_contact_list(device=device_name))
            intended_x, bias_list, sweep_contact_pick = XJ_1D_CM, BIAS_1D, "single"
        else:
            region, mesh_name, contacts = build_2d_device(level, device_name, mesh_name, tmp_ctx.name)
            intended_x, bias_list, sweep_contact_pick = XJ_2D_UM * LENGTH_SCALE, BIAS_2D, "minmax"

        x_native = devsim.get_node_model_values(device=device_name, region=region, name="x")
        x0, x1 = locate_junction(x_native, intended_x)
        local_spacing = x1 - x0
        xj_shifted = (x0 + x1) / 2.0
        xj_used = xj_shifted if shifted else x0

        # ---- P0-1 preflight: the shift is real, exact, and off-node -----------------------------------------------
        if shifted:
            assert xj_used != x0, "shifted xj equals the aligned xj (shift computation collapsed)"
            assert abs(xj_used - x0) > 0, "shifted displacement is zero"
            assert abs((xj_used - x0) - local_spacing / 2.0) < 1e-9 * local_spacing, (
                f"shifted displacement {xj_used - x0} is not exactly local_spacing/2 ({local_spacing / 2.0})")
            junction_on_a_node = any(abs(xv - xj_used) < 1e-9 * local_spacing for xv in x_native)
            assert junction_on_a_node is False, f"shifted xj={xj_used} unexpectedly coincides with a real mesh node"
        else:
            junction_on_a_node = any(abs(xv - x0) < 1e-9 * local_spacing for xv in x_native)
            assert junction_on_a_node is True, f"aligned xj={x0} is not actually a real mesh node"

        set_doping(device_name, region, representation, xj_used)
        d0_at_x0, a0_at_x0 = doping_at(device_name, region, x_native, x0)   # sampled at the SAME reference point x0
        # -- for reporting/cross-case comparison (the P0-1 "doping arrays differ" assertion is enforced by the
        #    dispatcher comparing this field across the aligned/shifted pair of a run -- see check_matrix_completeness.py)

        ok, solve_detail = equilibrium(device_name, region, contacts, relative_error, maximum_iterations)
        v_t, q, eps, n_i = vt_q_eps_ni(device_name, region)
        v_bi_analytic = v_t * math.log(NA * ND / (n_i * n_i))
        w_analytic = math.sqrt((2.0 * eps / q) * v_bi_analytic * (1.0 / NA + 1.0 / ND)) if ok else None
        e_max_analytic = (2.0 * v_bi_analytic / w_analytic) if (ok and w_analytic) else None

        result = {
            "label": label, "geometry": geometry, "level": level, "representation": representation, "shifted": shifted,
            "n_nodes": len(x_native), "x0_aligned_cm": x0, "x1_neighbor_cm": x1, "local_spacing_cm": local_spacing,
            "xj_used_cm": xj_used, "junction_on_a_node": junction_on_a_node,
            "donors_at_x0": d0_at_x0, "acceptors_at_x0": a0_at_x0,
            "equilibrium_converged": ok, "solve_detail": solve_detail,
            "V_t": v_t, "ElectronCharge": q, "Permittivity": eps, "n_i": n_i,
            "V_bi_analytic": v_bi_analytic, "W_analytic_cm": w_analytic, "E_max_analytic_Vpercm": e_max_analytic,
            "contact_potential_span": None, "contact_boundary_consistency_error": None,
            "peak_field_solved_Vpercm": None, "depletion_recovery_donor_side": None, "depletion_recovery_acceptor_side": None,
            "bias_points": [], "contacts": contacts,
        }
        if ok:
            pot = devsim.get_node_model_values(device=device_name, region=region, name="Potential")
            result["contact_potential_span"] = max(pot) - min(pot)
            result["contact_boundary_consistency_error"] = abs(result["contact_potential_span"] - v_bi_analytic)

            efield = devsim.get_edge_model_values(device=device_name, region=region, name="ElectricField")
            result["peak_field_solved_Vpercm"] = max(abs(v) for v in efield) if efield else None

            electrons = devsim.get_node_model_values(device=device_name, region=region, name="Electrons")
            holes = devsim.get_node_model_values(device=device_name, region=region, name="Holes")
            donors = devsim.get_node_model_values(device=device_name, region=region, name="Donors")
            acceptors = devsim.get_node_model_values(device=device_name, region=region, name="Acceptors")
            result["depletion_recovery_donor_side"] = depletion_recovery(x_native, electrons, donors, xj_used, "+")
            result["depletion_recovery_acceptor_side"] = depletion_recovery(x_native, holes, acceptors, xj_used, "-")
            space_charge = [h - e + dn - ac for h, e, dn, ac in zip(holes, electrons, donors, acceptors)]

            dump_nodes(device_name, region, os.path.join(DATA, f"{label}_equilibrium.csv"), extra={"space_charge_rho_over_q": space_charge})

            if geometry == "1d":
                for v in bias_list:
                    devsim.set_parameter(device=device_name, name=GetContactBiasName("top"), value=v)
                    step = _solve(absolute_error=1e10, relative_error=relative_error, maximum_iterations=maximum_iterations)
                    cur = currents(device_name, contacts) if step["converged"] else None
                    result["bias_points"].append({"v_bias": v, **step, "currents": cur,
                                                  "conservation_error": (abs(sum(cur.values())) if cur else None)})
                    if not step["converged"]:
                        break
            else:
                p_contact, n_contact = min(contacts), max(contacts)
                for v in bias_list:
                    devsim.set_parameter(device=device_name, name=GetContactBiasName(n_contact), value=v)
                    devsim.set_parameter(device=device_name, name=GetContactBiasName(p_contact), value=0.0)
                    sweep_rel = max(relative_error, 1e-6)
                    step = _solve(absolute_error=1e10, relative_error=sweep_rel, maximum_iterations=100)
                    cur = currents(device_name, contacts) if step["converged"] else None
                    result["bias_points"].append({"v_bias": v, **step, "currents": cur,
                                                  "conservation_error": (abs(sum(cur.values())) if cur else None)})
                    if not step["converged"]:
                        break
        return result
    finally:
        try:
            devsim.delete_device(device=device_name)
        except Exception:
            pass
        try:
            devsim.delete_mesh(mesh=mesh_name)
        except Exception:
            pass
        tmp_ctx.cleanup()


if __name__ == "__main__":
    geometry, level, representation, shifted_i, rel_err, max_it, label = sys.argv[1:8]
    level, shifted, rel_err, max_it = int(level), bool(int(shifted_i)), float(rel_err), int(max_it)
    r = run(geometry, level, representation, shifted, rel_err, max_it, label)
    print("===RESULT_JSON===")
    print(json.dumps(r, default=str))
