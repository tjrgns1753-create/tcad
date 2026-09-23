"""Batch 7H-B: read DEVSIM's public geometric models for one device/region.
Public API only: create_gmsh_mesh / add_gmsh_region / finalize_mesh /
create_device, get_node_model_values, get_edge_model_values,
get_element_model_values, get_element_node_list, edge_from_node_model,
element_from_node_model, delete_device, delete_mesh. No solve, no PDE."""
import numpy as np

EPS = 2.220446049250313e-16
ABS_FACTOR = 256
REL_TOL = 1e-11


def match(d, p, abs_tol):
    return abs(d - p) <= abs_tol + REL_TOL * abs(p)


def import_fixture(devsim, pts_cm, tris, name):
    coords = []
    for x, y in pts_cm:
        coords += [float(x), float(y), 0.0]
    elements = []
    for a, b, c in tris:
        elements += [2, 0, int(a), int(b), int(c)]
    mesh, dev = f"m7hb_{name}", f"d7hb_{name}"
    devsim.create_gmsh_mesh(mesh=mesh, coordinates=coords, elements=elements, physical_names=["R"])
    devsim.add_gmsh_region(gmsh_name="R", mesh=mesh, region="R", material="Si")
    devsim.finalize_mesh(mesh=mesh)
    devsim.create_device(mesh=mesh, device=dev)
    return dev, "R", mesh


def read_models(devsim, dev, region):
    g = lambda n: np.array(devsim.get_node_model_values(device=dev, region=region, name=n))  # noqa: E731
    out = {"x": g("x"), "y": g("y"), "node_index": g("node_index"), "NodeVolume": g("NodeVolume"),
           "node_models": list(devsim.get_node_model_list(device=dev, region=region)),
           "edge_models_builtin": list(devsim.get_edge_model_list(device=dev, region=region)),
           "element_models_builtin": list(devsim.get_element_model_list(device=dev, region=region))}
    devsim.edge_from_node_model(device=dev, region=region, node_model="node_index")
    e = lambda n: np.array(devsim.get_edge_model_values(device=dev, region=region, name=n))  # noqa: E731
    out["edge_n0"], out["edge_n1"] = e("node_index@n0"), e("node_index@n1")
    for n in ("EdgeCouple", "EdgeLength", "EdgeNodeVolume"):
        out[n] = e(n) if n in out["edge_models_builtin"] else None
    devsim.element_from_node_model(device=dev, region=region, node_model="node_index")
    el = lambda n: np.array(devsim.get_element_model_values(device=dev, region=region, name=n))  # noqa: E731
    out["el_en0"], out["el_en1"], out["el_en2"] = el("node_index@en0"), el("node_index@en1"), el("node_index@en2")
    for n in ("ElementEdgeCouple", "ElementNodeVolume"):
        out[n] = el(n) if n in out["element_models_builtin"] else None
    out["element_node_list"] = [tuple(int(v) for v in t) for t in devsim.get_element_node_list(device=dev, region=region)]
    return out


def verify_import(m, pts_cm, tris):
    """Coordinates, node order and connectivity must equal the input exactly."""
    n = len(pts_cm)
    coords_ok = len(m["x"]) == n and bool(np.all(m["x"] == pts_cm[:, 0]) and np.all(m["y"] == pts_cm[:, 1]))
    index_ok = bool(np.all(m["node_index"] == np.arange(n)))
    conn_ok = sorted(tuple(sorted(t)) for t in m["element_node_list"]) == sorted(tuple(sorted(int(v) for v in t)) for t in tris)
    edges_in = set()
    for a, b, c in tris:
        for u, v in ((a, b), (b, c), (c, a)):
            edges_in.add((min(u, v), max(u, v)))
    e0, e1 = m["edge_n0"].astype(int), m["edge_n1"].astype(int)
    edge_map_ok = (bool(np.all(m["edge_n0"] == e0) and np.all(m["edge_n1"] == e1))
                   and {(min(a, b), max(a, b)) for a, b in zip(e0, e1)} == edges_in and len(e0) == len(edges_in))
    if edge_map_ok and m["EdgeLength"] is not None:
        L = np.hypot(pts_cm[e0, 0] - pts_cm[e1, 0], pts_cm[e0, 1] - pts_cm[e1, 1])
        edge_map_ok = bool(np.allclose(m["EdgeLength"], L, rtol=1e-13, atol=0))
    t0, t1, t2 = m["el_en0"].astype(int), m["el_en1"].astype(int), m["el_en2"].astype(int)
    tri_set = {tuple(sorted(int(v) for v in t)) for t in tris}
    el_map_ok = all(tuple(sorted((a, b, c))) in tri_set and len({a, b, c}) == 3 for a, b, c in zip(t0, t1, t2)) \
        and len(t0) == 3 * len(tris)
    return {"coords_equal": coords_ok, "node_index_identity": index_ok, "connectivity_equal": conn_ok,
            "edge_endpoint_mapping_proven": edge_map_ok, "element_edge_mapping_proven": el_map_ok}
