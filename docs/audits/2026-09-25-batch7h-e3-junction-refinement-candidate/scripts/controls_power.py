"""Batch 7H-E3: corrected, POWER-CHECKED control logic (fixes the 7H-E2 flaw documented in
../../2026-09-25-batch7h-e2-nodevolume-first-bad-stage/ERRATUM.md section 1: a control that changes 0 triangles cannot
license a "no effect" / cause-exclusion verdict, because comparing an unmodified input to itself is a tautology, not an
experiment). Pure Python; E2's own files (verdicts_e2.py, trace_refine_e2.py, its PLAN/results) are NOT modified.

A control record must report `n_changed` (how many geometric elements the manipulation actually altered) alongside its
comparison result. `powered_verdict()` below refuses to return a cause-exclusion / no-effect verdict whenever
n_changed == 0, returning CONTROL_NOT_POWERED / ORIENTATION_INCONCLUSIVE instead -- mechanically, not by convention."""


def reverse_all_windings(triangles):
    """A POWERED orientation manipulation (unlike 7H-E2's ccw_only, which only touched already-negative-oriented
    triangles and was therefore a no-op on an already-all-CCW mesh): swap vertices 1 and 2 of EVERY triangle,
    unconditionally. n_changed == len(triangles) always, by construction -- this control cannot be accidentally
    unpowered the way ccw_only was."""
    out = [(t[0], t[2], t[1]) for t in triangles]
    return out, len(triangles)  # (reversed_triangles, n_changed) -- n_changed is exact, not measured after the fact


def powered_verdict(label, n_changed, n_total, comparison_equal_within_budget, effect_metric=None):
    """label: name of the property being controlled for (e.g. "orientation"). n_changed: how many elements the
    manipulation actually altered (0 means an unpowered / null control). n_total: size of the input the manipulation
    was applied to, for reporting the changed fraction. comparison_equal_within_budget: whether the two DEVSIM
    readbacks agreed within the pre-registered per-node budget b_i / tau. Returns one of:
      CONTROL_NOT_POWERED   -- n_changed == 0; no verdict about `label` can be drawn (this is what 7H-E2's C_ccw was).
      {LABEL}_NO_EFFECT     -- powered (n_changed > 0) and the two readbacks agreed within budget.
      {LABEL}_EFFECT        -- powered and they disagreed.
    """
    up = label.upper()
    if n_changed == 0:
        return {"verdict": "CONTROL_NOT_POWERED", "label": label, "n_changed": 0, "n_total": n_total,
                "reason": f"the {label} manipulation altered 0 of {n_total} elements; "
                          "comparing an unmodified input to itself cannot exclude a cause"}
    return {"verdict": f"{up}_NO_EFFECT" if comparison_equal_within_budget else f"{up}_EFFECT",
            "label": label, "n_changed": n_changed, "n_total": n_total, "changed_fraction": n_changed / n_total,
            "effect_metric": effect_metric}
