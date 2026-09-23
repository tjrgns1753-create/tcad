"""Batch 7H-D shared DEVSIM helpers (public API only). The semiconductor
equations are registered by the UNMODIFIED production functions
tcad.device.devsim.semiconductor_equation.setup_semiconductor_potential_equation
and setup_drift_diffusion_equation (which call the public simple_physics
helpers). Geometry overrides use only set_parameter + edge_solution /
node_solution / element_model (7H-C capability spike)."""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
DATA = os.path.join(HERE, "..", "data")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-23-batch7h-b-nodevolume-mechanism", "scripts"))
import formulas as fm  # noqa: E402  (7H-B, read-only)

FIX = json.load(open(os.path.join(DATA, "fixed_physics.json"), encoding="utf-8"))
SPEC, REF = FIX["spec"], FIX["analytic_reference"]
NA, ND = SPEC["doping"]["NA_cm3"], SPEC["doping"]["ND_cm3"]
VT, NI = REF["V_T_V"], REF["n_i_cm3"]
UM = 1e-4
REGION = "Si"
ECE, HCE, PE = "ElectronContinuityEquation", "HoleContinuityEquation", "PotentialEquation"


def netdoping(x_cm):
    return [ND if x > 0 else (-NA if x < 0 else 0.0) for x in x_cm]


def build_2d(dv, P_um, tris, dev="d"):
    P = np.asarray(P_um, dtype=float)
    coords = []
    for x, y in P:
        coords += [float(x) * UM, float(y) * UM, 0.0]
    own = {}
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            own[(min(a, b), max(a, b))] = own.get((min(a, b), max(a, b)), 0) + 1
    bnd = [e for e, n in own.items() if n == 1]
    xmin, xmax = P[:, 0].min(), P[:, 0].max()
    left = [e for e in bnd if P[e[0], 0] == xmin and P[e[1], 0] == xmin]
    right = [e for e in bnd if P[e[0], 0] == xmax and P[e[1], 0] == xmax]
    el = []
    for t in tris:
        el += [2, 0, int(t[0]), int(t[1]), int(t[2])]
    for k, edges in ((1, left), (2, right)):
        for a, b in edges:
            el += [1, k, int(a), int(b)]
    dv.create_gmsh_mesh(mesh="m_" + dev, coordinates=coords, elements=el, physical_names=[REGION, "left", "right"])
    dv.add_gmsh_region(gmsh_name=REGION, mesh="m_" + dev, region=REGION, material="Si")
    for c in ("left", "right"):
        dv.add_gmsh_contact(gmsh_name=c, mesh="m_" + dev, name=c, material="metal", region=REGION)
    dv.finalize_mesh(mesh="m_" + dev)
    dv.create_device(mesh="m_" + dev, device=dev)
    return {"left_nodes": sorted({v for e in left for v in e}), "right_nodes": sorted({v for e in right for v in e})}


def build_1d(dv, dx_um, x_range_um=(-0.5, 0.5), dev="d"):
    m = "m_" + dev
    dv.create_1d_mesh(mesh=m)
    dv.add_1d_mesh_line(mesh=m, pos=x_range_um[0] * UM, ps=dx_um * UM, tag="L")
    dv.add_1d_mesh_line(mesh=m, pos=0.0, ps=dx_um * UM)
    dv.add_1d_mesh_line(mesh=m, pos=x_range_um[1] * UM, ps=dx_um * UM, tag="R")
    dv.add_1d_contact(mesh=m, name="left", tag="L", material="metal")
    dv.add_1d_contact(mesh=m, name="right", tag="R", material="metal")
    dv.add_1d_region(mesh=m, material="Si", region=REGION, tag1="L", tag2="R")
    dv.finalize_mesh(mesh=m)
    dv.create_device(mesh=m, device=dev)


def set_doping(dv, dev="d"):
    x = dv.get_node_model_values(device=dev, region=REGION, name="x")
    dv.node_model(device=dev, region=REGION, name="NetDoping", equation="0")
    dv.set_node_values(device=dev, region=REGION, name="NetDoping", values=netdoping(x))


def signed_geometry(dv, dev="d"):
    x = np.array(dv.get_node_model_values(device=dev, region=REGION, name="x"))
    y = np.array(dv.get_node_model_values(device=dev, region=REGION, name="y"))
    tris = [list(t) for t in dv.get_element_node_list(device=dev, region=REGION)]
    P = np.column_stack([x, y])
    g1, _, _ = fm.edge_couple_predictions(P, tris)
    dv.edge_from_node_model(device=dev, region=REGION, node_model="node_index")
    n0 = np.array(dv.get_edge_model_values(device=dev, region=REGION, name="node_index@n0")).astype(int)
    n1 = np.array(dv.get_edge_model_values(device=dev, region=REGION, name="node_index@n1")).astype(int)
    couple = [g1[(min(a, b), max(a, b))] for a, b in zip(n0, n1)]
    vol = fm.node_areas(P, tris, "F2")
    return couple, vol.tolist()


EL_COUPLE = ("0.5*pow((x@en0-x@en1)^2+(y@en0-y@en1)^2,0.5)*((x@en0-x@en2)*(x@en1-x@en2)+(y@en0-y@en2)*(y@en1-y@en2))"
             "/pow(((x@en0-x@en2)*(y@en1-y@en2)-(y@en0-y@en2)*(x@en1-x@en2))^2,0.5)")


def apply_variant(dv, variant, dev="d"):
    """D0 default; D1 consistent signed (couple + volumes, edge/element);
    D2 edge/element couple only; D3 node/edge-node/element-node volume only.
    Negative values are kept as computed -- never clamped."""
    info = {"variant": variant}
    if variant == "D0":
        return info
    couple, vol = signed_geometry(dv, dev)
    info.update({"n_negative_signed_edge_couple": int(sum(1 for c in couple if c < 0)),
                 "min_signed_edge_couple_cm": float(min(couple)),
                 "n_negative_signed_node_volume": int(sum(1 for v in vol if v < 0)),
                 "min_signed_node_volume_cm2": float(min(vol))})
    for nm in ("x", "y"):
        dv.element_from_node_model(device=dev, region=REGION, node_model=nm)
    flux = variant in ("D1", "D2")
    volume = variant in ("D1", "D3")
    params = []
    if flux:
        dv.edge_solution(device=dev, region=REGION, name="OvEdgeCouple")
        dv.set_edge_values(device=dev, region=REGION, name="OvEdgeCouple", values=couple)
        dv.element_model(device=dev, region=REGION, name="OvElementEdgeCouple", equation=EL_COUPLE)
        params += [("edge_couple_model", "OvEdgeCouple"), ("element_edge_couple_model", "OvElementEdgeCouple")]
    if volume:
        dv.node_solution(device=dev, region=REGION, name="OvNodeVolume")
        dv.set_node_values(device=dev, region=REGION, name="OvNodeVolume", values=vol)
        cpl = "OvEdgeCouple" if flux else "OvEdgeCoupleForVolume"
        if not flux:
            dv.edge_solution(device=dev, region=REGION, name="OvEdgeCoupleForVolume")
            dv.set_edge_values(device=dev, region=REGION, name="OvEdgeCoupleForVolume", values=couple)
            dv.element_model(device=dev, region=REGION, name="OvElementEdgeCoupleForVolume", equation=EL_COUPLE)
        dv.edge_model(device=dev, region=REGION, name="OvEdgeNodeVolume", equation=f"0.25*{cpl}*EdgeLength")
        ecpl = "OvElementEdgeCouple" if flux else "OvElementEdgeCoupleForVolume"
        dv.element_model(device=dev, region=REGION, name="OvElementNodeVolume",
                         equation=f"0.25*{ecpl}*pow((x@en0-x@en1)^2+(y@en0-y@en1)^2,0.5)")
        params += [("node_volume_model", "OvNodeVolume"), ("edge_node0_volume_model", "OvEdgeNodeVolume"),
                   ("edge_node1_volume_model", "OvEdgeNodeVolume"), ("element_node0_volume_model", "OvElementNodeVolume"),
                   ("element_node1_volume_model", "OvElementNodeVolume")]
    for pn, v in params:
        dv.set_parameter(name=pn, value=v)
    info["parameters"] = {pn: dv.get_parameter(name=pn) for pn, _ in params}
    return info


def solve(dv, kind, tag):
    s = dict(SPEC["solver"]["poisson" if kind == "poisson" else "drift_diffusion"])
    s["relative_error"] = 1e-6  # DEVIATIONS.md item 1 (registered 1e-10; psi = 0 at the symmetric x = 0 node)
    print(f"### SOLVE-BEGIN {tag}", flush=True)
    try:
        dv.solve(type="dc", absolute_error=s["absolute_error"], relative_error=s["relative_error"],
                 maximum_iterations=s["maximum_iterations"])
        ok, err = True, None
    except Exception as e:  # convergence failure is a result, never retried with other settings
        ok, err = False, repr(e)[:300]
    print(f"### SOLVE-END {tag} ok={ok}", flush=True)
    return ok, err


def state(dv, dev="d", with_carriers=True):
    g = lambda n: np.array(dv.get_node_model_values(device=dev, region=REGION, name=n))  # noqa: E731
    s = {"x": g("x"), "y": g("y"), "psi": g("Potential"), "C": g("NetDoping"), "V": g("NodeVolume")}
    if with_carriers:
        s["n"], s["p"] = g("Electrons"), g("Holes")
    return s


def currents(dv, eqs=(ECE, HCE), dev="d"):
    out = {}
    for c in ("left", "right"):
        out[c] = {e: float(dv.get_contact_current(device=dev, contact=c, equation=e)) for e in eqs}
        out[c]["total"] = sum(out[c][e] for e in eqs)
    return out


def matrix_blocks(dv, dev="d", eqs=(PE,), contact_nodes=()):
    m = dv.get_matrix_and_rhs(format="csr")["static"]
    ap, ai, av = np.array(m["ap"]), np.array(m["ai"]), np.array(m["av"])
    out = {}
    for e in eqs:
        rows = np.array(dv.get_equation_numbers(device=dev, region=REGION, equation=e))
        col_of = {int(r): k for k, r in enumerate(rows)}   # same numbering is the variable's column
        pos, neg, zero, diag_dom_fail = [], 0, 0, 0
        for k, r in enumerate(rows):
            if k in contact_nodes:
                continue
            offsum, diag = 0.0, 0.0
            for q in range(ap[r], ap[r + 1]):
                c = ai[q]
                if c == r:
                    diag = av[q]
                elif int(c) in col_of:
                    v = av[q]
                    offsum += abs(v)
                    if v > 0:
                        pos.append((k, col_of[int(c)], float(v)))
                    elif v < 0:
                        neg += 1
                    else:
                        zero += 1
            if abs(diag) < offsum * (1 - 1e-12):
                diag_dom_fail += 1
        out[e] = {"n_offdiag_positive": len(pos), "n_offdiag_negative": neg, "n_offdiag_zero": zero,
                  "n_rows_not_weakly_diag_dominant": diag_dom_fail, "positive_entries": pos[:200]}
    return out


def qf(s):
    phin = s["psi"] - VT * np.log(s["n"] / NI)
    phip = s["psi"] + VT * np.log(s["p"] / NI)
    return phin, phip
