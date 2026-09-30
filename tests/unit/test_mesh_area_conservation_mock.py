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
    MAX_AREA_RELATIVE_UNCERTAINTY, MeshAreaConservationError, check_mesh_input, check_nodevolume,
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
    assert rep["Si"]["pass"] and abs(rep["Si"]["relative_difference"]) <= rep["Si"]["relative_uncertainty"], rep
    assert rep["Si"]["relative_uncertainty"] <= MAX_AREA_RELATIVE_UNCERTAINTY and rep["Si"]["budget_basis"].startswith("ASSUMED_BOUND")
    print(f"single material exact: pass, rel {rep['Si']['relative_difference']!r} B/A {rep['Si']['relative_uncertainty']!r}")

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

    # area-tolerance boundary (7H-E6E-R1 PLAN case 9, second part): a one-node region with a known budget (E_A = 0, E_NV = 1e-9,
    # under the 1e-8 certification limit; E_S = u S ~1e-16 is far below the 2^-10 margin), S = 1 + 1e-9 (1 -/+ 2^-10)
    p, t, g = grid()
    terms = check_mesh_input(p, t, g, {1: "Si"}, [])
    base = dual_nodevolume(p, t, g, 1)
    kt = {"Si": {"triangles": 1, "area": 1.0, "E_A": 0.0, "E_NV": 1e-9}}
    assert check_nodevolume(kt, {"Si": np.array([1.0 + 1e-9 * (1 - 2 ** -10)])}, {"Si": 1})["Si"]["pass"]
    refused(lambda: check_nodevolume(kt, {"Si": np.array([1.0 + 1e-9 * (1 + 2 ** -10)])}, {"Si": 1}), "MESH_AREA_NOT_CONSERVED")
    print("tolerance boundary: B(1 - 2^-10) pass, B(1 + 2^-10) refused")

    # certification-limit boundary (case 9, first part): S = A = 1.0, E_NV = 1e-8 (1 -/+ 2^-10)
    lim_in = {"Si": {"triangles": 1, "area": 1.0, "E_A": 0.0, "E_NV": 1e-8 * (1 - 2 ** -10)}}
    lim_out = {"Si": {"triangles": 1, "area": 1.0, "E_A": 0.0, "E_NV": 1e-8 * (1 + 2 ** -10)}}
    assert check_nodevolume(lim_in, {"Si": np.array([1.0])}, {"Si": 1})["Si"]["pass"]
    refused(lambda: check_nodevolume(lim_out, {"Si": np.array([1.0])}, {"Si": 1}), "MESH_AREA_UNCERTAINTY_TOO_LARGE")
    print("certification limit boundary: B/A 1e-8(1 - 2^-10) pass, 1e-8(1 + 2^-10) refused")

    # P0 sliver (cases 1, 2): the counterexample that PASSED before 7H-E6E-R1 (p0_before.json) -- S = 2A and S = A both refused
    ps = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 1e-14, 0.0]])
    ts, gs = np.array([[0, 1, 2]]), np.array([1])
    st = check_mesh_input(ps, ts, gs, {1: "Si"}, [])
    A = st["Si"]["area"]
    for label, s_total in (("S = 2A", 2 * A), ("S = A", A)):
        exc = refused(lambda s_total=s_total: check_nodevolume(st, {"Si": np.full(3, s_total / 3)}, {"Si": 1}),
                      "MESH_AREA_UNCERTAINTY_TOO_LARGE")
        r = exc.physics_status["regions"]["Si"]
        assert r["relative_uncertainty"] > MAX_AREA_RELATIVE_UNCERTAINTY and r["certification_limit"] == MAX_AREA_RELATIVE_UNCERTAINTY
        assert r["budget_basis"].startswith("ASSUMED_BOUND") and "pass" not in r
        print(f"P0 sliver {label}: refused, B/A {r['relative_uncertainty']!r}, S/A-1 {r['relative_difference']!r}")

    # non-finite budget (case 3): E_NV = inf; S overflow; o_t overflow from 1e200 coordinates
    refused(lambda: check_nodevolume({"Si": {"triangles": 1, "area": 1.0, "E_A": 0.0, "E_NV": float("inf")}}, {"Si": np.array([1.0])},
                                     {"Si": 1}), "MESH_AREA_BUDGET_NONFINITE")
    refused(lambda: check_nodevolume({"Si": {"triangles": 1, "area": 1.0, "E_A": 0.0, "E_NV": 0.0}}, {"Si": np.array([1e308, 1e308])},
                                     {"Si": 1}), "MESH_AREA_BUDGET_NONFINITE")
    refused(lambda: check_mesh_input(p * 1e200, t, g, {1: "Si"}, []), "MESH_AREA_BUDGET_NONFINITE")
    refused(lambda: check_nodevolume({"Si": {"triangles": 1, "area": 0.0, "E_A": 0.0, "E_NV": 0.0}}, {"Si": np.array([1.0])},
                                     {"Si": 1}), "MESH_AREA_INVALID")
    print("non-finite budget / S overflow / o_t overflow / zero area: refused")

    # normal shape, real mismatch (case 7)
    off = base.copy()
    off[0] += 0.01
    refused(lambda: check_nodevolume(terms, {"Si": off}, {"Si": len(t)}), "MESH_AREA_NOT_CONSERVED")
    print("normal shape, S = A + 0.01: MESH_AREA_NOT_CONSERVED")

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
