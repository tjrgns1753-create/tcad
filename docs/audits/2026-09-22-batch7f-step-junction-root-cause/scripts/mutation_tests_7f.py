"""Batch 7F -- false-green mutation tests (section 14). Builds each mutated
fixture from the REAL completed imported_7f.json/structured_7f.json/
case_manifest.json (never invented from scratch), injects exactly one named
defect, and confirms check_completeness_7f.py (or scan_public_api_only_7f.py
for mutation 11) actually catches it.

usage: python mutation_tests_7f.py <imported_7f.json> <structured_7f.json> <case_manifest.json>
"""
import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(__file__)
CHECKER = os.path.join(HERE, "check_completeness_7f.py")
SCANNER = os.path.join(HERE, "scan_public_api_only_7f.py")

results = []


def run_checker(imported, structured, manifest):
    with tempfile.TemporaryDirectory() as td:
        pi = os.path.join(td, "imported.json")
        ps = os.path.join(td, "structured.json")
        pm = os.path.join(td, "manifest.json")
        json.dump({"imported_7f": imported}, open(pi, "w", encoding="utf-8"))
        json.dump({"structured_7f": structured}, open(ps, "w", encoding="utf-8"))
        json.dump(manifest, open(pm, "w", encoding="utf-8"))
        p = subprocess.run([sys.executable, CHECKER, pi, ps, pm], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


def check(name, expect_substring, returncode, output):
    caught = returncode == 1 and expect_substring in output
    results.append((name, caught))
    print(f"[{name}] {'CAUGHT' if caught else 'MISSED'} (rc={returncode})")
    if not caught:
        print("  --- checker output tail ---")
        print("  " + output.strip().replace("\n", "\n  ")[-800:])


def main():
    imported_path, structured_path, manifest_path = sys.argv[1:4]
    imported = list(json.load(open(imported_path, encoding="utf-8")).values())[0]
    structured = list(json.load(open(structured_path, encoding="utf-8")).values())[0]
    manifest = json.load(open(manifest_path, encoding="utf-8"))

    def base():
        return copy.deepcopy(imported), copy.deepcopy(structured), copy.deepcopy(manifest)

    # ---- 1. NodeVolume 없이 단순 node count로 inventory 계산 -----------------------------------------------------
    imp, st, mf = base()
    for c in imp:
        if "inventory" in c and c["inventory"]:
            del c["inventory"]["sum_NodeVolume_cm2"]
    rc, out = run_checker(imp, st, mf)
    check("1_no_nodevolume_inventory", "does not use NodeVolume", rc, out)

    # ---- 2. global edge scalar max를 vector-field max로 잘못 라벨링 -------------------------------------------------
    imp, st, mf = base()
    for c in imp:
        if c.get("field"):
            del c["field"]["n_elements"]
    rc, out = run_checker(imp, st, mf)
    check("2_scalar_mislabeled_as_vector", "scalar mislabeled as vector", rc, out)

    # ---- 3. field maximum 좌표를 기록하지 않음 ------------------------------------------------------------------------
    imp, st, mf = base()
    for c in imp:
        if c.get("field") and c["field"].get("global_max"):
            del c["field"]["global_max"]["centroid_cm"]
    rc, out = run_checker(imp, st, mf)
    check("3_no_field_location", "missing location", rc, out)

    # ---- 4. y variation을 검사하지 않음 -------------------------------------------------------------------------------
    imp, st, mf = base()
    for c in imp:
        c["y_invariance"] = None
    rc, out = run_checker(imp, st, mf)
    check("4_no_y_invariance", "missing y-invariance", rc, out)

    # ---- 5. structured control 누락 -----------------------------------------------------------------------------------
    imp, st, mf = base()
    mf["structured_cases"] = mf["structured_cases"][:3]
    rc, out = run_checker(imp, st, mf)
    check("5_structured_control_missing", "structured control missing", rc, out)

    # ---- 6. H/2H scaling 누락 -------------------------------------------------------------------------------------------
    imp, st, mf = base()
    mf["structured_cases"] = [c for c in mf["structured_cases"] if not c["label"].endswith(("_H", "_2H"))]
    rc, out = run_checker(imp, st, mf)
    check("6_h2h_missing", "H/2H", rc, out)

    # ---- 7. L5 누락 --------------------------------------------------------------------------------------------------------
    imp, st, mf = base()
    imp = [c for c in imp if c.get("level") != 5]
    mf["structured_cases"] = [c for c in mf["structured_cases"] if c.get("level_equiv") != 5]
    rc, out = run_checker(imp, st, mf)
    check("7_l5_missing", "missing imported levels", rc, out)

    # ---- 8. R1/R2 inventory 차이 누락 (drop one representation entirely at one level) --------------------------------------
    imp, st, mf = base()
    imp = [c for c in imp if not (c.get("level") == 3 and c.get("representation") == "R2" and not c.get("shifted"))]
    rc, out = run_checker(imp, st, mf)
    check("8_r1_r2_pair_incomplete", "combos", rc, out)

    # ---- 9. triangle quality 지표 누락 ----------------------------------------------------------------------------------------
    imp, st, mf = base()
    for c in imp:
        if c.get("mesh_quality"):
            del c["mesh_quality"]["transition_ring"]["triangle_min_angle_deg"]
    rc, out = run_checker(imp, st, mf)
    check("9_triangle_quality_missing", "missing fields", rc, out)

    # ---- 10. 기존 Batch 7D raw 파일을 수정 --------------------------------------------------------------------------------------
    # BYTE-SAFE: read/write in BINARY mode throughout (newline="" / "rb"/"wb")
    # so no text-mode newline translation can alter the file's exact bytes
    # across the temporary write+restore cycle -- a real, disclosed mistake
    # in an earlier version of this exact test corrupted
    # docs/audits/2026-09-21-batch7d-step-junction-convergence/REPORT.md's
    # line endings (LF -> CRLF) via Python's default text-mode round-trip on
    # Windows; see the Batch 7F chat report's own disclosure for the
    # incident and why this file's SHA-256 no longer matches the pre-Batch-
    # 7F snapshot despite being content-identical.
    batch7d_file = os.path.join(HERE, "..", "..", "2026-09-21-batch7d-step-junction-convergence", "REPORT.md")
    original_bytes = open(batch7d_file, "rb").read()
    try:
        with open(batch7d_file, "ab") as f:
            f.write(b"\n<!-- MUTATION TEST 10: this line must be detected and then removed -->\n")
        imp, st, mf = base()
        rc, out = run_checker(imp, st, mf)
        check("10_batch7d_file_modified", "Batch 7D pre-existing files modified", rc, out)
    finally:
        with open(batch7d_file, "wb") as f:
            f.write(original_bytes)
        restored_bytes = open(batch7d_file, "rb").read()
        assert restored_bytes == original_bytes, "FAILED TO RESTORE docs/audits/.../batch7d.../REPORT.md -- fix manually"
        print("  (Batch 7D REPORT.md restored to its exact original BYTES, binary-safe)")

    # ---- 11. private DEVSIM API 호출 -------------------------------------------------------------------------------------------
    probe_src = open(os.path.join(HERE, "probe_case_7f.py"), encoding="utf-8").read()
    mutated_src = probe_src.replace("devsim.solve(type=\"dc\"", "devsim._internal_hack(); devsim.solve(type=\"dc\"", 1)
    assert mutated_src != probe_src, "mutation site not found"
    with tempfile.TemporaryDirectory() as td:
        mpath = os.path.join(td, "probe_case_7f_mutated.py")
        open(mpath, "w", encoding="utf-8").write(mutated_src)
        p = subprocess.run([sys.executable, SCANNER, mpath], capture_output=True, text=True)
        check("11_private_devsim_api", "PRIVATE/INTERNAL ACCESS", p.returncode, p.stdout + p.stderr)

    # ---- 12. actual iteration 수를 발명 -------------------------------------------------------------------------------------------
    imp, st, mf = base()
    if imp:
        imp[0]["solve_detail"] = {"stage": {"actual_iterations": 42}}
    rc, out = run_checker(imp, st, mf)
    check("12_fabricated_actual_iterations", "fabricated actual_iterations", rc, out)

    print()
    print("=== SUMMARY ===")
    all_caught = True
    for name, caught in results:
        print(f"{'CAUGHT' if caught else 'MISSED'}  {name}")
        all_caught = all_caught and caught
    print()
    if all_caught:
        print(f"ALL {len(results)}/12 MUTATIONS CAUGHT.")
        sys.exit(0)
    print("SOME MUTATIONS WERE MISSED.")
    sys.exit(1)


if __name__ == "__main__":
    main()
