"""Batch 3A section 10: probes of the CURRENT analyzer (tcad/mesh/etch_diagnostics.py). Reproduce-and-report only;
nothing in tcad/ or tests/ is modified. (Private helpers `_reach`, `_Ctx.sections` are CALLED to isolate one interval.)

Probe R  -- `_reach()` describes itself as judging the "whole measured run" but inspects ONE scanline (the midpoint)
            per common interval. Can that return a wrong reach?
            R-a  whole-run sanity cases (flush / exposed / mixed)
            R-b  one isolated interval, valid non-overlapping geometry: overlayer bottom and Si top are both linear
                 across the interval, so a random sweep compares the midpoint verdict with the exact end-gap verdict
            R-c  one isolated interval, INVALID (overlapping) geometry, to show what midpoint-only sees
Probe C  -- can a "paired flat run" be assembled from DIFFERENT triangle components that merely share a top height?
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_common as ac
from audit_common import ed, np

WINDOW = (-1.0, 1.0)


def layer(mat, xs, tops, bottoms):
    out = []
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        b0, b1, t0, t1 = bottoms[i], bottoms[i + 1], tops[i], tops[i + 1]
        out.append((mat, ((x0, b0), (x1, b1), (x1, t1))))
        out.append((mat, ((x0, b0), (x1, t1), (x0, t0))))
    return out


def mesh(parts):
    """Vertices with identical coordinates share one index (a conforming mesh), so triangle adjacency is meaningful."""
    index, pts, tri = {}, [], []
    for _, t in parts:
        ids = []
        for p in t:
            key = (float(p[0]), float(p[1]))
            if key not in index:
                index[key] = len(pts)
                pts.append(key)
            ids.append(index[key])
        tri.append(ids)
    return ed.TaggedMesh(np.array(pts, dtype=np.float64), np.array(tri, dtype=np.int64), tuple(m for m, _ in parts))


def analyze(pre, post, material="Si", window=WINDOW):
    return {r.material: r for r in ed.analyze_window(pre, post, window)}[material]


def brief(r):
    return {"status": r.status, "displacement_um": r.displacement_um, "run_x_um": r.run_x_um,
            "n_intervals": r.n_intervals, "reach": r.reach, "reason": r.reason}


XS = [-1.0, -0.5, 0.0, 0.5, 1.0]
si_flat = layer("Si", XS, [0.0] * 5, [-1.0] * 5)
pre = mesh(si_flat)
EPS = ed._geometry_eps((pre,), WINDOW)
out = {"geometry_eps_um_at_this_scale": EPS}

# ------------------------------------------------------------------ R-a: whole-run sanity
Ra = {"flush_overlayer": brief(analyze(pre, mesh(si_flat + layer("SiO2", XS, [0.2] * 5, [0.0] * 5)))),
      "exposed": brief(analyze(pre, mesh(si_flat))),
      "flush_left_half_only": brief(analyze(pre, mesh(si_flat + layer("SiO2", [-1.0, -0.5, 0.0], [0.2] * 3, [0.0] * 3))))}
out["R_a_whole_run_sanity"] = Ra


# ------------------------------------------------------------------ R-b / R-c: one isolated interval [a, b]
def reach_one_interval(si_top_a, si_top_b, ov_bottom_a, ov_bottom_b, a=0.0, b=1.0):
    si = layer("Si", [a, b], [si_top_a, si_top_b], [-1.0, -1.0])
    ov = layer("SiO2", [a, b], [0.5, 0.5], [ov_bottom_a, ov_bottom_b])
    post = mesh(si + ov)
    win = (a, b)
    e = ed._geometry_eps((post,), win)
    cpre, cpost = ed._Ctx(mesh(si), a, b, e), ed._Ctx(post, a, b, e)
    secs = [(cpre.sections(a, b), cpost.sections(a, b))]
    return ed._reach("Si", secs, 0, 0, e), e


rng = np.random.default_rng(20260921)          # fixed seed: the sweep is reproducible
rows = []
for _ in range(4000):
    g0, g1 = (0.0 if rng.random() < 0.2 else float(10 ** rng.uniform(-9, -1)) for _ in range(2))
    got, e = reach_one_interval(0.0, 0.0, g0, g1)
    # exact verdict from the exact end gaps (linear edges): flush over the whole interval iff both end gaps <= eps
    exact = "overlain" if max(g0, g1) <= e else ("cannot_be_inferred")
    rows.append((g0, g1, got, exact, e))
mism = [r for r in rows if r[2] != r[3]]
Rb = {"n_random_valid_cases": len(rows), "n_mismatch_midpoint_vs_exact_end_gaps": len(mism),
      "mismatch_examples": [{"gap_a": r[0], "gap_b": r[1], "midpoint_rule": r[2], "exact_end_gaps": r[3],
                             "gap_a_over_eps": r[0] / r[4], "gap_b_over_eps": r[1] / r[4]} for r in mism[:8]],
      "max_gap_over_eps_among_mismatches": max((max(r[0], r[1]) / r[4] for r in mism), default=None),
      "min_gap_over_eps_among_mismatches": min((max(r[0], r[1]) / r[4] for r in mism), default=None)}
out["R_b_valid_geometry_random_sweep"] = Rb

got_c, e_c = reach_one_interval(0.0, 0.0008, 0.0004, 0.0004)      # Si top rises 0 -> 0.0008 (within 0.001 tolerance);
out["R_c_INVALID_overlap_single_interval"] = {                      # overlayer bottom flat 0.0004: penetrates Si on the right half
    "midpoint_only_reach": got_c,
    "exact": "overlayer penetrates Si for x > 0.5 (bottom 0.0004 < Si top up to 0.0008): geometry is overlapping/invalid",
    "note": "the analyzer has no overlap check; a ViennaLS material export cannot produce overlapping material triangles"}

# ------------------------------------------------------------------ Probe C: component switching
xs = [-1.0, -0.5, 0.0, 0.3, 0.6, 1.0]
pre_c = mesh(layer("Si", xs, [0.0] * 6, [-1.0] * 6))


def two_slabs(gap):
    a = layer("Si", [-1.0, -0.5, 0.0, 0.3], [-0.15] * 4, [-1.0] * 4)
    b = layer("Si", [0.3 + gap, 0.6, 1.0], [-0.15] * 3, [-0.6] * 3)        # a different body (different bottom)
    return mesh(a + b)


def n_components(m, material="Si"):
    idx = [k for k in range(len(m.triangles)) if m.materials[k] == material]
    return len(ac._components(idx, m.triangles))


C = {}
for label, gap in (("touching_gap_0", 0.0), ("hairline_gap_0.5eps", 0.5 * EPS), ("hairline_gap_2eps", 2.0 * EPS),
                   ("gap_1e-4", 1e-4)):
    post_c = two_slabs(gap)
    C[label] = {"gap_um": gap, "gap_over_eps": gap / EPS,
                "triangle_adjacency_components_of_Si_in_post": n_components(post_c), **brief(analyze(pre_c, post_c))}
out["C_component_switching"] = C
out["note"] = ("components counted by shared-edge adjacency (vertex indices) on the synthetic mesh; at gap 0 the two "
               "slabs touch geometrically but share no vertex index, so adjacency reports 2 components")
dest = ac.AUDIT / "raw" / "synthetic_analyzer_probes.json"
dest.parent.mkdir(exist_ok=True)
dest.write_bytes(json.dumps(out, indent=1, default=float).encode("utf-8"))      # LF, not Windows text-mode CRLF
print(json.dumps(out, indent=1, default=float))
