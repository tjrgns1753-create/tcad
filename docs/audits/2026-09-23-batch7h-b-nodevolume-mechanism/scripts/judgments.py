"""Batch 7H-B Phase D: H1-H6 decided mechanically from fixture_results.json.
Edge classification (boundary vs interior) is by owner count only."""
import json
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fixtures as fx  # noqa: E402

CONF, EXCL, CORR, UNRES = ("CONFIRMED_BY_CONTROLLED_INTERVENTION", "EXCLUDED_BY_CONTROLLED_INTERVENTION",
                           "CORRELATED_ONLY", "UNRESOLVED")
RATIO_EQ = 1e-12   # "ratio == 1" test uses the same order as REL_TOL-level agreement (node matches are separate)


def edge_class(tris):
    owners = {}
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            owners[(min(a, b), max(a, b))] = owners.get((min(a, b), max(a, b)), 0) + 1
    return {e: ("interior" if n == 2 else "boundary") for e, n in owners.items()}


def overcounts(r):
    return r["ratio_sum_NodeVolume_over_area"] > 1 + RATIO_EQ


def judge(res):
    all_names = [n for n in fx.FIXTURES]
    F3_all = all(res[n]["rule_match"]["F3"]["all_nodes_match"] for n in all_names)
    F4_any_obtuse = any(res[n]["rule_match"]["F4"]["all_nodes_match"] for n in all_names
                        if "obtuse" in res[n]["triangle_class"] and overcounts(res[n]))
    ratios = {n: res[n]["ratio_sum_NodeVolume_over_area"] for n in ("T4_mild_obtuse", "T6_T4_mirror", "T7_T4_rot90", "T8_T4_x0.1", "T9_T4_x10")}
    invariant = max(ratios.values()) - min(ratios.values()) <= RATIO_EQ * max(ratios.values())
    H = {}
    H["H1_abs_contribution_overcount"] = CONF if (F3_all and not F4_any_obtuse and invariant) else UNRES
    right_only = [n for n in all_names if set(res[n]["triangle_class"]) <= {"right"}]
    H["H2_right_triangle_degeneracy"] = EXCL if right_only and all(not overcounts(res[n]) for n in right_only) else UNRES
    # interior obtuse evidence: a fixture whose obtuse triangle's NEGATIVE element couple sits on an INTERIOR edge,
    # and which over-counts
    interior_obtuse = []
    for n in all_names:
        r = res[n]
        cls = edge_class(fx.FIXTURES[n]["triangles"])
        neg_interior = [row for row in r["element_level"]["rows"]
                        if row["signed_couple"] < -r["abs_tol"] and cls[(min(row["en0"], row["en1"]), max(row["en0"], row["en1"]))] == "interior"]
        if neg_interior and overcounts(r):
            interior_obtuse.append(n)
    H["H3_boundary_triangles_only"] = EXCL if interior_obtuse else UNRES
    H["H4_interior_obtuse_also"] = CONF if interior_obtuse else UNRES
    delaunay_obtuse = [n for n in ("P5_interior_obtuse_Delaunay", "P6_fan_obtuse_centre") if overcounts(res[n])]
    H["H5_obtuse_without_non_Delaunay"] = CONF if delaunay_obtuse else UNRES
    f32 = all(res[n + "_float32"]["rule_match"]["F3"]["all_nodes_match"] and overcounts(res[n + "_float32"])
              for n in ("T4_mild_obtuse", "T5_strong_obtuse"))
    exact_overcount = all(overcounts(res[n]) for n in ("T4_mild_obtuse", "T5_strong_obtuse"))
    H["H6_float32_primary_cause"] = EXCL if (f32 and exact_overcount) else UNRES
    return H, {"F3_reproduces_all": F3_all, "F4_reproduces_any_overcounting_obtuse": F4_any_obtuse,
               "T4_family_ratios": ratios, "invariant": invariant, "interior_obtuse_fixtures": interior_obtuse,
               "delaunay_obtuse_overcounting": delaunay_obtuse}


if __name__ == "__main__":
    res = json.load(open(os.path.join(HERE, "..", "data", "fixture_results.json"), encoding="utf-8"))
    H, ev = judge(res)
    print(json.dumps({"H": H, "evidence": ev}, indent=1))
    with open(os.path.join(HERE, "..", "data", "judgments.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({"H": H, "evidence": ev}, f, indent=1, sort_keys=True)
