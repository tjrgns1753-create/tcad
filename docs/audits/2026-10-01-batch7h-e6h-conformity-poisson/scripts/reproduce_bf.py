"""E6H: the modified structured_lateral_refine must reproduce the committed E6G B / F outputs exactly (same request, same arrays)."""
import json, os, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
import meshio, numpy as np  # noqa: E402
from tcad.device.devsim.mesh_refine import structured_lateral_refine  # noqa: E402
E6G = os.path.join(ROOT, "docs/audits/2026-10-01-batch7h-e6g-structured-template")
SRC = os.path.join(E6G, "data/remote_run_36737500532/outputs/e6g_out")
RAW = {"B": os.path.join(ROOT, "docs/audits/2026-09-30-batch7h-e6e-r1-gate-uncertainty/data/remote_run_36690617723/outputs/e6e_r1_out/B_raw.vtu"),
       "F": os.path.join(ROOT, "docs/audits/2026-09-28-batch7h-e6a-mesh-family/data/remote_run_36388479824/outputs/e6a_out/wafer_volume.vtu")}
out = {}
for k in ("B", "F"):
    real = json.load(open(os.path.join(SRC, f"real_{k}.json")))
    req = real["request"]
    m = meshio.read(RAW[k])
    P, T, G, rep = structured_lateral_refine(m.points, m.cells[0].data, m.cell_data["Material"][0], req["centers"], req["rings"])
    ref = meshio.read(os.path.join(SRC, f"{k}_refined.vtu"))
    same = bool(np.array_equal(P, ref.points) and np.array_equal(T, ref.cells[0].data) and np.array_equal(G, ref.cell_data["Material"][0]))
    out[k] = {"triangles": int(len(T)), "points": int(len(P)), "identical_to_E6G_committed_output": same}
    print(k, out[k], flush=True)
json.dump(out, open(os.path.join(HERE, "..", "reproduce_bf.json"), "w", newline="\n"), indent=1)
