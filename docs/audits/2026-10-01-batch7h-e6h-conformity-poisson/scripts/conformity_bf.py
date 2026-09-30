"""Apply the exact conformity checker to the committed E6G outputs B_refined.vtu / F_refined.vtu (no regeneration, no DEVSIM)."""
import hashlib, json, os, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
import meshio  # noqa: E402
from conformity_e6h import check_conformity, count_apex_triangles  # noqa: E402
SRC = os.path.join(ROOT, "docs/audits/2026-10-01-batch7h-e6g-structured-template/data/remote_run_36737500532/outputs/e6g_out")
out = {}
for name in ("B", "F"):
    path = os.path.join(SRC, f"{name}_refined.vtu")
    m = meshio.read(path)
    t = time.time()
    rep = check_conformity(m.points, m.cells[0].data)
    rep["wall_s"] = round(time.time() - t, 2)
    rep["file_sha256"] = hashlib.sha256(open(path, "rb").read()).hexdigest()
    rep["apex_triangles"] = count_apex_triangles(m.points, m.cells[0].data)
    out[name] = rep
    print(name, json.dumps(rep))
with open(os.path.join(HERE, "..", "conformity_bf.json"), "w", newline="\n") as f:
    json.dump(out, f, indent=1)
