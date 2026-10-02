"""Pure geometry only: reuse E6G builder, no backend imports or solves."""
import hashlib
import importlib.util
import json
import sys
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path.cwd()
AUDIT = ROOT / "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency"
sys.path.insert(0, str(AUDIT / "scripts"))
import e6m_metrics as M


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    R = load("e6g_pure_builder", ROOT / "tcad/device/devsim/mesh_refine.py")
    C = load("e6h_exact_geometry", ROOT / "docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/scripts/conformity_e6h.py")
    old = np.load(AUDIT / "data/remote_run_36904995835/remote-run-32/outputs/e6m_out/arrays.npz")
    ref = np.load(ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out/states.npz")
    out = {"design_rule_sha256": hashlib.sha256((Path(__file__).parent / "GEOMETRY_DESIGN_RULE.md").read_bytes()).hexdigest(),
           "request": {"centers_um": [0.0], "half_widths_um": [0.1]}, "levels": {}}
    for lv in M.LEVELS:
        p, t = old[lv + "__points_um"], old[lv + "__triangles"]
        tags = np.zeros(len(t), dtype=np.int32)
        rec = out["levels"][lv] = {}
        try:
            R.structured_lateral_refine(p, t, tags, [0.0], [0.1])
        except (R.StructuredRemeshAborted, R.StructuredRemeshUnsupported) as exc:
            rec["original_candidate"] = {"reason": exc.reason, "detail": str(exc)}
        else:
            raise AssertionError("the formerly blocked input unexpectedly succeeded")
        xs, ys, _, _ = R.structured_grid_of(p, t, tags)
        leaves = R._strip_depths(xs, [0.0], [0.1], 400000)
        bounds, template_count, transitions = [], 0, []
        for k, (a, b, d, _) in enumerate(leaves):
            fl = k > 0 and leaves[k - 1][2] == d + 1
            fr = k + 1 < len(leaves) and leaves[k + 1][2] == d + 1
            template_count += (4 if fl and fr else 3 if fl or fr else 2) * 2**d
            if fl != fr:
                bounds.append(2 * (Fraction(b) - Fraction(a)) * 2**d)
                transitions.append({"x_min_um": a, "x_max_um": b, "depth": d})
        assert bounds, "a non-transition candidate is outside this experiment"
        bound = min(bounds)
        ny = 1
        height = Fraction(float(M.H_UM))
        while height / ny > bound:
            ny *= 2
        rec.update(base_rows=ny, base_row_height_um=float(height / ny), exact_aspect_base_height_bound_um=float(bound),
                   planned_triangles=ny * template_count, transition_strips=transitions)
        if ny * template_count > 400000:
            rec["candidate_status"] = "RESOURCE_CAP"
            continue
        x1 = M.e6k_snapshot(ref, lv, "rev", 0.0)["x"]
        with patch.object(M, "Y_LINES_UM", np.linspace(-M.H_UM, 0.0, ny + 1).tolist()):
            pp, tt = M.build_mesh(x1)
        assert np.array_equal(np.unique(pp[:, 0]), xs), "x geometry changed"
        try:
            pp, tt, gg, report = R.structured_lateral_refine(pp, tt, np.zeros(len(tt), dtype=np.int32), [0.0], [0.1])
        except (R.StructuredRemeshAborted, R.StructuredRemeshUnsupported) as exc:
            rec["candidate_status"] = exc.reason
            rec["detail"] = str(exc)
            continue
        coords = C._dyadic_ints(pp[:, :2].reshape(-1).tolist())
        xy = list(zip(coords[0::2], coords[1::2]))
        obtuse = 0
        for tri in tt.tolist():
            q = [xy[i] for i in tri]
            for i in range(3):
                a, b, c = q[i], q[(i + 1) % 3], q[(i + 2) % 3]
                obtuse += (b[0] - a[0]) * (c[0] - a[0]) + (b[1] - a[1]) * (c[1] - a[1]) < 0
        exact = C.check_conformity(pp, tt)
        rec.update(nodes=len(pp), triangles=len(tt), exact_obtuse_angles=obtuse, conformity=exact,
                   numeric_geometry=M.geometry_checks(pp, tt), builder_report=report)
        assert len(tt) == rec["planned_triangles"]
        assert np.array_equal(np.unique(gg), [0])
        assert np.min(pp[:, 0]) == -20.0 and np.max(pp[:, 0]) == 20.0
        assert np.min(pp[:, 1]) == -0.1 and np.max(pp[:, 1]) == 0.0
        assert exact["pass"] and obtuse == 0
        rec["candidate_status"] = "GEOMETRY_PREFLIGHT_PASS_ONLY"
        print(lv, ny, len(pp), len(tt), "geometry PASS", flush=True)
    out["engine_imports"] = len([n for n in sys.modules if n in ("devsim", "viennaps")])
    out["real_solves"] = 0
    assert out["engine_imports"] == 0
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
