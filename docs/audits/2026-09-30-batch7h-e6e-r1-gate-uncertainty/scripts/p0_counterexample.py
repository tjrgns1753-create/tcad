"""Batch 7H-E6E-R1 step 3: the P0 counterexample through the CURRENT (unmodified) mesh_conservation functions. Pure; no DEVSIM.
Input fixed by the Codex prompt: one sliver triangle (0,0),(1,0),(2,1e-14), area 5e-15, NodeVolume 2A/3 on each node (sum 2A)."""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from tcad.device.devsim import mesh_conservation as mc  # noqa: E402

P = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 1e-14, 0.0]])
T = np.array([[0, 1, 2]])
G = np.array([1])
o, e, p1, p2, theta = mc.triangle_terms(P, T)
out = {"o_t": float(o[0]), "area_from_o": float(abs(o[0]) / 2), "e_t": float(e[0]), "theta_min_rad": float(theta[0]),
       "sin_theta_min": float(np.sin(theta[0]))}
try:
    terms = mc.check_mesh_input(P, T, G, {1: "Si"}, [])
    out["check_mesh_input"] = "accepted (orientation certified, not degenerate)"
    A = terms["Si"]["area"]
    nv = np.full(3, 2 * A / 3)
    out["NodeVolume"] = nv.tolist()
    try:
        rep = mc.check_nodevolume(terms, {"Si": nv}, {"Si": 1})["Si"]
        out["check_nodevolume"] = "PASS"
    except mc.MeshAreaConservationError as exc:
        rep = exc.physics_status["regions"]["Si"]
        out["check_nodevolume"] = f"REFUSED {exc.physics_status['reason_code']}"
    B = rep["E_A"] + rep["E_S"] + rep["E_NV"]
    out.update({"A": A, "S": rep["sum_NodeVolume"], "S_over_A_minus_1": rep["relative_difference"], "E_A": rep["E_A"],
                "E_S": rep["E_S"], "E_NV": rep["E_NV"], "B": B, "B_over_A": B / A})
except mc.MeshAreaConservationError as exc:
    out["check_mesh_input"] = f"REFUSED {exc.physics_status['reason_code']}"
print(json.dumps(out, indent=1))
