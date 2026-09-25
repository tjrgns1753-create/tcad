"""Batch 7H-E2 verdict rules (PLAN sections 2, 5, 6, 7). Pure Python; tested on synthetic records locally."""


def within(rec):
    r, t = rec.get("ratio"), rec.get("tau")
    return None if r is None or t is None else abs(r - 1.0) <= t


def identities_ok(rec):
    i = rec.get("identity", {})
    return bool(i.get("I1")) and bool(i.get("I2"))


def cross_stage(stages):
    """I4: exact area, contact node sets, tags and regions equal to S0 at every stage."""
    s0 = stages[0]
    bad = []
    for s in stages:
        for key in ("exact_area_cm2", "contact_nodes_sha256"):
            if s.get(key) != s0.get(key):
                bad.append({"stage": s["k"], "field": key})
        if not s.get("tags_all_si") or s.get("regions") != ["Si"]:
            bad.append({"stage": s["k"], "field": "tags/regions"})
    return {"ok": not bad, "differences": bad}


def decide(stages, i3_ok, c_rt, c_ccw):
    """stages: list of per-stage records (k = 0..4, in order). c_rt / c_ccw: control records or None."""
    out = {"withheld": [], "verdicts": [], "candidate_allowed": False}
    if not i3_ok:
        out["withheld"].append("I3_FAIL: S4 does not reproduce the E1 production mesh; no causal verdict")
        out["verdicts"].append("INCONCLUSIVE")
        return out
    i4 = cross_stage(stages)
    out["I4"] = i4
    w = [within(s) for s in stages]
    out["within_tau"] = w
    if w[0] is False:
        out["verdicts"].append("PRE_EXISTING")
    first = next((k for k, v in enumerate(w) if v is False), None)
    out["first_outside_tau"] = first
    if first is None:
        out["verdicts"].append("NO_STAGE_OUTSIDE_TAU")
    elif first > 0:
        pair = [stages[first - 1], stages[first]]
        if all(identities_ok(s) for s in pair) and i4["ok"] and all(v is True for v in w[:first]):
            out["verdicts"].append(f"FIRST_BAD_STAGE={first}")
            out["first_bad_stage"] = first
        else:
            out["withheld"].append(f"FIRST_BAD_STAGE withheld: identities or I4 fail for S{first - 1}/S{first}")
    orient = None
    if c_rt is None or not c_rt.get("reproduces_S4"):
        out["withheld"].append("C_rt does not reproduce S4: orientation and candidate comparisons INCONCLUSIVE")
    elif c_ccw is not None:
        if c_ccw.get("n_nodes_beyond_budget_vs_rt", 1) > 0:
            orient = "ORIENTATION_EFFECT"
            out["verdicts"].append("ORIENTATION_EFFECT")
            if within(c_ccw):
                out["verdicts"].append("ORIENTATION_CAUSE")
        else:
            orient = "NO_ORIENTATION_EFFECT"
            out["verdicts"].append("NO_ORIENTATION_EFFECT")
    fb = out.get("first_bad_stage")
    if fb is not None and orient == "NO_ORIENTATION_EFFECT":
        shape = all(stages[k].get("f3_all_nodes_within_budget") and stages[k].get("excess_explained_by_F3_within_tau")
                    and stages[k].get("f3_excess_nodes_all_obtuse_vertices") for k in (fb, len(stages) - 1))
        if shape:
            out["verdicts"].append("SHAPE_CAUSE")
    if not any(v.startswith("FIRST_BAD_STAGE") or v in ("PRE_EXISTING", "SHAPE_CAUSE", "ORIENTATION_CAUSE")
               for v in out["verdicts"]):
        out["verdicts"].append("INCONCLUSIVE")
    out["candidate_allowed"] = fb is not None and orient == "NO_ORIENTATION_EFFECT" and "SHAPE_CAUSE" in out["verdicts"]
    return out


def candidate_verdict(c):
    """PLAN section 7 (a)-(d); every item must be True."""
    keys = ("points_identical", "boundary_edges_equal", "interface_edges_equal", "x0_edges_equal", "tag_counter_equal",
            "exact_area_equal", "no_duplicate_zero_nonmanifold", "no_positive_overlap", "flip_terminated_clean",
            "contacts_equal", "regions_equal", "ratio_within_tau", "inventory_donor_within_tau", "inventory_acceptor_within_tau")
    failed = [k for k in keys if c.get(k) is not True]
    return {"verdict": "CANDIDATE_PASSES_AUDIT_CHECKS" if not failed else "CANDIDATE_REJECTED", "failed": failed}
