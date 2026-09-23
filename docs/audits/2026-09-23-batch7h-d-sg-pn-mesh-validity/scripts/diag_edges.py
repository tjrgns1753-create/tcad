"""Batch 7H-D supplementary diagnostic (added after the registered runs; same
builds, same production setup functions, same sg_lib.solve). Re-runs only
Experiment A (Poisson) and B (0 V DD) per configuration to read quantities
the registered worker did not store:
  * max |ElectricField| over edges (V/cm; edge-projected field, production model)
  * max |ElectronCurrent|, |HoleCurrent| over edges (A/cm^2) and the same
    times the edge couple actually assembled (A/cm in 2D)
  * 2D: overshoot nodes at 0 V (psi outside the contact range +-1e-9 V,
    n or p outside the contact [min,max]*(1+-1e-9)) and their graph distance
    (edge hops) to the nearest endpoint of a negative signed couple edge
  * 2D: PE-block sign-violation edges vs negative signed couple edges
usage: diag_edges.py <group>   (ref1d | synth2d | l3ref | l3); writes data/diag_edges_<group>.json"""
import json
import os
import subprocess
import sys
from collections import deque

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def one(cfg):
    import devsim as dv
    import sg_lib as sl
    import sg_worker as sw
    from diag_m4_blocks import entries
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    g = lambda n: np.array(dv.get_edge_model_values(device="d", region=sl.REGION, name=n))  # noqa: E731
    cn, _ = sw.build(dv, cfg)
    out = {"cfg": cfg}
    two_d = cfg["kind"] == "2d"
    if two_d:
        couple, _vol = sl.signed_geometry(dv)
        n0 = [int(v) for v in g("node_index@n0")]
        n1 = [int(v) for v in g("node_index@n1")]
        neg = {(min(a, b), max(a, b)) for a, b, c in zip(n0, n1, couple) if c < 0}
        adj = {}
        for a, b in zip(n0, n1):
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
        src = {v for e in neg for v in e}
        hop = {v: 0 for v in src}
        dq = deque(src)
        while dq:
            u = dq.popleft()
            for w in adj[u]:
                if w not in hop:
                    hop[w] = hop[u] + 1
                    dq.append(w)
        out["n_negative_signed_couple_edges"] = len(neg)
    setup_semiconductor_potential_equation("d", sl.REGION, ["left", "right"], 300.0)
    ok, _ = sl.solve(dv, "poisson", "A")
    out["A_ok"] = ok
    if ok:
        out["A_max_abs_ElectricField_V_per_cm"] = float(np.max(np.abs(g("ElectricField"))))
        setup_drift_diffusion_equation("d", sl.REGION, ["left", "right"])
        ok, _ = sl.solve(dv, "dd", "B0")
        out["B_ok"] = ok
    if ok:
        cpl_name = "OvEdgeCouple" if cfg.get("variant") in ("D1", "D2") else "EdgeCouple"
        cpl = g(cpl_name)
        jn, jp = g("ElectronCurrent"), g("HoleCurrent")
        out.update({"B_couple_model": cpl_name,
                    "B_max_abs_ElectronCurrent_A_per_cm2": float(np.max(np.abs(jn))),
                    "B_max_abs_HoleCurrent_A_per_cm2": float(np.max(np.abs(jp))),
                    "B_max_abs_ElectronCurrent_x_couple": float(np.max(np.abs(jn * cpl))),
                    "B_max_abs_HoleCurrent_x_couple": float(np.max(np.abs(jp * cpl)))})
        if two_d:
            nv = lambda n: np.array(dv.get_node_model_values(device="d", region=sl.REGION, name=n))  # noqa: E731
            x, y, psi, n, p = nv("x"), nv("y"), nv("Potential"), nv("Electrons"), nv("Holes")
            c = sorted(cn)
            pl, pr = psi[x == x.min()].mean(), psi[x == x.max()].mean()
            bad = {"psi": np.where((psi > max(pl, pr) + 1e-9) | (psi < min(pl, pr) - 1e-9))[0],
                   "n": np.where((n > n[c].max() * (1 + 1e-9)) | (n < n[c].min() * (1 - 1e-9)))[0],
                   "p": np.where((p > p[c].max() * (1 + 1e-9)) | (p < p[c].min() * (1 - 1e-9)))[0]}
            for k, idx in bad.items():
                hops = [hop.get(int(i), -1) for i in idx]
                out[f"B_overshoot_{k}"] = {"n_nodes": int(len(idx)),
                                           "hop_histogram_to_negative_couple_endpoint": {str(h): hops.count(h) for h in sorted(set(hops))},
                                           "coords_um_sample": [[float(x[i] * 1e4), float(y[i] * 1e4)] for i in idx[:12]]}
            out["B_psi_overshoot_max_V"] = float(max(0.0, psi.max() - max(pl, pr), min(pl, pr) - psi.min()))
            ent = entries(dv, (sl.PE,), cn)[sl.PE]["violations"]
            pairs = {(min(k, q), max(k, q)) for k, q, _ in ent}
            out["B_PE_violation_edges"] = len(pairs)
            out["B_PE_violation_edges_subset_of_negative_couple"] = pairs <= neg
            out["B_negative_couple_edges_all_violating_or_contact"] = all(e in pairs or e[0] in cn or e[1] in cn for e in neg)
            if cfg["mesh"].startswith("L3"):
                out["negative_couple_edges_midpoints_um"] = sorted(
                    [[float((x[a] + x[b]) * 0.5e4), float((y[a] + y[b]) * 0.5e4)] for a, b in neg])
    sw.teardown(dv)
    return out


def main(group):
    import run_matrix as rm
    res = {}
    for cfg in rm.configs(group):
        p = subprocess.run([sys.executable, os.path.abspath(__file__), "--one", json.dumps(cfg)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=3600,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        t = p.stdout
        r = json.loads(t.split("===RESULT_JSON===", 1)[1].strip().splitlines()[0]) if "===RESULT_JSON===" in t \
            else {"error": (t + p.stderr)[-800:]}
        res[cfg["id"]] = r
        print(cfg["id"], {k: v for k, v in r.items() if k not in ("cfg", "negative_couple_edges_midpoints_um")}, flush=True)
    with open(os.path.join(HERE, "..", "data", f"diag_edges_{group}.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)


if __name__ == "__main__":
    if sys.argv[1] == "--one":
        r = one(json.loads(sys.argv[2]))
        print("===RESULT_JSON===")
        print(json.dumps(r))
    else:
        main(sys.argv[1])
