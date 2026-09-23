"""Batch 7H-A Phases B-E on the real L3 mesh, in ONE process / ONE DEVSIM
environment. Stages write their own JSON; a stop condition halts later stages.

L3 = Phase 1's build_raw_or_imported(3) (refine_levels=4), reused read-only.
"""
import hashlib
import json
import os
import sys
import time
import warnings

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")

import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
DATA = os.path.join(HERE, "..", "data")
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7g-delaunay-refinement-spike", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7g-rev1-overlap-flip-validation", "scripts"))
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-22-batch7f-step-junction-root-cause", "scripts"))

import exact_geometry as eg  # noqa: E402
import exact_flip as ef  # noqa: E402
from probe_delaunay_7g import build_raw_or_imported  # noqa: E402  (Phase 1, read-only)
from geometry_checks import local_delaunay_check  # noqa: E402  (Phase 1, read-only)
from geometry_checks_v2 import (corrected_triangle_overlap_check, derive_overlap_area_tolerance,  # noqa: E402
                                method_a_clip_area, method_b_sat_overlap_length)  # (Rev.1, read-only)
from candidate_a_edge_flip_v2 import flip_to_local_delaunay_v2  # noqa: E402  (Rev.1, read-only)
from structured_mesh import import_structured_device  # noqa: E402  (Batch 7F, read-only)

LENGTH_SCALE = 1.0e-4
XJ_UM, BAND_UM, RING_MULT = 0.0, 0.1, 3.0


def dump(name, obj):
    path = os.path.join(DATA, name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=1, default=str, sort_keys=True)
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def stop(msg, payload):
    print("\n!!! STOP CONDITION:", msg)
    dump("STOP.json", {"reason": msg, "payload": payload})
    sys.exit(2)


def method_comparison(points, tris, exact_verdicts):
    lt, at, det = derive_overlap_area_tolerance(points, np.asarray(tris))
    rows = {"methodA": {"FP": 0, "FN": 0, "TP": 0, "TN": 0}, "SAT": {"FP": 0, "FN": 0, "TP": 0, "TN": 0}}
    claimed = []
    for (i, j), v in exact_verdicts.items():
        if v in (eg.DUPLICATE, eg.INVALID):
            continue
        pi, pj = points[tris[i]][:, :2], points[tris[j]][:, :2]
        a_area, _ = method_a_clip_area(pi, pj)
        sat = method_b_sat_overlap_length(pi, pj)
        truth = v == eg.POSITIVE
        for name, says in (("methodA", float(a_area) > at), ("SAT", sat > lt)):
            key = ("TP" if truth else "FP") if says else ("FN" if truth else "TN")
            rows[name][key] += 1
        if float(a_area) > at or sat > lt:
            claimed.append({"pair": (i, j), "exact": v, "methodA_area": float(a_area), "sat_min_overlap": float(sat)})
    return {"tolerance": det, "confusion": rows, "n_pairs_evaluated": sum(rows["SAT"].values()),
            "claimed_overlap_pairs": claimed,
            "claimed_by_exact_verdict": {k: sum(1 for c in claimed if c["exact"] == k) for k in (eg.POSITIVE, eg.TOUCH, eg.DISJOINT)}}


def classify_list(ipts, tris, pair_list):
    out = {eg.POSITIVE: 0, eg.TOUCH: 0, eg.DISJOINT: 0, eg.DUPLICATE: 0, eg.INVALID: 0}
    for i, j in pair_list:
        out[eg.classify_pair(ipts, tris[i], tris[j])] += 1
    return out


def devsim_measure(points_um, tris, name):
    import devsim
    dev, mesh = f"d7h_{name}", f"m7h_{name}"
    region, _, contacts = import_structured_device(devsim, points_um, np.asarray(tris), np.zeros(len(tris), dtype=np.int64),
                                                    dev, mesh, LENGTH_SCALE)
    x = np.array(devsim.get_node_model_values(device=dev, region=region, name="x"))
    y = np.array(devsim.get_node_model_values(device=dev, region=region, name="y"))
    nv = np.array(devsim.get_node_model_values(device=dev, region=region, name="NodeVolume"))
    expect = (points_um * LENGTH_SCALE)  # same float32 product the import helper feeds DEVSIM
    order_identity = len(x) == len(points_um) and bool(np.all(x == expect[:, 0].astype(np.float64))
                                                       and np.all(y == expect[:, 1].astype(np.float64)))
    contact = {}
    for c in contacts:
        elems = devsim.get_element_node_list(device=dev, region=region, contact=c)
        edges = sorted(tuple(sorted(int(v) for v in e)) for e in elems)
        contact[c] = {"node_set": sorted({v for e in edges for v in e}), "edge_set": edges}
    devsim.edge_from_node_model(device=dev, region=region, node_model="x")
    devsim.edge_from_node_model(device=dev, region=region, node_model="y")
    ec = np.array(devsim.get_edge_model_values(device=dev, region=region, name="EdgeCouple"))
    ex0 = np.array(devsim.get_edge_model_values(device=dev, region=region, name="x@n0"))
    ex1 = np.array(devsim.get_edge_model_values(device=dev, region=region, name="x@n1"))
    ey0 = np.array(devsim.get_edge_model_values(device=dev, region=region, name="y@n0"))
    ey1 = np.array(devsim.get_edge_model_values(device=dev, region=region, name="y@n1"))
    devsim.delete_device(device=dev)
    devsim.delete_mesh(mesh=mesh)
    assert dev not in devsim.get_device_list()
    return {"x": x, "y": y, "nv": nv, "order_identity": order_identity, "contact": contact, "contacts": contacts,
            "edgecouple": ec, "edge_mid_x_um": (ex0 + ex1) / 2 / LENGTH_SCALE, "edge_mid_y_um": (ey0 + ey1) / 2 / LENGTH_SCALE,
            "edge_n0_xy": list(zip(ex0, ey0)), "edge_n1_xy": list(zip(ex1, ey1))}


def barycentric_cm2(points_um, tris):
    p = points_um.astype(np.float64)
    bary = np.zeros(len(p))
    total = 0.0
    for t in tris:
        a, b, c = p[t[0]], p[t[1]], p[t[2]]
        area = abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2.0 * LENGTH_SCALE ** 2
        total += area
        for v in t:
            bary[v] += area / 3.0
    return bary, total


def zone(x):
    d = abs(x - XJ_UM)
    return "band" if d < BAND_UM else ("ring" if d < RING_MULT * BAND_UM else "outer")


def main():
    t0 = time.time()
    points, tri0, tags0 = build_raw_or_imported(3)
    points = np.asarray(points)
    tri0 = np.asarray(tri0)
    tags0 = np.asarray(tags0)
    print(f"L3: points={len(points)} dtype={points.dtype} triangles={len(tri0)} tags={sorted(set(tags0.tolist()))}")
    points_sha_start = hashlib.sha256(np.ascontiguousarray(points).tobytes()).hexdigest()
    ipts, K = eg.exact_integer_points(points[:, :2])
    tris_before = [[int(v) for v in t] for t in tri0]

    # ---- Rev.1 reproduction (read-only Rev.1 code, same inputs)
    rev1_before = corrected_triangle_overlap_check(points, tri0, tags0)
    _, rev1_after_tri, rev1_after_tags, rev1_rep = flip_to_local_delaunay_v2(points, tri0, tags0, max_passes=20)
    rev1_after_tri = np.asarray(rev1_after_tri)
    rev1_after = corrected_triangle_overlap_check(points, rev1_after_tri, rev1_after_tags)
    unk_b = [tuple(u["triangles"]) for u in rev1_before["unknown_pairs"]]
    unk_a = [tuple(u["triangles"]) for u in rev1_after["unknown_pairs"]]
    rev1_flips = sum(p.get("n_flips", 0) for p in rev1_rep["passes"])
    print(f"Rev.1 reproduction: unknown before={len(unk_b)} after={len(unk_a)} flips={rev1_flips} term={rev1_rep['terminated']}")

    # ---- Phase B: exact global scans
    scan_b, verd_b = eg.global_exact_scan(ipts, tris_before, K, keep_all=True)
    rev1_after_list = [[int(v) for v in t] for t in rev1_after_tri]
    scan_ra, verd_ra = eg.global_exact_scan(ipts, rev1_after_list, K, keep_all=True)
    print(f"exact before: {scan_b['counts']} pairs={scan_b['n_candidate_pairs']}")
    print(f"exact Rev.1-after: {scan_ra['counts']} pairs={scan_ra['n_candidate_pairs']}")
    unk_b_cls = classify_list(ipts, tris_before, unk_b)
    unk_a_cls = classify_list(ipts, rev1_after_list, unk_a)
    print(f"Rev.1 UNKNOWN before exact: {unk_b_cls}; after exact: {unk_a_cls}")
    mc_b = method_comparison(points, tri0, verd_b)
    mc_a = method_comparison(points, rev1_after_tri, verd_ra)
    print(f"method confusion before: {mc_b['confusion']}  after: {mc_a['confusion']}")
    phase_b = {"L3": {"n_points": len(points), "n_triangles": len(tri0), "dtype": str(points.dtype), "K_power_of_two": K},
               "rev1_reproduction": {"unknown_before": len(unk_b), "unknown_after": len(unk_a), "flips": rev1_flips,
                                     "terminated": rev1_rep["terminated"],
                                     "confirmed_before": rev1_before["n_confirmed_overlaps"],
                                     "confirmed_after": rev1_after["n_confirmed_overlaps"],
                                     "rev1_tolerance": rev1_before["tolerance_detail"]},
               "exact_scan_before": scan_b, "exact_scan_rev1_after": scan_ra,
               "rev1_unknown_before_exact": unk_b_cls, "rev1_unknown_after_exact": unk_a_cls,
               "method_comparison_before": mc_b, "method_comparison_rev1_after": mc_a}
    h_b = dump("phase_b_exact_overlap.json", phase_b)
    if scan_b["counts"][eg.POSITIVE] or scan_b["counts"][eg.DUPLICATE] or scan_b["counts"][eg.INVALID]:
        stop("exact positive overlap / duplicate / invalid in L3 BEFORE flip", scan_b["positives"][:50])
    if scan_ra["counts"][eg.POSITIVE]:
        print("NOTE: Rev.1 AFTER mesh has exact positive overlap:", scan_ra["positives"][:10])

    # ---- Phase C: exact-safe Candidate A
    owners, bset, iset, _ = eg.edge_sets(tris_before, tags0)
    protected = frozenset(e for e, _ in bset) | frozenset(e for e, _ in iset)
    exact_viol_before = ef.exact_violations(ipts, tris_before, [int(t) for t in tags0], protected)
    tris_after, tags_after, rep = ef.exact_flip(points[:, :2], tris_before, tags0, protected=protected, max_passes=50)
    print(f"exact flip: term={rep['terminated']} flips={len(rep['history'])} passes={[(p['n_violations_before'], p['n_flips']) for p in rep['passes']]}")
    if rep["terminated"] == "OSCILLATION_DETECTED":
        stop("flip oscillation", rep["history"][-5:])
    scan_after, _ = eg.global_exact_scan(ipts, tris_after, K)
    print(f"exact after (exact-safe): {scan_after['counts']}")
    inv_b = eg.mesh_exact_invariants(ipts, tris_before, tags0)
    inv_a = eg.mesh_exact_invariants(ipts, tris_after, tags_after)
    geom_inv = {
        "point_bytes_equal": hashlib.sha256(np.ascontiguousarray(points).tobytes()).hexdigest() == points_sha_start,
        "points_sha256": points_sha_start,
        "triangle_count": (inv_b["n_triangles"], inv_a["n_triangles"]),
        "tag_counter_equal": inv_b["tag_counter"] == inv_a["tag_counter"], "tag_counter": dict(inv_a["tag_counter"]),
        "boundary_edge_set_equal": inv_b["boundary_edge_set"] == inv_a["boundary_edge_set"],
        "n_boundary_edges": len(inv_a["boundary_edge_set"]),
        "interface_edge_set_equal": inv_b["interface_edge_set"] == inv_a["interface_edge_set"],
        "n_interface_edges": len(inv_a["interface_edge_set"]),
        "non_manifold_equal": inv_b["non_manifold_edge_set"] == inv_a["non_manifold_edge_set"],
        "n_non_manifold": (len(inv_b["non_manifold_edge_set"]), len(inv_a["non_manifold_edge_set"])),
        "duplicate_set_equal": inv_b["duplicate_triangle_set"] == inv_a["duplicate_triangle_set"],
        "n_duplicate": (len(inv_b["duplicate_triangle_set"]), len(inv_a["duplicate_triangle_set"])),
        "zero_area": (len(inv_b["zero_area_set"]), len(inv_a["zero_area_set"])),
        "inverted": (len(inv_b["inverted_set"]), len(inv_a["inverted_set"])),
        "total_area2_int_equal": inv_b["total_area2_int"] == inv_a["total_area2_int"],
        "total_area_exact_um2": str(eg.Fraction(inv_a["total_area2_int"], 2 * (1 << (2 * K)))),
        "exact_overlap_set_before": [p["pair"] for p in scan_b["positives"]],
        "exact_overlap_set_after": [p["pair"] for p in scan_after["positives"]],
        "exact_overlap_counts_after": scan_after["counts"],
    }
    viol_float_b = sum(1 for e in local_delaunay_check(points, tri0, tags0)[0] if e["angle_sum_violation"])
    viol_float_a = sum(1 for e in local_delaunay_check(points, np.asarray(tris_after), np.asarray(tags_after))[0] if e["angle_sum_violation"])
    exact_viol_after = ef.exact_violations(ipts, tris_after, tags_after, protected)
    same_as_rev1 = sorted(tuple(sorted(t)) for t in tris_after) == sorted(tuple(sorted(t)) for t in rev1_after_list)
    reflips = [h for h in rep["history"] if h["reflip_to_earlier_diagonal"]]
    ext_increase = [h for h in rep["history"] if h["external_positive_after"] > h["external_positive_before"]]
    phase_c = {"terminated": rep["terminated"], "passes": rep["passes"], "n_flips": len(rep["history"]),
               "history": rep["history"], "n_reflips": len(reflips), "n_external_increase": len(ext_increase),
               "exact_violations_before": len(exact_viol_before), "exact_violations_after": len(exact_viol_after),
               "rev1_float_angle_violations_before": viol_float_b, "rev1_float_angle_violations_after": viol_float_a,
               "same_triangle_set_as_rev1_after": same_as_rev1, "exact_scan_after": scan_after,
               "geometry_invariants": geom_inv, "n_protected_edges": len(protected)}
    h_c = dump("phase_c_exact_flip.json", phase_c)
    print(f"violations exact {len(exact_viol_before)}->{len(exact_viol_after)}, float {viol_float_b}->{viol_float_a}; "
          f"same_as_rev1={same_as_rev1}; invariants={ {k: v for k, v in geom_inv.items() if k.endswith('_equal')} }")
    if scan_after["counts"][eg.POSITIVE] or scan_after["counts"][eg.DUPLICATE] or scan_after["counts"][eg.INVALID]:
        stop("exact positive overlap / duplicate / invalid AFTER exact-safe flip", scan_after["positives"][:50])
    bad = [k for k, v in geom_inv.items() if k.endswith("_equal") and v is not True]
    if bad or inv_a["n_triangles"] != inv_b["n_triangles"]:
        stop(f"geometry invariant changed: {bad}", geom_inv)

    # ---- Phase D: same-run NodeVolume, before vs after (and Rev.1-after as a cross-check)
    import devsim
    pts_um = points[:, :2]
    mb = devsim_measure(pts_um, tris_before, "before")
    ma = devsim_measure(pts_um, tris_after, "after")
    bary_b, area_b = barycentric_cm2(pts_um, tris_before)
    bary_a, area_a = barycentric_cm2(pts_um, tris_after)
    contacts_equal = {c: {"node_set_equal": mb["contact"][c]["node_set"] == ma["contact"][c]["node_set"],
                          "edge_set_equal": mb["contact"][c]["edge_set"] == ma["contact"][c]["edge_set"],
                          "n_nodes": len(ma["contact"][c]["node_set"]), "n_edges": len(ma["contact"][c]["edge_set"])}
                      for c in mb["contacts"]}
    rel_b = (mb["nv"].sum() - area_b) / area_b
    rel_a = (ma["nv"].sum() - area_a) / area_a
    phase_d = {"devsim_version": devsim.__version__ if hasattr(devsim, "__version__") else None,
               "n_nodes": (len(mb["nv"]), len(ma["nv"])), "n_triangles": (len(tris_before), len(tris_after)),
               "node_order_identity": (mb["order_identity"], ma["order_identity"]),
               "before": {"sum_NodeVolume_cm2": float(mb["nv"].sum()), "triangulated_area_cm2": area_b, "relative_error": float(rel_b)},
               "after": {"sum_NodeVolume_cm2": float(ma["nv"].sum()), "triangulated_area_cm2": area_a, "relative_error": float(rel_a)},
               "absolute_reduction_of_relative_error": float(rel_b - rel_a),
               "relative_reduction_of_relative_error": float((rel_b - rel_a) / rel_b) if rel_b else None,
               "excess_cm2": (float(mb["nv"].sum() - area_b), float(ma["nv"].sum() - area_a)),
               "contacts": contacts_equal,
               "exact_overlap_certification_sha256": {"phase_b_exact_overlap.json": h_b, "phase_c_exact_flip.json": h_c}}
    print(f"NodeVolume same-run: before rel={rel_b:.6f} after rel={rel_a:.6f}; contacts={contacts_equal}; order_identity={phase_d['node_order_identity']}")
    dump("phase_d_nodevolume_same_run.json", phase_d)
    if not all(v["node_set_equal"] and v["edge_set_equal"] for v in contacts_equal.values()):
        stop("DEVSIM contact node/edge set changed", contacts_equal)
    if not (rel_a < rel_b):
        stop("same-run NodeVolume improvement not reproduced", phase_d)
    if not (mb["order_identity"] and ma["order_identity"]):
        stop("DEVSIM node order != mesh point order; per-node residual mapping not proven", phase_d["node_order_identity"])

    # ---- Phase E: residual location only (after-flip mesh)
    resid = ma["nv"] - bary_a
    owners_a, bset_a, _, _ = eg.edge_sets(tris_after, tags_after)
    boundary_nodes = {v for (e, _) in bset_a for v in e}
    tri_obtuse, tri_right, tri_acute, cc_in, cc_on, cc_out = [], 0, 0, 0, 0, 0
    node_obtuse = np.zeros(len(points), dtype=int)
    node_ccout = np.zeros(len(points), dtype=int)
    for ti, t in enumerate(tris_after):
        P3 = [ipts[v] for v in t]
        dots = []
        for k in range(3):
            A, B, C = P3[k], P3[(k + 1) % 3], P3[(k + 2) % 3]
            dots.append((B[0] - A[0]) * (C[0] - A[0]) + (B[1] - A[1]) * (C[1] - A[1]))
        # exact circumcenter via Fractions, located by exact barycentric signs
        (ax, ay), (bx, by), (cx, cy) = P3
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        ux = eg.Fraction((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by), d)
        uy = eg.Fraction((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax), d)
        U = (ux, uy)
        s = [((P3[(k + 1) % 3][0] - P3[k][0]) * (U[1] - P3[k][1]) - (P3[(k + 1) % 3][1] - P3[k][1]) * (U[0] - P3[k][0]))
             * (1 if eg.orient(*P3) > 0 else -1) for k in range(3)]
        loc = "inside" if all(v > 0 for v in s) else ("on" if min(s) == 0 and all(v >= 0 for v in s) else "outside")
        cc_in += loc == "inside"; cc_on += loc == "on"; cc_out += loc == "outside"
        if min(dots) < 0:
            tri_obtuse.append(ti)
            for v in t:
                node_obtuse[v] += 1
        elif min(dots) == 0:
            tri_right += 1
        else:
            tri_acute += 1
        if loc == "outside":
            for v in t:
                node_ccout[v] += 1
    node_constrained = np.zeros(len(points), dtype=int)
    for (e, _) in bset_a:
        node_constrained[e[0]] += 1
        node_constrained[e[1]] += 1
    boundary_neg_cot = 0
    boundary_neg_cot_mid = []
    for e, o in owners_a.items():
        if len(o) == 1:
            t = tris_after[o[0]]
            c = [v for v in t if v not in e][0]
            A, B, C = ipts[e[0]], ipts[e[1]], ipts[c]
            if (A[0] - C[0]) * (B[0] - C[0]) + (A[1] - C[1]) * (B[1] - C[1]) < 0:
                boundary_neg_cot += 1
                boundary_neg_cot_mid.append(((float(points[e[0]][0]) + float(points[e[1]][0])) / 2,
                                             (float(points[e[0]][1]) + float(points[e[1]][1])) / 2))
    ec = ma["edgecouple"]
    neg_idx = np.where(ec < 0)[0]
    zero_idx = np.where(ec == 0)[0]
    top = np.argsort(-np.abs(resid))[:30]
    top30 = [{"node": int(i), "x_um": float(points[i][0]), "y_um": float(points[i][1]), "zone": zone(float(points[i][0])),
              "boundary_node": int(i) in boundary_nodes, "residual_cm2": float(resid[i]),
              "NodeVolume_cm2": float(ma["nv"][i]), "barycentric_cm2": float(bary_a[i]),
              "incident_obtuse_tri": int(node_obtuse[i]), "incident_circumcenter_outside_tri": int(node_ccout[i]),
              "incident_constrained_edges": int(node_constrained[i])} for i in top]
    by_zone = {z: 0.0 for z in ("band", "ring", "outer")}
    by_boundary = {"boundary": 0.0, "interior": 0.0}
    for i, r in enumerate(resid):
        by_zone[zone(float(points[i][0]))] += float(r)
        by_boundary["boundary" if i in boundary_nodes else "interior"] += float(r)
    phase_e = {"residual_sum_cm2": float(resid.sum()), "positive_sum_cm2": float(resid[resid > 0].sum()),
               "negative_sum_cm2": float(resid[resid < 0].sum()), "residual_by_zone_cm2": by_zone,
               "residual_by_boundary_cm2": by_boundary, "top30_abs_residual_nodes": top30,
               "top30_boundary_count": sum(1 for r in top30 if r["boundary_node"]),
               "triangles": {"acute": tri_acute, "right": tri_right, "obtuse": len(tri_obtuse)},
               "circumcenter": {"inside": cc_in, "on_edge": cc_on, "outside": cc_out},
               "interior_unconstrained_exact_delaunay_violations": len(exact_viol_after),
               "boundary_edges_one_sided_negative_cotangent": boundary_neg_cot,
               "boundary_negative_cot_edge_midpoints_um": boundary_neg_cot_mid[:60],
               "material_interface_negative_weight_candidates": 0,
               "material_interface_note": "L3 is single-material (tag 10 only): zero material-interface edges exist",
               "devsim_EdgeCouple": {"n_edges": int(len(ec)), "negative": int(len(neg_idx)), "zero": int(len(zero_idx)),
                                     "positive": int((ec > 0).sum()),
                                     "negative_locations_um": [(float(ma["edge_mid_x_um"][k]), float(ma["edge_mid_y_um"][k]),
                                                                float(ec[k])) for k in neg_idx[:80]],
                                     "negative_by_zone": {z: int(sum(1 for k in neg_idx if zone(float(ma["edge_mid_x_um"][k])) == z))
                                                          for z in ("band", "ring", "outer")}},
               "devsim_EdgeCouple_before": {"negative": int((mb["edgecouple"] < 0).sum()), "zero": int((mb["edgecouple"] == 0).sum()),
                                            "positive": int((mb["edgecouple"] > 0).sum())}}
    dump("phase_e_residual_location.json", phase_e)
    print(f"residual sum={phase_e['residual_sum_cm2']:.4e} pos={phase_e['positive_sum_cm2']:.4e} neg={phase_e['negative_sum_cm2']:.4e}")
    print(f"by zone={by_zone} by boundary={by_boundary} top30 boundary={phase_e['top30_boundary_count']}")
    print(f"triangles={phase_e['triangles']} circumcenter={phase_e['circumcenter']} boundary_neg_cot={boundary_neg_cot}")
    print(f"EdgeCouple after={ {k: v for k, v in phase_e['devsim_EdgeCouple'].items() if k in ('n_edges','negative','zero','positive','negative_by_zone')} } before={phase_e['devsim_EdgeCouple_before']}")
    print(f"total wall {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
