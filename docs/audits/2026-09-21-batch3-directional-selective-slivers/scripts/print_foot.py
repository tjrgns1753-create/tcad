"""Print the raw geometry around the right window wall (x = +2) for chosen runs: native level-set segments
(pre and post) and volume-mesh triangles (post). Post-processing of raw/matrix_results.json only.

usage: print_foot.py <grid> <label> [<label> ...]        e.g.  print_foot.py 0.05 directional_plain directional_selective
"""
import json
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
data = json.loads((AUDIT / "raw" / "matrix_results.json").read_text(encoding="utf-8"))
grid = float(sys.argv[1])
labels = sys.argv[2:]


def fmt(seg):
    (x1, y1), (x2, y2) = seg
    return f"({x1:.5f},{y1:+.5f})->({x2:.5f},{y2:+.5f})"


for r in data["runs"]:
    if r["grid_um"] != grid or r["label"] not in labels:
        continue
    print(f"\n######## grid {grid}  {r['label']}")
    for stage, key in (("PRE ", "foot_native_pre"), ("POST", "foot_native_post")):
        for ls in ("Mask", "SiO2", "Si"):
            segs = r[key][ls]
            print(f"  native {stage} LS {ls}: {len(segs)} segments in the crop")
            for s in segs:
                print("     ", fmt(s))
    tris = r["foot_volume_final"]
    print(f"  exported POST triangles touching the crop: {len(tris)}")
    for t in tris:
        v = t["vertices"]
        xs = [p[0] for p in v]
        print(f"      {t['material']:<4} x[{min(xs):.5f},{max(xs):.5f}] " + " ".join(f"({p[0]:.5f},{p[1]:+.5f})" for p in v))
