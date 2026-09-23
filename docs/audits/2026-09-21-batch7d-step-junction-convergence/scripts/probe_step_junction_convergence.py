"""Batch 7D capability audit -- PUBLIC DEVSIM API ONLY. Never touches DEVSIM internals, never patches production.

Compares three doping REPRESENTATIONS (all built with `devsim.node_model()` equation strings, DEVSIM's own public symbolic
engine -- same call CreateNodeModel/SetNetDoping use in devsim/examples/diode/diode_common.py):

  R1 official   Donors = Nd*step(x-xj)      Acceptors = Na*step(xj-x)        (devsim/examples/diode/diode_common.py::SetNetDoping,
                                                                               verbatim convention; both fire AT xj)
  R2 strict     Donors = Nd*step(x-xj)      Acceptors = Na*(1-step(x-xj))    (Batch 7C Rev.2's one-sided convention -- algebraically
                                                                               the complement of R1's donor term, so ONLY the donor
                                                                               fires at xj)
  R3 half-cell  same formula as R1, but xj is placed halfway between two mesh nodes instead of on one

Two independent geometries, at 4 refinement levels each (h, h/2, h/4, h/8 near the junction):
  1D  -- DEVSIM's own public 1D mesh API (create_1d_mesh/add_1d_mesh_line/...), the exact structure of
         devsim/examples/diode/diode_common.py::CreateMesh, with the "mid" segment spacing swept.
  2D  -- the project's OWN real ViennaPS-imported mesh (identical geometry every level: only the project's own
         public `import_process_result(..., refine_levels=...)` knob changes -- no ViennaPS geometry variation).

Physics setup uses ONLY devsim.python_packages.simple_physics's public helpers (SetSiliconParameters,
CreateSiliconPotentialOnly[Contact], CreateSiliconDriftDiffusion[AtContact]) -- the same ones
tcad/device/devsim/semiconductor_equation.py already wraps -- plus this project's own public
tcad.device.devsim.mesh_import.import_process_result for the 2D case. Nothing here is production code and nothing
here is imported by production; this script never calls tcad.device.devsim.doping_mapping (the canonical gate) --
Donors/Acceptors/NetDoping are written directly via the public node_model API to isolate the discretization
question from the canonical-state layer Batches 7C/7D already settled.

Outputs: docs/audits/2026-09-21-batch7d-step-junction-convergence/data/*.csv (per-node raw fields) and
matrix.json (the full measurement table this script's own stdout summarizes).
"""
import json
import math
import os
import sys
import tempfile
import warnings

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
DATA = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA, exist_ok=True)

import devsim  # noqa: E402
from devsim.python_packages.simple_physics import (  # noqa: E402
    CreateSiliconPotentialOnly, CreateSiliconPotentialOnlyContact,
    CreateSiliconDriftDiffusion, CreateSiliconDriftDiffusionAtContact,
    SetSiliconParameters, GetContactBiasName, ece_name, hce_name,
)
from devsim.python_packages.model_create import CreateSolution  # noqa: E402

REGION, DEVICE_1D = "reg", "dev1d"
ND, NA = 1.0e18, 1.0e18            # matches diode_common.py::SetNetDoping magnitude AND the project's own step-junction fixture
DEVICE_LEN_CM = 1.0e-5             # matches diode_common.py::CreateMesh exactly (0 .. 1e-5 cm)
XJ_CM = 0.5e-5                     # matches diode_common.py's own "mid" tag position exactly
FAR_H_CM = 1.0e-7                  # matches diode_common.py's own top/bot spacing exactly
LEVELS = [0, 1, 2, 3]              # h, h/2, h/4, h/8
BASE_NEAR_H_CM = 8.0e-9            # coarsest near-junction spacing tested (level 0); halved at each further level
BIAS_1D = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]   # devsim's own diode_1d.py ramp exactly


def near_h(level):
    return BASE_NEAR_H_CM / (2 ** level)


# ---------------------------------------------------------------------------------------------------------- 1D mesh (public API)
def build_1d_device(level, shifted):
    """DEVSIM's own public 1D mesh API, structured exactly like diode_common.py::CreateMesh -- only the
    'mid' segment's own point spacing (near the junction) is varied by refinement level."""
    h = near_h(level)
    xj = XJ_CM + (h / 2.0 if shifted else 0.0)
    devsim.create_1d_mesh(mesh="m")
    devsim.add_1d_mesh_line(mesh="m", pos=0.0, ps=FAR_H_CM, tag="top")
    devsim.add_1d_mesh_line(mesh="m", pos=XJ_CM, ps=h, tag="mid")
    devsim.add_1d_mesh_line(mesh="m", pos=DEVICE_LEN_CM, ps=FAR_H_CM, tag="bot")
    devsim.add_1d_contact(mesh="m", name="top", tag="top", material="metal")
    devsim.add_1d_contact(mesh="m", name="bot", tag="bot", material="metal")
    devsim.add_1d_region(mesh="m", material="Si", region=REGION, tag1="top", tag2="bot")
    devsim.finalize_mesh(mesh="m")
    devsim.create_device(mesh="m", device=DEVICE_1D)
    return DEVICE_1D, xj


# ---------------------------------------------------------------------------------------------------------- doping (public node_model API)
def set_doping(device, region, representation, xj_cm):
    """Donors/Acceptors/NetDoping via devsim.node_model() -- DEVSIM's own public symbolic engine, the identical
    call CreateNodeModel()/SetNetDoping() use. R1 is diode_common.py's own formula verbatim; R2 is the algebraic
    complement (Rev.2's convention); R3 reuses R1's formula with xj_cm chosen off-node by the caller."""
    if representation in ("R1", "R3"):
        acc_eq = f"{NA:.10e}*step(({xj_cm:.10e})-x)"
    elif representation == "R2":
        acc_eq = f"{NA:.10e}*(1-step(x-({xj_cm:.10e})))"
    else:
        raise ValueError(representation)
    donor_eq = f"{ND:.10e}*step(x-({xj_cm:.10e}))"
    # `node_model()` is DEVSIM's own public symbolic-model API (the identical call
    # CreateNodeModel()/SetNetDoping() use); called once per fresh device here, so no
    # redefinition is needed.
    devsim.node_model(device=device, region=region, name="Donors", equation=donor_eq)
    devsim.node_model(device=device, region=region, name="Acceptors", equation=acc_eq)
    devsim.node_model(device=device, region=region, name="NetDoping", equation="Donors-Acceptors")


def vt_ni(device, region):
    return devsim.get_parameter(device=device, region=region, name="V_t"), devsim.get_parameter(device=device, region=region, name="n_i")


def equilibrium(device, region, contacts, taun=1e-8, taup=1e-8, relative_error=1e-10, maximum_iterations=30):
    """Same call sequence as diode_common.py::InitialSolution + DriftDiffusionInitialSolution -- public
    simple_physics helpers only. Default tolerance copied verbatim from diode_1d.py / diode_common.py
    (the correct reference for the 1D case); the 2D Trial B run below instead passes this project's own
    PRE-EXISTING, already-shipped tolerance from tcad/characterization/pn_junction_iv_sweep.py
    (relative_error=1e-6, maximum_iterations=100) -- not chosen after seeing these results: that file's own
    docstring already documents (independently of this audit) that 1e-10/30 fails to converge on a real
    unstructured 2D ViennaPS-derived mesh and 1e-6/100 was verified necessary."""
    SetSiliconParameters(device, region, 300)
    devsim.set_parameter(device=device, region=region, name="taun", value=taun)
    devsim.set_parameter(device=device, region=region, name="taup", value=taup)
    CreateSolution(device, region, "Potential")
    CreateSiliconPotentialOnly(device, region)
    for c in contacts:
        devsim.set_parameter(device=device, name=GetContactBiasName(c), value=0.0)
        CreateSiliconPotentialOnlyContact(device, region, c)
    ok1, it1 = _solve(absolute_error=1.0, relative_error=relative_error, maximum_iterations=maximum_iterations)
    CreateSolution(device, region, "Electrons")
    CreateSolution(device, region, "Holes")
    devsim.set_node_values(device=device, region=region, name="Electrons", init_from="IntrinsicElectrons")
    devsim.set_node_values(device=device, region=region, name="Holes", init_from="IntrinsicHoles")
    CreateSiliconDriftDiffusion(device, region)
    for c in contacts:
        CreateSiliconDriftDiffusionAtContact(device, region, c)
    ok2, it2 = _solve(absolute_error=1e10, relative_error=relative_error, maximum_iterations=maximum_iterations)
    # `it1`/`it2` are the requested maximum_iterations on success, or an error STRING on failure (see `_solve`) --
    # never add them; report the pair so a partial failure (stage 1 ok, stage 2 not, or vice versa) is visible.
    return ok1 and ok2, (it1, it2)


def _solve(**kw):
    try:
        devsim.solve(type="dc", **kw)
        return True, kw.get("maximum_iterations")
    except Exception as exc:  # noqa: BLE001 -- probe: record the failure, never fabricate a converged result
        return False, str(exc)


def currents(device, contacts):
    out = {}
    for c in contacts:
        e = devsim.get_contact_current(device=device, contact=c, equation=ece_name)
        h = devsim.get_contact_current(device=device, contact=c, equation=hce_name)
        out[c] = e + h
    return out


def dump_nodes(device, region, path):
    x = devsim.get_node_model_values(device=device, region=region, name="x")
    rows = {"x_cm": x}
    for name in ("Donors", "Acceptors", "NetDoping", "Potential", "Electrons", "Holes"):
        try:
            rows[name] = devsim.get_node_model_values(device=device, region=region, name=name)
        except Exception:
            rows[name] = None
    with open(path, "w", encoding="utf-8") as f:
        f.write(",".join(rows.keys()) + "\n")
        for i in range(len(x)):
            f.write(",".join(str(rows[k][i]) if rows[k] is not None else "" for k in rows) + "\n")


def teardown(device):
    try:
        devsim.delete_device(device=device)
    except Exception:
        pass
    try:
        devsim.delete_mesh(mesh="m")
    except Exception:
        pass


def run_case_1d(level, representation, shifted, label):
    device, xj = build_1d_device(level, shifted)
    contacts = list(devsim.get_contact_list(device=device))
    set_doping(device, REGION, representation, xj)
    x = devsim.get_node_model_values(device=device, region=REGION, name="x")
    d0 = devsim.get_node_model_values(device=device, region=REGION, name="Donors")
    a0 = devsim.get_node_model_values(device=device, region=REGION, name="Acceptors")
    near_idx = sorted(range(len(x)), key=lambda i: abs(x[i] - xj))[:2]
    ok, it = equilibrium(device, REGION, contacts)
    v_t, n_i = vt_ni(device, REGION)
    v_bi_analytic = v_t * math.log(NA * ND / (n_i * n_i)) if ok else None
    pot = devsim.get_node_model_values(device=device, region=REGION, name="Potential") if ok else []
    v_bi_solved = (max(pot) - min(pot)) if ok else None
    result = {
        "label": label, "level": level, "near_h_cm": near_h(level), "representation": representation, "shifted": shifted,
        "n_nodes": len(x), "xj_used_cm": xj, "junction_on_a_node": any(abs(xi - xj) < 1e-16 for xi in x),
        "min_spacing_near_junction_cm": min(abs(x[i] - x[j]) for i in near_idx for j in near_idx if i != j) if len(near_idx) > 1 else None,
        "junction_node_donors_acceptors": [(round(x[i], 12), d0[i], a0[i]) for i in near_idx],
        "equilibrium_converged": ok, "equilibrium_iterations": it,
        "V_t": v_t, "n_i": n_i, "V_bi_analytic": v_bi_analytic, "V_bi_solved": v_bi_solved,
        "V_bi_error": (abs(v_bi_solved - v_bi_analytic) if ok else None),
        "bias_points": [], "contacts": contacts,
    }
    if ok:
        dump_nodes(device, REGION, os.path.join(DATA, f"{label}_equilibrium.csv"))
        for v in BIAS_1D:
            devsim.set_parameter(device=device, name=GetContactBiasName("top"), value=v)
            step_ok, step_it = _solve(absolute_error=1e10, relative_error=1e-10, maximum_iterations=30)
            cur = currents(device, contacts) if step_ok else None
            result["bias_points"].append({"v_top": v, "converged": step_ok, "iterations": step_it, "currents": cur,
                                          "conservation_error": (abs(sum(cur.values())) if cur else None)})
            if not step_ok:
                break
    teardown(device)
    return result


# ---------------------------------------------------------------------------------------------------------- 2D (project's own real mesh)
RECIPE_2D = {"grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0, "silicon_depth_um": 2.0}
BIAS_2D = [-0.3, 0.0, 0.3, 0.4]      # exactly tests/integration/test_wafer_state_v2_initial_geometry_devsim_real.py::scenario_step_junction
DONOR_2D, ACCEPTOR_2D, XJ_2D_UM = 1.0e18, 1.0e18, 0.0   # exact same fixture values
LENGTH_SCALE = 1.0e-4                # um -> cm, the project's own convention


def build_2d_mesh_once(tmp):
    from tcad.backends.viennaps import session as vsession
    from tcad.backends.viennaps.io import save_volume_mesh
    from tcad.mesh.viennaps_adapter import build_process_result
    domain = vsession.make_mask_spans(
        grid_delta_um=RECIPE_2D["grid_delta_um"], x_extent_um=RECIPE_2D["x_extent_um"], y_extent_um=RECIPE_2D["y_extent_um"],
        spans_um=[], mask_height_um=0.1, substrate_depth_um=RECIPE_2D["silicon_depth_um"] + 1.0,
    )
    mesh_path = save_volume_mesh(domain, os.path.join(tmp, "virgin_wafer"), floor_depth_um=RECIPE_2D["silicon_depth_um"])
    return build_process_result({"final_mesh": mesh_path, "snapshots": []})


def run_case_2d(process_result, level, representation, shifted, label, relative_error=1e-10, maximum_iterations=30):
    from tcad.device.devsim.mesh_import import import_process_result

    refine_levels = level + 1     # 1..4 subdivision passes near the junction -> the "h, h/2, h/4, h/8" progression
    imported = import_process_result(
        process_result, mesh_name=f"m2d_{label}", device_name=f"d2d_{label}",
        contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE,
        refine_near_um=XJ_2D_UM, refine_axis="x", refine_levels=refine_levels,
    )
    device, contacts = imported.device, imported.contacts
    x_native = devsim.get_node_model_values(device=device, region="Si", name="x")
    xj_cm = XJ_2D_UM * LENGTH_SCALE + (0.0 if not shifted else 0.0)
    if shifted:
        # place xj exactly between the two nodes nearest x=0 along x (native/native cm coordinates)
        near_x = sorted({xv for xv in x_native}, key=abs)
        pos = sorted(v for v in near_x if v > 0)[0] if any(v > 0 for v in near_x) else 0.0
        neg = sorted((v for v in near_x if v < 0), reverse=True)[0] if any(v < 0 for v in near_x) else 0.0
        xj_cm = (pos + neg) / 2.0
    set_doping(device, "Si", representation, xj_cm)
    d0 = devsim.get_node_model_values(device=device, region="Si", name="Donors")
    a0 = devsim.get_node_model_values(device=device, region="Si", name="Acceptors")
    by_x = {}
    for i, xv in enumerate(x_native):
        by_x.setdefault(xv, i)          # first node index at each distinct x coordinate
    unique_x_by_dist = sorted(by_x, key=lambda xv: abs(xv - xj_cm))[:6]
    near_idx = [by_x[v] for v in unique_x_by_dist]
    unique_x_sorted = sorted(by_x, key=lambda xv: abs(xv - xj_cm))[:12]
    unique_x_sorted.sort()               # numeric order, so adjacent entries are spatially adjacent
    ok, it = equilibrium(device, "Si", contacts, relative_error=relative_error, maximum_iterations=maximum_iterations)
    v_t, n_i = vt_ni(device, "Si")
    v_bi_analytic = v_t * math.log(ACCEPTOR_2D * DONOR_2D / (n_i * n_i)) if ok else None
    pot = devsim.get_node_model_values(device=device, region="Si", name="Potential") if ok else []
    v_bi_solved = (max(pot) - min(pot)) if ok else None
    result = {
        "label": label, "level": level, "refine_levels_param": refine_levels, "representation": representation, "shifted": shifted,
        "n_nodes": len(x_native), "xj_used_cm": xj_cm, "junction_on_a_node": any(abs(xv - xj_cm) < 1e-16 for xv in x_native),
        "min_spacing_near_junction_cm": (min(unique_x_sorted[i] - unique_x_sorted[i - 1] for i in range(1, len(unique_x_sorted))) if len(unique_x_sorted) > 1 else None),
        "junction_node_donors_acceptors": [(round(x_native[i] / LENGTH_SCALE, 6), d0[i], a0[i]) for i in near_idx[:2]],
        "equilibrium_converged": ok, "equilibrium_iterations": it,
        "V_t": v_t, "n_i": n_i, "V_bi_analytic": v_bi_analytic, "V_bi_solved": v_bi_solved,
        "V_bi_error": (abs(v_bi_solved - v_bi_analytic) if ok else None),
        "bias_points": [], "contacts": contacts,
    }
    if ok:
        dump_nodes(device, "Si", os.path.join(DATA, f"{label}_equilibrium.csv"))
        p_contact = min(contacts)  # Si_xmin fixed at 0V; Si_xmax swept -- matches the project's own scenario_step_junction convention
        n_contact = max(contacts)
        for v in BIAS_2D:
            devsim.set_parameter(device=device, name=GetContactBiasName(n_contact), value=v)
            devsim.set_parameter(device=device, name=GetContactBiasName(p_contact), value=0.0)
            sweep_rel = max(relative_error, 1e-6)   # never tighter than the equilibrium tolerance actually used
            step_ok, step_it = _solve(absolute_error=1e10, relative_error=sweep_rel, maximum_iterations=100)
            cur = currents(device, contacts) if step_ok else None
            result["bias_points"].append({"v_n_contact": v, "converged": step_ok, "iterations": step_it, "currents": cur,
                                          "conservation_error": (abs(sum(cur.values())) if cur else None)})
            if not step_ok:
                break
    try:
        devsim.delete_device(device=device)
        devsim.delete_mesh(mesh=imported.mesh)
    except Exception:
        pass
    return result


def main():
    matrix = {"1d": [], "2d": []}
    print("=== 1D public-DEVSIM-mesh probe (devsim/examples/diode/diode_common.py::CreateMesh structure) ===")
    for level in LEVELS:
        for representation in ("R1", "R2"):
            for shifted in (False, True):
                label = f"1d_L{level}_{representation}_{'shift' if shifted else 'node'}"
                try:
                    r = run_case_1d(level, representation, shifted, label)
                except Exception as exc:  # noqa: BLE001 -- record, never fabricate
                    r = {"label": label, "level": level, "representation": representation, "shifted": shifted, "error": repr(exc)}
                matrix["1d"].append(r)
                print(f"[{label}] near_h={near_h(level):.3e}cm on_node={r.get('junction_on_a_node')} "
                      f"eq_ok={r.get('equilibrium_converged')} Vbi_analytic={r.get('V_bi_analytic')} "
                      f"Vbi_solved={r.get('V_bi_solved')} err={r.get('V_bi_error')} "
                      f"bias_pts_ok={[b['converged'] for b in r.get('bias_points', [])]}")

    print("\n=== 2D probe (project's own real ViennaPS-imported mesh; only refine_levels + doping representation vary) ===")
    with tempfile.TemporaryDirectory() as tmp:
        process_result = build_2d_mesh_once(tmp)
        for level in LEVELS:
            for representation in ("R1", "R2"):
                for shifted in (False, True):
                    label = f"2d_L{level}_{representation}_{'shift' if shifted else 'node'}"
                    try:
                        r = run_case_2d(process_result, level, representation, shifted, label)
                    except Exception as exc:  # noqa: BLE001
                        r = {"label": label, "level": level, "representation": representation, "shifted": shifted, "error": repr(exc)}
                    matrix["2d"].append(r)
                    print(f"[{label}] nodes={r.get('n_nodes')} min_h_near_j={r.get('min_spacing_near_junction_cm')} "
                          f"on_node={r.get('junction_on_a_node')} eq_ok={r.get('equilibrium_converged')} "
                          f"Vbi_analytic={r.get('V_bi_analytic')} Vbi_solved={r.get('V_bi_solved')} err={r.get('V_bi_error')} "
                          f"bias_pts_ok={[b['converged'] for b in r.get('bias_points', [])]}")

    with open(os.path.join(DATA, "matrix.json"), "w", encoding="utf-8") as f:
        json.dump(matrix, f, indent=2, default=str)
    print("\nWrote", os.path.join(DATA, "matrix.json"))


if __name__ == "__main__":
    main()
