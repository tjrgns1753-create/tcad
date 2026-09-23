"""Batch 7H-C section 9: regenerate the 7H-A L3 before / exact-safe-after
meshes read-only (Phase 1 build_raw_or_imported(3) + 7H-A exact_flip),
verify against 7H-A's stored point hash and flip history, export to
data/l3_meshes.json for dev_run.py."""
import hashlib
import json
import os
import sys
import warnings

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
warnings.simplefilter("ignore")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
A7H = os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7h-exact-flip-certification")
for p in (ROOT, os.path.join(ROOT, "docs", "audits", "2026-09-23-batch7g-delaunay-refinement-spike", "scripts"), os.path.join(A7H, "scripts")):
    sys.path.insert(0, p)
from probe_delaunay_7g import build_raw_or_imported  # noqa: E402
import exact_geometry as eg  # noqa: E402
import exact_flip as ef  # noqa: E402


def main():
    points, tri0, tags0 = build_raw_or_imported(3)
    points = np.asarray(points)
    sha = hashlib.sha256(np.ascontiguousarray(points).tobytes()).hexdigest()
    tb = [[int(v) for v in t] for t in tri0]
    _, bset, iset, _ = eg.edge_sets(tb, tags0)
    prot = frozenset(e for e, _ in bset) | frozenset(e for e, _ in iset)
    ta, _, rep = ef.exact_flip(points[:, :2], tb, tags0, protected=prot, max_passes=50)
    stored = json.load(open(os.path.join(A7H, "data", "phase_c_exact_flip.json"), encoding="utf-8"))
    same = [(h["quad"], list(h["old_diagonal"]), list(h["new_diagonal"])) for h in rep["history"]] == \
           [(h["quad"], list(h["old_diagonal"]), list(h["new_diagonal"])) for h in stored["history"]]
    ok = sha == stored["geometry_invariants"]["points_sha256"] and same
    print("points sha", sha, "matches 7H-A:", sha == stored["geometry_invariants"]["points_sha256"], "history identical:", same)
    if not ok:
        sys.exit(2)
    P = points[:, :2].astype(np.float64)
    out = {"points_sha256_7HA": sha, "points_um": P.tolist(), "L3_before": tb, "L3_after": ta,
           "extent_um": [float(P[:, 0].min()), float(P[:, 0].max()), float(P[:, 1].min()), float(P[:, 1].max())]}
    with open(os.path.join(HERE, "..", "data", "l3_meshes.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f)
    print("extent_um", out["extent_um"])


if __name__ == "__main__":
    main()
