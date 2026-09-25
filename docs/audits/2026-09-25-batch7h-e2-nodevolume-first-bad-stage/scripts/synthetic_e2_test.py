"""Batch 7H-E2 SYNTHETIC test (no ViennaPS / DEVSIM): trace copy == production refine_mesh_near on a synthetic
structured right-triangle grid with mixed orientation; CCW-only control; exact area invariance; verdict rules.
usage: synthetic_e2_test.py <work dir>"""
import copy
import json
import os
import sys

sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import trace_refine_e2 as tr  # noqa: E402
import verdicts_e2 as vd  # noqa: E402
from tcad.device.devsim.mesh_refine import refine_mesh_near  # noqa: E402  (pure numpy)


def grid(h=0.05, x0=-0.5, x1=0.5, y0=-0.3, y1=0.0):
    xs = np.arange(round((x1 - x0) / h) + 1) * h + x0
    ys = np.arange(round((y1 - y0) / h) + 1) * h + y0
    P = np.array([(x, y, 0.0) for y in ys for x in xs], dtype=np.float32)
    nx = len(xs)
    T = []
    for j in range(len(ys) - 1):
        for i in range(nx - 1):
            a, b, c, d = j * nx + i, j * nx + i + 1, (j + 1) * nx + i, (j + 1) * nx + i + 1
            t1, t2 = (a, b, d), (a, d, c)
            if (i + j) % 3 == 0:          # mixed orientation, as in the E1 mesh (all_ccw false)
                t1, t2 = (a, d, b), (a, c, d)
            T += [t1, t2]
    return P, np.array(T, dtype=np.int64), np.full(len(T), 1.0)


def main():
    work = os.path.abspath(sys.argv[1])
    os.makedirs(work, exist_ok=True)
    res, ok = {}, True
    P, T, G = grid()
    pred = lambda c: abs(c[0] - 0.0) < 0.1  # noqa: E731
    states, origin, kinds = tr.refine_traced(P, T, G, pred, 4)
    i1 = []
    a0 = tr.exact_area(P[:, :2], T)
    for k in range(5):
        pp, tt, gg = refine_mesh_near(P, T, G, pred, levels=k)
        sp, st, sg = states[k]
        eq = bool(np.array_equal(pp, sp) and np.array_equal(tt, st) and np.array_equal(gg, sg))
        area_eq = tr.exact_area(sp[:, :2], st) == a0
        n_obt = int((tr.max_angle_deg_per_triangle(sp[:, :2], st) > 90.0 + 1e-9).sum())
        i1.append({"k": k, "trace_equals_production": eq, "exact_area_equal_S0": area_eq, "n_triangles": len(st),
                   "n_obtuse_float": n_obt, "origin_len_ok": len(origin[k]) == len(st), "kinds_len_ok": len(kinds[k]) == len(st)})
        ok &= eq and area_eq and len(origin[k]) == len(st)
    res["trace"] = i1
    t4 = states[4][1]
    ccw, nflip = tr.ccw_only(states[4][0], t4)
    all_pos = all(tr.exact_orient2(*(states[4][0][v] for v in t)) > 0 for t in ccw)
    same_sets = bool(np.array_equal(np.sort(ccw, 1), np.sort(t4, 1)))
    res["ccw"] = {"n_reoriented": nflip, "all_ccw_after": all_pos, "same_vertex_sets": same_sets}
    ok &= all_pos and same_sets and nflip > 0
    b = tr.node_budget(states[4][0][:, :2], t4, len(states[4][0]))
    res["budget"] = {"min": float(b.min()), "max": float(b.max())}
    ok &= bool(np.all(b > 0) and np.all(b < 1e-10))

    # verdict rules on synthetic stage records
    def st(k, ratio, **kw):
        r = {"k": k, "ratio": ratio, "tau": 1e-11, "identity": {"I1": True, "I2": True}, "exact_area_cm2": "1/2",
             "contact_nodes_sha256": "c", "tags_all_si": True, "regions": ["Si"], "f3_all_nodes_within_budget": True,
             "excess_explained_by_F3_within_tau": True, "f3_excess_nodes_all_obtuse_vertices": True}
        r.update(kw)
        return r
    good = [st(0, 1.0), st(1, 1.0), st(2, 1.01), st(3, 1.03), st(4, 1.058)]
    rt = {"reproduces_S4": True, "ratio": 1.058, "tau": 1e-11}
    ccw_same = {"n_nodes_beyond_budget_vs_rt": 0, "ratio": 1.058, "tau": 1e-11}
    ccw_fix = {"n_nodes_beyond_budget_vs_rt": 10, "ratio": 1.0, "tau": 1e-11}
    cases = {
        "shape_first_bad_2": (vd.decide(good, True, rt, ccw_same), {"FIRST_BAD_STAGE=2", "NO_ORIENTATION_EFFECT", "SHAPE_CAUSE"}, True),
        "pre_existing": (vd.decide([st(0, 1.001)] + good[1:], True, rt, ccw_same), {"PRE_EXISTING", "NO_ORIENTATION_EFFECT"}, False),
        "orientation_cause": (vd.decide(good, True, rt, ccw_fix), {"FIRST_BAD_STAGE=2", "ORIENTATION_EFFECT", "ORIENTATION_CAUSE"}, False),
        "i3_fail": (vd.decide(good, False, rt, ccw_same), {"INCONCLUSIVE"}, False),
        "c_rt_fail": (vd.decide(good, True, {"reproduces_S4": False}, ccw_same), {"FIRST_BAD_STAGE=2"}, False),
        "identity_fail": (vd.decide([good[0], st(1, 1.0, identity={"I1": False, "I2": True})] + good[2:], True, rt, ccw_same),
                          {"NO_ORIENTATION_EFFECT", "INCONCLUSIVE"}, False),
        "area_differs": (vd.decide([good[0], st(1, 1.0, exact_area_cm2="3/5")] + good[2:], True, rt, ccw_same),
                         {"NO_ORIENTATION_EFFECT", "INCONCLUSIVE"}, False),
        "f3_unexplained": (vd.decide([*good[:2], st(2, 1.01, excess_explained_by_F3_within_tau=False), *good[3:]], True, rt, ccw_same),
                           {"FIRST_BAD_STAGE=2", "NO_ORIENTATION_EFFECT"}, False),
    }
    res["verdict_cases"] = {}
    for name, (dec, want, cand) in cases.items():
        got = set(dec["verdicts"])
        good_case = got == want and dec["candidate_allowed"] == cand
        res["verdict_cases"][name] = {"got": sorted(got), "want": sorted(want), "candidate_allowed": dec["candidate_allowed"],
                                      "ok": good_case}
        ok &= good_case
    full = {k: True for k in ("points_identical", "boundary_edges_equal", "interface_edges_equal", "x0_edges_equal",
                              "tag_counter_equal", "exact_area_equal", "no_duplicate_zero_nonmanifold", "no_positive_overlap",
                              "flip_terminated_clean", "contacts_equal", "regions_equal", "ratio_within_tau",
                              "inventory_donor_within_tau", "inventory_acceptor_within_tau")}
    bad = copy.deepcopy(full)
    bad["ratio_within_tau"] = False
    cv = [vd.candidate_verdict(full)["verdict"], vd.candidate_verdict(bad)["verdict"], vd.candidate_verdict({})["verdict"]]
    res["candidate_cases"] = cv
    ok &= cv == ["CANDIDATE_PASSES_AUDIT_CHECKS", "CANDIDATE_REJECTED", "CANDIDATE_REJECTED"]
    res["ALL_OK"] = bool(ok)
    json.dump(res, open(os.path.join(work, "synthetic_e2_results.json"), "w"), indent=1, default=str)
    print(json.dumps(res, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
