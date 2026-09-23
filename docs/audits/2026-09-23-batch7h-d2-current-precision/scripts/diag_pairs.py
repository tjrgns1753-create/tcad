"""Batch 7H-D2 SUPPLEMENTARY (after the registered runs; not a registered input and
changes no registered verdict). Registered P1-P3 (single flags) did not restore the
contact current while P4 (all three) did; this finds the minimal flag COMBINATION
on the 1D fixture only. Same worker_d2.run (registered code, unmodified) with the
variant table extended in memory by three pairs:
  P12 = model + equation, P13 = model + solver, P23 = equation + solver.
usage: diag_pairs.py -> data/diag_pairs.json"""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PAIRS = {"P12": (True, True, False), "P13": (True, False, True), "P23": (False, True, True)}

if __name__ == "__main__":
    if len(sys.argv) > 1:
        import common_d2 as c2
        c2.VARIANTS.update(PAIRS)
        import worker_d2 as wk
        print("RESULT " + json.dumps(wk.run(json.loads(sys.argv[1]))))
        sys.exit(0)
    res = {}
    for h in (0.005, 0.00125, 0.0003125):
        for P in PAIRS:
            cfg = {"kind": "1d", "h": h, "P": P, "mirror": False}
            p = subprocess.run([sys.executable, os.path.abspath(__file__), json.dumps(cfg)], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=3600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            ln = [x for x in p.stdout.splitlines() if x.startswith("RESULT ")]
            r = json.loads(ln[-1][7:]) if ln else {"error": p.stderr[-500:]}
            out = {"flags_set": r.get("flags_set"), "flags_at_start": r.get("flags_at_start")}
            for b in ("C-0.100", "C+0.050", "C+0.100"):
                s = r["steps"][b]
                L, R = s["C0"]["left"]["total"], s["C0"]["right"]["total"]
                c = [s["C2"][k]["total"] for k in s["C2"]]
                i0 = s["C2"]["+0.00"]["total"]
                out[b] = {"ok": s["info"]["ok"], "C0_left": L, "mis_lr": abs(L + R) / abs(L),
                          "spread": (max(c) - min(c)) / abs(i0), "c0_vs_cut0": abs(L - i0) / abs(i0),
                          "dev_vs_py_dpsi_left": s["ulp"]["left_contact"]["max_rel_dev_minus_py_dpsi"]}
            res[f"1D_h{h}_{P}"] = out
            print(f"1D_h{h}_{P}", out["flags_set"], {b: "mis=%.1e sprd=%.1e c0/cut=%.1e devpy=%.1e" % (
                out[b]["mis_lr"], out[b]["spread"], out[b]["c0_vs_cut0"], out[b]["dev_vs_py_dpsi_left"]) for b in ("C-0.100", "C+0.100")}, flush=True)
    with open(os.path.join(HERE, "..", "data", "diag_pairs.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(res, fh, indent=1)
