"""Batch 7H-E6F small demonstrations cited in REPORT section 2 (pure): (1) blue locality on exact squares vs cells of height 1+2^-20;
(2) B_raw exact cell widths; (3) sweep (prototype) vs queue (refine_blue) closure on B_raw 1e16 pass 0 -- order dependence."""
import os
import sys
from fractions import Fraction as F

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import meshio  # noqa: E402
import alt_rgb_e6f as proto  # noqa: E402
import refine_blue as rb  # noqa: E402
import eval2_e6f as ev  # noqa: E402

for dy in (1.0, 1.0 + 2 ** -20):
    P, T, G = ev.grid(20, 20, 1.0)
    P[:, 1] *= dy
    marked = [bool(abs(c[0] - 10) < 1) for c in P[T].mean(1)]
    st = {}
    rb.refine_once_blue(P, T, G, marked, stats=st)
    print(f"20x20 grid, cell height {dy!r}: " + str({k: st[k] for k in ("red", "green", "blue", "untouched", "output_triangles")}))
m = meshio.read(os.path.join(ROOT, "docs/audits/2026-09-30-batch7h-e6e-r1-gate-uncertainty/data/remote_run_36690617723/outputs/e6e_r1_out/B_raw.vtu"))
xs = sorted(set(F(float(v)) for v in m.points[:, 0]))
w = sorted(set(xs[i + 1] - xs[i] for i in range(len(xs) - 1)))
print("B_raw distinct exact cell widths:", len(w), [float(v) for v in (w[0], w[-1])])
case = {c[0]: c for c in ev.cases()}["B_raw_recipe_1e16"]
_, P, T, G, preds = case
marked = [bool(preds[0](x)) for x in np.asarray(P, float)[T].mean(1)]
print("B_raw 1e16 pass 0: sweep prototype", len(proto.refine_once_rgb(P, T, G, marked)[1]), "queue blue", len(rb.refine_once_blue(P, T, G, marked)[1]))
