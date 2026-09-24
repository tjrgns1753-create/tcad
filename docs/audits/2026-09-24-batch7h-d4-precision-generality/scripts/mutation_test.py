"""Batch 7H-D4 section 2: reproduce the D3 false-PASS paths A-D and show the D4 analyzer blocks them.

No physics is computed. Inputs are COPIES of the committed D3 evidence (11 run JSONs, PLAN.md, PLAN.sha256);
the D3 files themselves are only read. For each case the OLD D3 analyzer (analyze_d3.py, run unmodified from its
own folder) and the NEW D4 analyzer (analyze_d4.py --mode d3) are run on the same copy.
  baseline : unmodified copy                    -> both must give E1 PASS / E2 MIRROR_PASS
  A        : one run's fixture.identical_to_stored = False
  B        : PLAN.md copy altered (hash mismatch)
  C        : E2_M1_h0.005_P4_mirror.json removed
  D        : 'identical_to_stored' field deleted from one run
usage: mutation_test.py <work dir>   -> <work dir>/mutation_results.json"""
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
D3 = os.path.join(ROOT, "docs", "audits", "2026-09-24-batch7h-d3-precision-pair-mirror")
RUNS = os.path.join(D3, "data", "remote_run_35896298771", "outputs", "d3_out", "runs")


def prepare(work, case):
    w = os.path.join(work, case)
    shutil.rmtree(w, ignore_errors=True)
    shutil.copytree(RUNS, os.path.join(w, "runs"))
    os.makedirs(os.path.join(w, "plan"))
    for f in ("PLAN.md", "PLAN.sha256"):
        shutil.copyfile(os.path.join(D3, f), os.path.join(w, "plan", f))
    victim = os.path.join(w, "runs", "E1_M2_D0_h0.005_P12.json")
    if case == "A":
        r = json.load(open(victim, encoding="utf-8"))
        r["fixture"]["identical_to_stored"] = False
        json.dump(r, open(victim, "w", encoding="utf-8"))
    elif case == "B":
        with open(os.path.join(w, "plan", "PLAN.md"), "a", encoding="utf-8") as f:
            f.write("\nEdited after the fact.\n")
    elif case == "C":
        os.remove(os.path.join(w, "runs", "E2_M1_h0.005_P4_mirror.json"))
    elif case == "D":
        r = json.load(open(victim, encoding="utf-8"))
        del r["fixture"]["identical_to_stored"]
        json.dump(r, open(victim, "w", encoding="utf-8"))
    return w


def old(w):
    out = os.path.join(w, "old")
    p = subprocess.run([sys.executable, os.path.join(D3, "scripts", "analyze_d3.py"), "--runs", os.path.join(w, "runs"),
                        "--out", out, "--plan-dir", os.path.join(w, "plan")], capture_output=True, text=True)
    if p.returncode != 0:
        return {"crashed": p.stderr[-300:]}
    f = json.load(open(os.path.join(out, "analysis_d3.json"), encoding="utf-8"))["final"]
    return {"E1": f["E1_P12_equals_P4"], "E2": f["E2_mirror_P4"], "identity_all_ok": f["identity_all_ok"],
            "plan_hash_matches": f["plan_hash_matches"]}


def new(w):
    out = os.path.join(w, "new")
    p = subprocess.run([sys.executable, os.path.join(HERE, "analyze_d4.py"), "--mode", "d3", "--runs", os.path.join(w, "runs"),
                        "--out", out, "--plan-dir", os.path.join(w, "plan")], capture_output=True, text=True)
    f = json.load(open(os.path.join(out, "analysis_d4_mode_d3.json"), encoding="utf-8"))["final"]
    return {"integrity": f["EVIDENCE_INTEGRITY"], "E1": f["E1_P12_equals_P4"], "E2": f["E2_mirror_P4"],
            "first_integrity_errors": f["integrity_errors"][:3], "exit_code": p.returncode}


def main():
    work = os.path.abspath(sys.argv[1])
    os.makedirs(work, exist_ok=True)
    res = {}
    for case in ("baseline", "A", "B", "C", "D"):
        w = prepare(work, case)
        res[case] = {"old_d3_analyzer": old(w), "new_d4_analyzer": new(w)}
        print(case, json.dumps(res[case]))
    blocked = {c: res[c]["new_d4_analyzer"]["integrity"] == "EVIDENCE_INTEGRITY_FAIL"
               and res[c]["new_d4_analyzer"]["E1"] != "PASS" and res[c]["new_d4_analyzer"]["E2"] != "MIRROR_PASS"
               for c in ("A", "B", "C", "D")}
    base = res["baseline"]["new_d4_analyzer"]
    res["summary"] = {"old_false_pass": {c: res[c]["old_d3_analyzer"].get("E1") == "PASS" or res[c]["old_d3_analyzer"].get("E2") == "MIRROR_PASS"
                                         for c in ("A", "B", "C", "D")},
                      "new_blocks": blocked,
                      "baseline_reproduced": base["integrity"] == "EVIDENCE_INTEGRITY_PASS" and base["E1"] == "PASS" and base["E2"] == "MIRROR_PASS"}
    print("SUMMARY", json.dumps(res["summary"]))
    json.dump(res, open(os.path.join(work, "mutation_results.json"), "w", encoding="utf-8"), indent=1)
    return 0 if all(blocked.values()) and res["summary"]["baseline_reproduced"] else 1


if __name__ == "__main__":
    sys.exit(main())
