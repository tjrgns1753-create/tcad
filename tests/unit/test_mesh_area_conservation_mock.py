#!/usr/bin/env python3
"""Pure (no DEVSIM) checks of tcad.device.devsim.mesh_conservation -- the
fail-closed per-region area-conservation gate of import_process_result().
Fixtures and expectations: docs/audits/2026-09-30-batch7h-e6e-area-conservation-gate/PLAN.md section 4.
NodeVolume is supplied as the exact per-node dual area of a structured
right-triangle mesh, perturbed where a case needs it."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tcad.device.devsim.mesh_conservation import (  # noqa: E402
    MeshAreaConservationError, check_mesh_input, check_nodevolume,
)


def grid(nx=4, ny=3, x0=0.0, h=0.5, split=None):
    """nx x ny squares of side h split into 2 right triangles; tag 1 for cells with x < split (or all), 2 otherwise."""
    pts = np.array([[x0 + i * h, j * h, 0.0] for j in range(ny + 1) for i in range(nx + 1)])
    tris, tags = [], []
    for j in range(ny):
        for i in range(nx):
            a, b = j * (nx + 1) + i, j * (nx + 1) + i + 1
            c, d = b + nx + 1, a + nx + 1
            tris += [(a, b, c), (a, c, d)]
            t = 1 if split is None or i < split else 2
            tags += [t, t]
    return pts, np.array(tris), np.array(tags)


def dual_nodevolume(pts, tris, tags, tag):
    """Right-triangle circumcentric dual: each triangle gives 1/4 of its area to each acute vertex and 1/2 to the right-angle vertex
    (circumcenter at the hypotenuse midpoint). Returns the region's per-node values (region-local nodes)."""
    nv = {}
    for (a, b, c), t in zip(tris, tags):
        if t != tag:
            continue
        u, v = pts[b, :2] - pts[a, :2], pts[c, :2] - pts[a, :2]
        A = abs(u[0] * v[1] - u[1] * v[0]) / 2
        for v, o1, o2 in ((a, b, c), (b, c, a), (c, a, b)):
            right = abs(np.dot(pts[o1, :2] - pts[v, :2], pts[o2, :2] - pts[v, :2])) == 0.0
            nv[v] = nv.get(v, 0.0) + (A / 2 if right else A / 4)
    return np.array(list(nv.values()))


def refused(fn, code):
    try:
        fn()
    except MeshAreaConservationError as exc:
        assert exc.physics_status["resolution"] == "UNSUPPORTED_BY_MODEL", exc.physics_status
        assert exc.physics_status["reason_code"] == code, (code, exc.physics_status["reason_code"])
        return exc
    raise AssertionError(f"expected refusal {code}")


def main():
    # exact single material
    p, t, g = grid()
    terms = check_mesh_input(p, t, g, {1: "Si"}, [])
    rep = check_nodevolume(terms, {"Si": dual_nodevolume(p, t, g, 1)}, {"Si": len(t)})
    assert rep["Si"]["pass"] and abs(rep["Si"]["relative_difference"]) <= rep["Si"]["tau"], rep
    print(f"single material exact: pass, rel {rep['Si']['relative_difference']!r} tau {rep['Si']['tau']!r}")

    # exact two materials, and the large-coordinate control
    p, t, g = grid(split=2)
    terms = check_mesh_input(p, t, g, {1: "Si", 2: "SiO2"}, [])
    nvs = {"Si": dual_nodevolume(p, t, g, 1), "SiO2": dual_nodevolume(p, t, g, 2)}
    rep = check_nodevolume(terms, nvs, {"Si": int((g == 1).sum()), "SiO2": int((g == 2).sum())})
    assert rep["Si"]["pass"] and rep["SiO2"]["pass"], rep
    pL, tL, gL = grid(x0=1.0e4)
    pL[:, 1] += 1.0e4
    termsL = check_mesh_input(pL, tL, gL, {1: "Si"}, [])
    repL = check_nodevolume(termsL, {"Si": dual_nodevolume(pL, tL, gL, 1)}, {"Si": len(tL)})
    assert repL["Si"]["pass"], repL
    print("two materials exact, large-coordinate control: pass")

    # opposite errors in two regions: the total is exact, each region fails
    d = 0.01
    bad = {"Si": nvs["Si"].copy(), "SiO2": nvs["SiO2"].copy()}
    bad["Si"][0] += d
    bad["SiO2"][0] -= d
    tot = sum(v.sum() for v in bad.values()) - sum(v.sum() for v in nvs.values())
    assert abs(tot) < 1e-15
    exc = refused(lambda: check_nodevolume(terms, bad, {"Si": int((g == 1).sum()), "SiO2": int((g == 2).sum())}),
                  "MESH_AREA_NOT_CONSERVED")
    assert exc.physics_status["first_failing_region"] == "Si"
    print("cancelling region errors: refused per region")

    # boundary just inside / outside the tolerance: a one-node region with a known budget (E_A = 0, E_NV = 1e-6; E_S = u S is
    # ~1e-16, far below the 2^-10 margin), so B*(1 -/+ 2^-10) is representable next to the area 1.0
    p, t, g = grid()
    terms = check_mesh_input(p, t, g, {1: "Si"}, [])
    base = dual_nodevolume(p, t, g, 1)
    kt = {"Si": {"triangles": 1, "area": 1.0, "E_A": 0.0, "E_NV": 1e-6}}
    assert check_nodevolume(kt, {"Si": np.array([1.0 + 1e-6 * (1 - 2 ** -10)])}, {"Si": 1})["Si"]["pass"]
    refused(lambda: check_nodevolume(kt, {"Si": np.array([1.0 + 1e-6 * (1 + 2 ** -10)])}, {"Si": 1}), "MESH_AREA_NOT_CONSERVED")
    print("tolerance boundary: B(1 - 2^-10) pass, B(1 + 2^-10) refused")

    # invalid NodeVolume / region / element count
    nonfin = base.copy()
    nonfin[1] = np.nan
    refused(lambda: check_nodevolume(terms, {"Si": nonfin}, {"Si": len(t)}), "MESH_NODEVOLUME_INVALID")
    neg = base.copy()
    neg[1] = -neg[1]
    refused(lambda: check_nodevolume(terms, {"Si": neg}, {"Si": len(t)}), "MESH_NODEVOLUME_INVALID")
    refused(lambda: check_nodevolume(terms, {}, {"Si": len(t)}), "MESH_NODEVOLUME_INVALID")          # missing region
    refused(lambda: check_nodevolume(terms, {"Si": base}, {"Si": len(t) - 1}), "MESH_REGION_ELEMENT_MISMATCH")
    print("non-finite / non-positive / missing NodeVolume, element mismatch: refused")

    # input checks
    pn = p.copy()
    pn[3, 0] = np.inf
    refused(lambda: check_mesh_input(pn, t, g, {1: "Si"}, []), "MESH_NONFINITE_COORDINATES")
    pz = p.copy()
    pz[3, 2] = 1e-9
    refused(lambda: check_mesh_input(pz, t, g, {1: "Si"}, []), "MESH_NOT_PLANAR_2D")
    refused(lambda: check_mesh_input(p, t, g, {1: "Si"}, ["quad"]), "MESH_UNSUPPORTED_CELLS")
    refused(lambda: check_mesh_input(p, t, g, {2: "Si"}, []), "MESH_TAG_UNMAPPED")
    refused(lambda: check_mesh_input(p, t, g[:-1], {1: "Si"}, []), "MESH_TAG_UNMAPPED")
    refused(lambda: check_mesh_input(p, t, g, {1: "Si", 2: "SiO2"}, []), "MESH_EMPTY_REGION")
    refused(lambda: check_mesh_input(p, np.vstack([t, t[:1]]), np.r_[g, g[:1]], {1: "Si"}, []), "MESH_DUPLICATE_TRIANGLE")
    pd = p.copy()
    td = t.copy()
    td[0] = (0, 1, 2)                                   # three collinear nodes on y = 0
    refused(lambda: check_mesh_input(pd, td, g, {1: "Si"}, []), "MESH_DEGENERATE_TRIANGLE")
    tm = t.copy()
    tm[0] = tm[0][[0, 2, 1]]                            # one inverted triangle
    refused(lambda: check_mesh_input(p, tm, g, {1: "Si"}, []), "MESH_ORIENTATION_MIXED")
    tcw = t[:, [0, 2, 1]]                               # consistently clockwise: accepted
    check_mesh_input(p, tcw, g, {1: "Si"}, [])
    print("input checks: non-finite, non-planar, extra cells, unmapped tag, empty region, duplicate, degenerate, mixed: refused; "
          "consistent clockwise accepted")

    print("ALL MESH AREA CONSERVATION MOCK CHECKS PASSED")


if __name__ == "__main__":
    main()
