"""Batch 7F -- proof that R1-shift and R2-shift produce BYTE-IDENTICAL
Donors/Acceptors arrays, justifying omitting R1-shift from the structured
matrix (bounded prompt section 11's own explicit escape hatch).

Algebraic proof (stated, then empirically confirmed on a real mesh):
  R1 acceptor(x) = NA * step(xj - x)       -- step(z) = 1 for z>=0 else 0
  R2 acceptor(x) = NA * (1 - step(x - xj))
For x != xj EXACTLY: step(xj-x)=1 iff x<=xj iff x<xj (since x!=xj), and
1-step(x-xj)=1 iff x-xj<0 iff x<xj -- the SAME condition. They differ ONLY
at x==xj exactly (R1 gives NA there since step(0)=1; R2 gives 0 since
1-step(0)=1-1=0). A SHIFTED junction is, by the P0-1 construction Batch 7D
Rev.2 already established and this audit's own locate_junction() reuses, at
the exact midpoint between two real nodes -- so NO real mesh node ever sits
at x==xj when shifted. Therefore every real node has R1==R2 for BOTH
representations when shifted: the two arrays must be byte-identical.
"""
import json
import os
import sys

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import warnings
warnings.simplefilter("ignore")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

import devsim  # noqa: E402
from structured_mesh import build_x_lines_um, build_structured_triangulation, import_structured_device  # noqa: E402

ND, NA = 1.0e18, 1.0e18
LENGTH_SCALE = 1.0e-4


def set_doping(device, region, representation, xj_cm):
    if representation == "R1":
        acc_eq = f"{NA:.10e}*step(({xj_cm:.10e})-x)"
    else:
        acc_eq = f"{NA:.10e}*(1-step(x-({xj_cm:.10e})))"
    devsim.node_model(device=device, region=region, name="Donors", equation=f"{ND:.10e}*step(x-({xj_cm:.10e}))")
    devsim.node_model(device=device, region=region, name="Acceptors", equation=acc_eq)


def main():
    xl = build_x_lines_um(0.1, 0.0125, 4.0, 0.2)
    pts, tris, tags = build_structured_triangulation(xl, 2.0, 20, diagonal="fixed")

    results = {}
    for rep in ("R1", "R2"):
        dev, mesh = f"d_{rep}", f"m_{rep}"
        region, mesh, contacts = import_structured_device(devsim, pts, tris, tags, dev, mesh, LENGTH_SCALE)
        x = devsim.get_node_model_values(device=dev, region=region, name="x")
        x0 = min(x, key=lambda v: abs(v - 0.0))
        righties = sorted(v for v in set(x) if v > x0)
        xj_shifted = (x0 + righties[0]) / 2.0
        set_doping(dev, region, rep, xj_shifted)
        donors = list(devsim.get_node_model_values(device=dev, region=region, name="Donors"))
        acceptors = list(devsim.get_node_model_values(device=dev, region=region, name="Acceptors"))
        results[rep] = {"x0": x0, "xj_shifted": xj_shifted, "donors": donors, "acceptors": acceptors}
        devsim.delete_device(device=dev)
        devsim.delete_mesh(mesh=mesh)

    import hashlib
    d1_hash = hashlib.sha256(json.dumps(results["R1"]["donors"]).encode()).hexdigest()
    d2_hash = hashlib.sha256(json.dumps(results["R2"]["donors"]).encode()).hexdigest()
    a1_hash = hashlib.sha256(json.dumps(results["R1"]["acceptors"]).encode()).hexdigest()
    a2_hash = hashlib.sha256(json.dumps(results["R2"]["acceptors"]).encode()).hexdigest()

    donors_identical = results["R1"]["donors"] == results["R2"]["donors"]
    acceptors_identical = results["R1"]["acceptors"] == results["R2"]["acceptors"]
    xj_identical = results["R1"]["xj_shifted"] == results["R2"]["xj_shifted"]

    out = {
        "xj_shifted_R1": results["R1"]["xj_shifted"], "xj_shifted_R2": results["R2"]["xj_shifted"],
        "xj_identical": xj_identical,
        "donors_byte_identical": donors_identical, "acceptors_byte_identical": acceptors_identical,
        "donors_sha256_R1": d1_hash, "donors_sha256_R2": d2_hash,
        "acceptors_sha256_R1": a1_hash, "acceptors_sha256_R2": a2_hash,
        "n_nodes": len(results["R1"]["donors"]),
        "VERDICT": "PROVEN byte-identical -- R1-shift may be safely omitted from the structured matrix"
                   if (donors_identical and acceptors_identical) else "NOT byte-identical -- do NOT omit R1-shift",
    }
    print("===BYTE_IDENTICAL_PROOF===")
    print(json.dumps(out, indent=2))
    return 0 if (donors_identical and acceptors_identical) else 1


if __name__ == "__main__":
    sys.exit(main())
