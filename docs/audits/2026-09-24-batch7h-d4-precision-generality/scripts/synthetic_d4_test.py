"""Batch 7H-D4: SYNTHETIC test of analyze_d4.py --mode d4 (no physics, no DEVSIM).

Fake D4 runs are built from the committed D3 E1 run JSONs (real field layout) with the cfg / fixture identity
relabelled to the D4 matrix, plus small fake node-state archives. Cases and the verdicts they must produce:
  good        -> EVIDENCE_INTEGRITY_PASS, P12_MATCHES..., NODE_STATE_MATCHES...
  node_diff   -> NODE_STATE_DIFFERS (psi of one P12 run shifted by 1e-6 V at one node)
  cur_diff    -> P12_DIFFERS_FROM_P4_ON_TESTED_FIXTURE (one cut current of one P12 run scaled by 1 + 1e-4)
  npz_missing -> EVIDENCE_INTEGRITY_FAIL (archive deleted)
  npz_tamper  -> EVIDENCE_INTEGRITY_FAIL (archive changed after its hash was recorded)
  run_missing -> EVIDENCE_INTEGRITY_FAIL (one of the six run files removed)
  field_gone  -> EVIDENCE_INTEGRITY_FAIL (identical_to_stored deleted)
  bad_flags   -> EVIDENCE_INTEGRITY_FAIL (P12 run reports extended_solver True)
  not_conv    -> EVIDENCE_INTEGRITY_FAIL (one solve step with final_device_rel 1e-8)
usage: synthetic_d4_test.py <work dir>"""
import copy
import zlib
import hashlib
import json
import os
import shutil
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
D4 = os.path.abspath(os.path.join(HERE, ".."))
D3RUNS = os.path.join(ROOT, "docs", "audits", "2026-09-24-batch7h-d3-precision-pair-mirror", "data", "remote_run_35896298771",
                      "outputs", "d3_out", "runs")
sys.path.insert(0, HERE)
import analyze_d4 as A4  # noqa: E402

POINT_KEYS = ["B0", "B0rev", "Cp0_050", "Cp0_100", "Cm0_100"]


def make(work, case):
    runs = os.path.join(work, case, "runs")
    shutil.rmtree(os.path.join(work, case), ignore_errors=True)
    os.makedirs(runs)
    tmpl = {P: json.load(open(os.path.join(D3RUNS, f"E1_M2_D0_h0.005_{P}.json"), encoding="utf-8")) for P in ("P12", "P4")}
    for rid, cfg in A4.expected_matrix("d4").items():
        r = copy.deepcopy(tmpl[cfg["P"]])
        r["cfg"] = dict(cfg)
        fsha, nn, nt, csha, ksha = A4.FIXTURES[f"{cfg['fam']}_h{cfg['h']}"]
        r["fixture"].update({"file_sha256_raw": fsha, "n_nodes": nn, "n_triangles": nt, "coordinates_sha256": csha,
                             "connectivity_sha256": ksha, "stored_coordinates_sha256": csha, "stored_connectivity_sha256": ksha,
                             "identical_to_stored": True})
        n = 50
        base = np.random.default_rng(zlib.crc32(f"{cfg['fam']}_{cfg['h']}".encode()))   # same arrays for P12 and P4 of a fixture
        arr = {"x": np.linspace(-0.5e-4, 0.5e-4, n), "y": np.zeros(n)}
        for k in POINT_KEYS:
            arr[f"psi_{k}"] = base.uniform(-0.42, 0.42, n)
            arr[f"n_{k}"] = 10 ** base.uniform(3, 17, n)
            arr[f"p_{k}"] = 10 ** base.uniform(3, 17, n)
        if case == "node_diff" and rid == "D4_M1_D0_h0.00125_P12":
            arr["psi_Cp0_100"][7] += 1e-6
        if case == "cur_diff" and rid == "D4_M2_D0_h0.00125_P12":
            r["steps"]["C+0.100"]["C2"]["+0.10"]["total"] *= 1 + 1e-4
        npz = os.path.join(runs, rid + ".npz")
        np.savez_compressed(npz, **arr)
        h = lambda a: hashlib.sha256(a.tobytes()).hexdigest()  # noqa: E731
        r["node_state"] = {"npz": rid + ".npz", "npz_sha256": hashlib.sha256(open(npz, "rb").read()).hexdigest(),
                           "x_sha256": h(arr["x"]), "y_sha256": h(arr["y"]), "elements_sha256": "e" * 64, "n_nodes": n}
        if case == "field_gone" and rid == "D4_M1_D0_h0.005_P12":
            del r["fixture"]["identical_to_stored"]
        if case == "bad_flags" and rid == "D4_M1_D0_h0.005_P12":
            r["flags_set"]["extended_solver"] = True
        if case == "not_conv" and rid == "D4_M2_D0_h0.00125_P4":
            r["steps"]["C-0.075"]["info"]["final_device_rel"] = 1e-8
        json.dump(r, open(os.path.join(runs, rid + ".json"), "w", encoding="utf-8"))
    if case == "npz_missing":
        os.remove(os.path.join(runs, "D4_M1_D0_h0.00125_P4.npz"))
    if case == "npz_tamper":
        with open(os.path.join(runs, "D4_M1_D0_h0.00125_P4.npz"), "ab") as f:
            f.write(b"x")
    if case == "run_missing":
        os.remove(os.path.join(runs, "D4_M2_D0_h0.00125_P12.json"))
    return runs


def main():
    work = os.path.abspath(sys.argv[1])
    expect = {"good": ("EVIDENCE_INTEGRITY_PASS", "P12_MATCHES_P4_FOR_TESTED_NONOBTUSE_DEFAULT_FIXTURES_AND_BIASES", "NODE_STATE_MATCHES_ON_TESTED_FIXTURES"),
              "node_diff": ("EVIDENCE_INTEGRITY_PASS", "P12_MATCHES_P4_FOR_TESTED_NONOBTUSE_DEFAULT_FIXTURES_AND_BIASES", "NODE_STATE_DIFFERS"),
              "cur_diff": ("EVIDENCE_INTEGRITY_PASS", "P12_DIFFERS_FROM_P4_ON_TESTED_FIXTURE", "NODE_STATE_MATCHES_ON_TESTED_FIXTURES")}
    for c in ("npz_missing", "npz_tamper", "run_missing", "field_gone", "bad_flags", "not_conv"):
        expect[c] = ("EVIDENCE_INTEGRITY_FAIL", "P12_GENERALITY_INCONCLUSIVE", "NODE_STATE_INCONCLUSIVE")
    res, allok = {}, True
    for case, want in expect.items():
        runs = make(work, case)
        out = os.path.join(work, case, "out")
        subprocess.run([sys.executable, os.path.join(HERE, "analyze_d4.py"), "--mode", "d4", "--runs", runs, "--out", out, "--plan-dir", D4],
                       capture_output=True, text=True)
        f = json.load(open(os.path.join(out, "analysis_d4_mode_d4.json"), encoding="utf-8"))["final"]
        got = (f["EVIDENCE_INTEGRITY"], f["P12_generality"], f["node_state"])
        ok = got == want
        allok = allok and ok
        res[case] = {"got": got, "expected": want, "ok": ok, "first_error": (f["integrity_errors"] or [None])[0]}
        print(f"{case:12s} ok={ok} got={got} first_error={res[case]['first_error']}")
    json.dump(res, open(os.path.join(work, "synthetic_d4_results.json"), "w", encoding="utf-8"), indent=1)
    print("ALL_OK", allok)
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
