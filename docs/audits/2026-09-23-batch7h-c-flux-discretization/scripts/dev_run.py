"""Batch 7H-C worker: ONE configuration per process (DEVSIM parameters are
global). Public DEVSIM API only. Prints ===RESULT_JSON=== then one JSON line.

config keys: exp (laplace|poisson|poisson_edgevol|poisson_elemvol|element|simple_physics),
mesh (fixture name or IF4), flux (E1|E2), overrides {param: signed|x2}."""
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-23-batch7h-b-nodevolume-mechanism", "scripts"))
import formulas as fm  # noqa: E402  (7H-B, read-only)

UM = 1e-4
L2Q = 1e-8          # l^2 for the Poisson problem, cm^2
SIGMA = 1.0
DV = 1.0
SOLVE = dict(type="dc", absolute_error=1e-12,  # DEVIATIONS.md item 1 (registered 1e-30)
             relative_error=1e-13, maximum_iterations=20, solver_type="direct")


def load_mesh(name):
    if name.startswith("L3_"):
        f = json.load(open(os.path.join(DATA, "l3_meshes.json"), encoding="utf-8"))
        return np.array(f["points_um"]) * UM, {"R": f[name]}, []
    if name == "IF4":
        f = json.load(open(os.path.join(DATA, "fixture_IF4.json"), encoding="utf-8"))
        return np.array(f["points_um"]) * UM, {"A": f["triangles_A"], "B": f["triangles_B"]}, f["interface_nodes"]
    f = json.load(open(os.path.join(DATA, "fixtures_7hc.json"), encoding="utf-8"))["fixtures"][name]
    return np.array(f["points_um"]) * UM, {"R": f["triangles"]}, []


def boundary_edges(tris):
    own = {}
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            own[(min(a, b), max(a, b))] = own.get((min(a, b), max(a, b)), 0) + 1
    return [e for e, n in own.items() if n == 1]


def build_device(dv, P, regions, contact_mode):
    coords = []
    for x, y in P:
        coords += [float(x), float(y), 0.0]
    names = list(regions)
    elements = []
    for ri, (rn, tris) in enumerate(regions.items()):
        for t in tris:
            elements += [2, ri, int(t[0]), int(t[1]), int(t[2])]
    all_tris = [t for ts in regions.values() for t in ts]
    bnd = boundary_edges(all_tris)
    xmin, xmax = P[:, 0].min(), P[:, 0].max()
    contacts = {}
    if contact_mode == "LR":
        contacts["left"] = [e for e in bnd if P[e[0], 0] == xmin and P[e[1], 0] == xmin]
        contacts["right"] = [e for e in bnd if P[e[0], 0] == xmax and P[e[1], 0] == xmax]
    else:
        contacts["all"] = bnd
    for cn, edges in contacts.items():
        names.append(cn)
        for a, b in edges:
            elements += [1, len(names) - 1, int(a), int(b)]
    iface = None
    if len(regions) == 2:
        rA, rB = list(regions.values())
        eA = {(min(a, b), max(a, b)) for t in rA for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))}
        eB = {(min(a, b), max(a, b)) for t in rB for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))}
        names.append("I")
        for a, b in sorted(eA & eB):
            elements += [1, len(names) - 1, a, b]
        iface = "I"
    dv.create_gmsh_mesh(mesh="m", coordinates=coords, elements=elements, physical_names=names)
    for rn in regions:
        dv.add_gmsh_region(gmsh_name=rn, mesh="m", region=rn, material="Si")
    region_of = {}
    for cn, edges in contacts.items():
        nodes = {v for e in edges for v in e}
        rn = next(r for r, ts in regions.items() if any(nodes & set(t) for t in ts))
        region_of[cn] = rn
        dv.add_gmsh_contact(gmsh_name=cn, mesh="m", name=cn, material="metal", region=rn)
    if iface:
        dv.add_gmsh_interface(gmsh_name="I", mesh="m", name="I", region0="A", region1="B")
    dv.finalize_mesh(mesh="m")
    dv.create_device(mesh="m", device="d")
    return contacts, region_of, iface


def signed_edge_couple_values(dv, rn):
    x = np.array(dv.get_node_model_values(device="d", region=rn, name="x"))
    y = np.array(dv.get_node_model_values(device="d", region=rn, name="y"))
    en = dv.get_element_node_list(device="d", region=rn)
    tris = [list(t) for t in en]
    g1, _, _ = fm.edge_couple_predictions(np.column_stack([x, y]), tris)
    dv.edge_from_node_model(device="d", region=rn, node_model="node_index")
    n0 = np.array(dv.get_edge_model_values(device="d", region=rn, name="node_index@n0")).astype(int)
    n1 = np.array(dv.get_edge_model_values(device="d", region=rn, name="node_index@n1")).astype(int)
    return [g1[(min(a, b), max(a, b))] for a, b in zip(n0, n1)], np.column_stack([x, y]), tris


def apply_overrides(dv, regions, ov):
    info = {}
    for rn in regions:
        if "edge_couple_model" in ov:
            if ov["edge_couple_model"] == "signed":
                vals, _, _ = signed_edge_couple_values(dv, rn)
                dv.edge_solution(device="d", region=rn, name="OvEdgeCouple")
                dv.set_edge_values(device="d", region=rn, name="OvEdgeCouple", values=vals)
                info["n_negative_signed_edge_couples_" + rn] = int(sum(1 for v in vals if v < 0))
            else:
                dv.edge_model(device="d", region=rn, name="OvEdgeCouple", equation="2*EdgeCouple")
        if "node_volume_model" in ov:
            if ov["node_volume_model"] == "signed":
                x = np.array(dv.get_node_model_values(device="d", region=rn, name="x"))
                y = np.array(dv.get_node_model_values(device="d", region=rn, name="y"))
                tris = [list(t) for t in dv.get_element_node_list(device="d", region=rn)]
                vol = fm.node_areas(np.column_stack([x, y]), tris, "F2")
                dv.node_solution(device="d", region=rn, name="OvNodeVolume")
                dv.set_node_values(device="d", region=rn, name="OvNodeVolume", values=vol.tolist())
                info["n_negative_signed_node_volumes_" + rn] = int((vol < 0).sum())
            else:
                dv.node_model(device="d", region=rn, name="OvNodeVolume", equation="2*NodeVolume")
        if "edge_node_volume_models" in ov:
            dv.edge_model(device="d", region=rn, name="OvEdgeNodeVolume", equation="2*EdgeNodeVolume")
        if "element_edge_couple_model" in ov:
            if ov["element_edge_couple_model"] == "signed":
                for nm in ("x", "y"):
                    dv.element_from_node_model(device="d", region=rn, node_model=nm)
                eq = ("0.5*pow((x@en0-x@en1)^2+(y@en0-y@en1)^2,0.5)*((x@en0-x@en2)*(x@en1-x@en2)+(y@en0-y@en2)*(y@en1-y@en2))"
                      "/pow(((x@en0-x@en2)*(y@en1-y@en2)-(y@en0-y@en2)*(x@en1-x@en2))^2,0.5)")
                dv.element_model(device="d", region=rn, name="OvElementEdgeCouple", equation=eq)
            else:
                dv.element_model(device="d", region=rn, name="OvElementEdgeCouple", equation="2*ElementEdgeCouple")
        if "element_node_volume_models" in ov:
            dv.element_model(device="d", region=rn, name="OvElementNodeVolume", equation="2*ElementNodeVolume")
    names = {"edge_couple_model": [("edge_couple_model", "OvEdgeCouple")],
             "node_volume_model": [("node_volume_model", "OvNodeVolume")],
             "edge_node_volume_models": [("edge_node0_volume_model", "OvEdgeNodeVolume"), ("edge_node1_volume_model", "OvEdgeNodeVolume")],
             "element_edge_couple_model": [("element_edge_couple_model", "OvElementEdgeCouple")],
             "element_node_volume_models": [("element_node0_volume_model", "OvElementNodeVolume"), ("element_node1_volume_model", "OvElementNodeVolume")]}
    for k in ov:
        for pname, val in names[k]:
            dv.set_parameter(name=pname, value=val)
    info["parameters_set"] = {pn: dv.get_parameter(name=pn) for k in ov for pn, _ in names[k]}
    return info


def edge_flux_models(dv, rn, flux):
    dv.node_solution(device="d", region=rn, name="Potential")
    dv.edge_from_node_model(device="d", region=rn, node_model="Potential")
    base = {"E1": "(Potential@n0-Potential@n1)*EdgeInverseLength", "E2": "(Potential@n0-Potential@n1)*EdgeCouple"}[flux]
    expr = f"{SIGMA}*{base}"
    dv.edge_model(device="d", region=rn, name="Flux", equation=expr)
    for n in ("n0", "n1"):
        dv.edge_model(device="d", region=rn, name=f"Flux:Potential@{n}", equation=f"diff({expr},Potential@{n})")


def element_flux_models(dv, rn):
    dv.node_solution(device="d", region=rn, name="Potential")
    for nm in ("Potential", "x", "y"):
        dv.element_from_node_model(device="d", region=rn, node_model=nm)
    inv = "pow((x@en0-x@en1)^2+(y@en0-y@en1)^2,-0.5)"
    dv.element_model(device="d", region=rn, name="EFlux", equation=f"{SIGMA}*(Potential@en0-Potential@en1)*{inv}")
    dv.element_model(device="d", region=rn, name="EFlux:Potential@en0", equation=f"{SIGMA}*{inv}")
    dv.element_model(device="d", region=rn, name="EFlux:Potential@en1", equation=f"-{SIGMA}*{inv}")
    dv.element_model(device="d", region=rn, name="EFlux:Potential@en2", equation="0")


def contacts_dirichlet(dv, contact_region, exp, element=False):
    for cn in contact_region:
        if exp.startswith("poisson"):
            val = f"(x*x+y*y)/{L2Q}"
        else:
            val = "0" if cn == "left" else f"{DV}"
        dv.contact_node_model(device="d", contact=cn, name=f"{cn}_bc", equation=f"Potential-({val})")
        dv.contact_node_model(device="d", contact=cn, name=f"{cn}_bc:Potential", equation="1")
        kw = {"element_current_model": "EFlux"} if element else {"edge_current_model": "Flux"}
        dv.contact_equation(device="d", contact=cn, name="PE", node_model=f"{cn}_bc", **kw)


def matrix_dense(dv):
    m = dv.get_matrix_and_rhs(format="csr")["static"]
    ap, ai, av = np.array(m["ap"]), np.array(m["ai"]), np.array(m["av"])
    n = len(ap) - 1
    J = np.zeros((n, n))
    for r in range(n):
        for k in range(ap[r], ap[r + 1]):
            J[r, ai[k]] += av[k]
    return J, np.array(m["rhs"])


def run(cfg):
    import devsim as dv
    exp, mesh, flux, ov = cfg["exp"], cfg["mesh"], cfg.get("flux", "E1"), cfg.get("overrides", {})
    P, regions, iface_nodes = load_mesh(mesh)
    EQ = "PotentialEquation" if exp == "simple_physics" else "PE"
    contacts, region_of, iface = build_device(dv, P, regions, "ALL" if exp.startswith("poisson") else "LR")
    out = {"cfg": cfg}
    out["override_info"] = apply_overrides(dv, regions, ov)
    for rn in regions:
        if exp == "element":
            element_flux_models(dv, rn)
            dv.equation(device="d", region=rn, name="PE", variable_name="Potential", element_model="EFlux", variable_update="default")
        elif exp == "simple_physics":
            from devsim.python_packages.simple_physics import (SetSiliconParameters, CreateSiliconPotentialOnly,
                                                               CreateSiliconPotentialOnlyContact, GetContactBiasName)
            from devsim.python_packages.model_create import CreateSolution
            SetSiliconParameters("d", rn, 300.0)
            dv.node_model(device="d", region=rn, name="NetDoping", equation="0")
            CreateSolution("d", rn, "Potential")
            CreateSiliconPotentialOnly("d", rn)
        else:
            edge_flux_models(dv, rn, flux)
            kw = {}
            if exp == "poisson":
                dv.node_model(device="d", region=rn, name="Src", equation=f"{4.0 / L2Q}")
                dv.node_model(device="d", region=rn, name="Src:Potential", equation="0")
                kw["node_model"] = "Src"
            if exp == "poisson_edgevol":
                dv.edge_model(device="d", region=rn, name="ESrc", equation=f"{4.0 / L2Q}")
                dv.edge_model(device="d", region=rn, name="ESrc:Potential@n0", equation="0")
                dv.edge_model(device="d", region=rn, name="ESrc:Potential@n1", equation="0")
                kw["edge_volume_model"] = "ESrc"
            if exp == "poisson_elemvol":
                dv.element_model(device="d", region=rn, name="ElSrc", equation=f"{4.0 / L2Q}")
                for n in ("en0", "en1", "en2"):
                    dv.element_model(device="d", region=rn, name=f"ElSrc:Potential@{n}", equation="0")
                kw["volume_node0_model"] = "ElSrc"
                kw["volume_node1_model"] = "ElSrc"
            dv.equation(device="d", region=rn, name="PE", variable_name="Potential", edge_model="Flux",
                        variable_update="default", **kw)
    if iface:
        dv.interface_model(device="d", interface=iface, name="cont", equation="Potential@r0-Potential@r1")
        dv.interface_model(device="d", interface=iface, name="cont:Potential@r0", equation="1")
        dv.interface_model(device="d", interface=iface, name="cont:Potential@r1", equation="-1")
        dv.interface_equation(device="d", interface=iface, name="PE", interface_model="cont", type="continuous")
    if exp == "simple_physics":
        for cn, rn in region_of.items():
            dv.set_parameter(device="d", name=GetContactBiasName(cn), value=0.0 if cn == "left" else 0.01)
            CreateSiliconPotentialOnlyContact("d", rn, cn)
    else:
        contacts_dirichlet(dv, region_of, exp, element=(exp == "element"))
    dv.solve(**SOLVE)
    J, rhs = matrix_dense(dv)
    res = {}
    for rn in regions:
        x = np.array(dv.get_node_model_values(device="d", region=rn, name="x"))
        y = np.array(dv.get_node_model_values(device="d", region=rn, name="y"))
        phi = np.array(dv.get_node_model_values(device="d", region=rn, name="Potential"))
        nv = np.array(dv.get_node_model_values(device="d", region=rn, name="NodeVolume"))
        eqn = np.array(dv.get_equation_numbers(device="d", region=rn, equation=EQ))
        cnodes = set()
        for cn, rr in region_of.items():
            if rr == rn:
                for e in contacts[cn]:
                    cnodes |= set(e)
        # region node order == global point order is verified: compare coordinates
        tris = [list(t) for t in dv.get_element_node_list(device="d", region=rn)]
        Lx = P[:, 0].max() - P[:, 0].min()
        if exp.startswith("poisson"):
            phia = (x * x + y * y) / L2Q
        elif exp == "simple_physics":
            phia = None
        else:
            phia = (x - P[:, 0].min()) / Lx * DV
        # map region-local node index -> global point index by coordinates
        gidx = {(float(a), float(b)): i for i, (a, b) in enumerate(P)}
        loc2glob = [gidx[(float(a), float(b))] for a, b in zip(x, y)]
        free = [i for i in range(len(x)) if loc2glob[i] not in cnodes]
        r = {"n_nodes": len(x), "n_free_nodes": len(free), "sum_NodeVolume_cm2": float(nv.sum()),
             "area_cm2": float(sum(fm.tri_area(np.column_stack([x, y])[t]) for t in tris))}
        if phia is not None:
            err = phi - phia
            r.update({"Linf_all_V": float(np.abs(err).max()), "Linf_free_V": float(np.abs(err[free]).max()) if free else 0.0,
                      "L2_free_V": float(np.sqrt(np.mean(err[free] ** 2))) if free else 0.0,
                      "err_free_V": {int(loc2glob[i]): float(err[i]) for i in free}})
            if exp.startswith("poisson"):
                r["phi_scale_V"] = float(np.abs(phia).max())
            dphi = phia - phi
            f_a = J[np.ix_(eqn, eqn)] @ dphi if len(regions) == 1 else None
            if f_a is not None:
                rows = {i: float(f_a[i]) for i in free}
                r["residual_at_analytic_free_max_abs"] = float(max((abs(v) for v in rows.values()), default=0.0))
                r["residual_at_analytic_free"] = {int(loc2glob[i]): v for i, v in rows.items()}
                if exp.startswith("poisson"):
                    flux_part = J[np.ix_(eqn, eqn)] @ phia
                    r["poisson_flux_part_free"] = {int(loc2glob[i]): float(flux_part[i]) for i in free}
                    r["poisson_source_part_free"] = {int(loc2glob[i]): float(f_a[i] - flux_part[i]) for i in free}
                    r["Z_times_NodeVolume_free"] = {int(loc2glob[i]): float(4.0 / L2Q * nv[i]) for i in free}
                    # P5 prediction: -(2/l^2) x_i . sum_j w_abs,ij (x_j - x_i), with w from the matrix row
                    pred = {}
                    for i in free:
                        row = J[eqn[i], eqn]
                        s = np.zeros(2)
                        for j in range(len(x)):
                            if j != i and row[j] != 0:
                                s += (-row[j]) * np.array([x[j] - x[i], y[j] - y[i]])
                        pred[int(loc2glob[i])] = float(-(2.0 / L2Q) * (x[i] * s[0] + y[i] * s[1]))
                    r["P5_predicted_residual_free"] = pred
        # effective edge weights from the matrix (free rows), vs EdgeCouple/EdgeLength and EdgeCouple^2
        if len(regions) == 1 and exp not in ("simple_physics",):
            dv.edge_from_node_model(device="d", region=rn, node_model="node_index")
            n0 = np.array(dv.get_edge_model_values(device="d", region=rn, name="node_index@n0")).astype(int)
            n1 = np.array(dv.get_edge_model_values(device="d", region=rn, name="node_index@n1")).astype(int)
            C = np.array(dv.get_edge_model_values(device="d", region=rn, name="EdgeCouple"))
            Le = np.array(dv.get_edge_model_values(device="d", region=rn, name="EdgeLength"))
            sgn, _, _ = signed_edge_couple_values(dv, rn) if True else (None, None, None)
            rows = []
            for k, (a, b) in enumerate(zip(n0, n1)):
                for i, j in ((a, b), (b, a)):
                    if i in free:
                        w = -J[eqn[i], eqn[j]]
                        rows.append({"edge": [int(loc2glob[a]), int(loc2glob[b])], "w_matrix": float(w),
                                     "C_over_L": float(C[k] / Le[k]), "C_squared": float(C[k] ** 2),
                                     "signed_C_over_L": float(sgn[k] / Le[k]), "C_devsim": float(C[k]), "L": float(Le[k])})
            r["weights"] = rows
        if exp == "simple_physics":
            dv.edge_from_node_model(device="d", region=rn, node_model="node_index")
            n0 = np.array(dv.get_edge_model_values(device="d", region=rn, name="node_index@n0")).astype(int)
            n1 = np.array(dv.get_edge_model_values(device="d", region=rn, name="node_index@n1")).astype(int)
            C = np.array(dv.get_edge_model_values(device="d", region=rn, name="EdgeCouple"))
            Le = np.array(dv.get_edge_model_values(device="d", region=rn, name="EdgeLength"))
            eps = dv.get_parameter(device="d", region=rn, name="Permittivity")
            sgn, _, _ = signed_edge_couple_values(dv, rn)
            rows = []
            for k, (a, b) in enumerate(zip(n0, n1)):
                for i, j in ((a, b), (b, a)):
                    if i in free:
                        rows.append({"w_matrix_over_eps": float(-J[eqn[i], eqn[j]] / eps), "C_over_L": float(C[k] / Le[k]),
                                     "signed_C_over_L": float(sgn[k] / Le[k])})
            r["weights_over_permittivity"] = rows
        res[rn] = r
    out["regions"] = res
    out["contact_current"] = {cn: float(dv.get_contact_current(device="d", contact=cn, equation=EQ)) for cn in contacts}
    out["rhs_final_max_abs"] = float(np.abs(rhs).max())
    return out


if __name__ == "__main__":
    cfg = json.loads(sys.argv[1])
    try:
        r = run(cfg)
    except Exception as e:  # recorded, never hidden
        r = {"cfg": cfg, "error": repr(e)[:800]}
    print("===RESULT_JSON===")
    print(json.dumps(r, default=float))
