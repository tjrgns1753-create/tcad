"""E6H criteria C: input / resource cases for structured_lateral_refine, each run in its own subprocess with a wall timeout and a
tracemalloc peak. usage: resource_cases.py <label>   (driver: resource_cases.py --all <out.json>)"""
import json, os, subprocess, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests", "unit"))
NAN, INF = float("nan"), float("inf")


def cases():
    from test_mesh_structured_remesh_mock import grid
    g = lambda nx, ny=4: grid([float(i) for i in range(nx + 1)], [float(j) for j in range(ny + 1)])  # noqa: E731
    ulp = grid([1.0, float.fromhex("0x1.0000000000001p+0"), 2.0], [0.0, 1.0])
    return {
        "nan_center": (g(8), [NAN], [1.0]),
        "inf_center": (g(8), [INF], [1.0]),
        "nan_halfwidth": (g(8), [4.0], [NAN]),
        "zero_halfwidth": (g(8), [4.0], [0.0]),
        "negative_halfwidth": (g(8), [4.0], [-1.0]),
        "empty_centers": (g(8), [], [1.0]),
        "empty_rings": (g(8), [4.0], []),
        "inf_halfwidth": (g(8), [4.0], [INF]),
        "rings_200": (g(8), [4.0], [1.0 / 2 ** k for k in range(200)]),
        "rings_60": (g(8), [4.0], [1.0 / 2 ** k for k in range(60)]),
        "midpoint_exhaustion": (ulp, [1.0], [1.0, 1.0]),
        "far_over_cap_100x100_depth8": (g(100, 100), [50.0], [64.0 / 2 ** k for k in range(8)]),
        "just_under_cap_valid": (g(200, 100), [100.0], [40.0, 20.0, 10.0]),
    }


def run_one(label):
    import tracemalloc
    import numpy as np
    from tcad.device.devsim.mesh_refine import structured_lateral_refine
    (P, T, G), c, r = cases()[label]
    tracemalloc.start()
    t = time.time()
    try:
        out = structured_lateral_refine(P, T, G, c, r)
        rep = out[3]
        res = {"outcome": "RETURNED", "identity": bool(rep.get("identity")), "triangles": rep.get("triangles"), "points": rep.get("points")}
    except Exception as e:  # noqa: BLE001
        res = {"outcome": type(e).__name__, "reason": getattr(e, "reason", None), "detail": str(e)[:160]}
    res["wall_s"] = round(time.time() - t, 2)
    res["peak_mb"] = round(tracemalloc.get_traced_memory()[1] / 1e6, 1)
    print(json.dumps(res))


if __name__ == "__main__":
    if sys.argv[1] == "--all":
        table = {}
        for label in cases():
            t = time.time()
            try:
                p = subprocess.run([sys.executable, __file__, label], capture_output=True, text=True, timeout=60)
                line = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""
                table[label] = json.loads(line) if line.startswith("{") else {"outcome": "CRASH", "rc": p.returncode, "stderr": p.stderr[-200:]}
            except subprocess.TimeoutExpired:
                table[label] = {"outcome": "TIMEOUT_60s"}
            print(label, table[label], flush=True)
        with open(sys.argv[2], "w", newline="\n") as f:
            json.dump(table, f, indent=1)
    else:
        run_one(sys.argv[1])
