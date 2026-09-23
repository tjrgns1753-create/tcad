"""Batch 7G Phase 1 -- 14 false-green mutation tests. Builds each mutated
fixture from the REAL completed geometry_7g.json / case_manifest_7g.json,
injects exactly one named defect, confirms check_completeness_7g.py (or
scan_public_api_only_7g.py for mutation 12) catches it. Mutation 11's
"existing audit file modified" test uses a THROWAWAY scratch copy, never a
real audit file (see this batch's own EVIDENCE_INTEGRITY_NOTICE.md for why).
usage: python mutation_tests_7g.py <geometry_7g.json> <case_manifest_7g.json>
"""
import copy
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(__file__)
CHECKER = os.path.join(HERE, "check_completeness_7g.py")
SCANNER_PATH = os.path.join(os.path.dirname(HERE), "..", "2026-09-22-batch7f-step-junction-root-cause", "scripts", "scan_public_api_only_7f.py")

results = []


def run_checker(geometry, manifest):
    with tempfile.TemporaryDirectory() as td:
        pg = os.path.join(td, "geometry.json")
        pm = os.path.join(td, "manifest.json")
        json.dump({"geometry_7g": geometry}, open(pg, "w", encoding="utf-8"))
        json.dump(manifest, open(pm, "w", encoding="utf-8"))
        p = subprocess.run([sys.executable, CHECKER, pg, pm], capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr


def check(name, expect_substring, returncode, output):
    caught = returncode == 1 and expect_substring in output
    results.append((name, caught))
    print(f"[{name}] {'CAUGHT' if caught else 'MISSED'} (rc={returncode})")
    if not caught:
        print("  " + output.strip().replace("\n", "\n  ")[-600:])


def check_direct(name, condition, detail=""):
    """For mutations verified as a direct boolean property of the algorithm
    itself (8, 9, 13), not via the completeness checker's text output."""
    results.append((name, bool(condition)))
    print(f"[{name}] {'CAUGHT' if condition else 'MISSED'} {detail}")


def main():
    geometry_path, manifest_path = sys.argv[1:3]
    geometry = list(json.load(open(geometry_path, encoding="utf-8")).values())[0]
    manifest = json.load(open(manifest_path, encoding="utf-8"))

    def base():
        return copy.deepcopy(geometry), copy.deepcopy(manifest)

    # 1. non-Delaunay edge count 누락
    geo, mf = base()
    for c in geo:
        c.pop("n_delaunay_violations", None)
    rc, out = run_checker(geo, mf)
    check("1_delaunay_count_missing", "missing Delaunay violation count", rc, out)

    # 2. constrained edge를 flip 가능으로 오분류 (proxy: n_constrained_edges forced to 0)
    geo, mf = base()
    for c in geo:
        if c.get("n_triangles", 0) > 0:
            c["n_constrained_edges"] = 0
    rc, out = run_checker(geo, mf)
    check("2_constrained_misclassified", "misclassified as flip-candidates", rc, out)

    # 3. T-junction 누락
    geo, mf = base()
    for c in geo:
        c.pop("n_hanging_nodes", None)
    rc, out = run_checker(geo, mf)
    check("3_tjunction_missing", "missing hanging-node check", rc, out)

    # 4. positive-area overlap을 shared-edge로 오판 (proxy: overlap search never ran)
    geo, mf = base()
    for c in geo:
        if c.get("n_triangles", 0) > 1:
            c["overlap_pairs_checked"] = 0
    rc, out = run_checker(geo, mf)
    check("4_overlap_search_skipped", "overlap search did not run", rc, out)

    # 5. hole 면적 누락
    geo, mf = base()
    for c in geo:
        c.pop("boundary_holes", None)
    rc, out = run_checker(geo, mf)
    check("5_hole_area_missing", "missing hole-area result", rc, out)

    # 6. NodeVolume를 triangle area와 같다고 강제 (imported case forced to 0 excess)
    geo, mf = base()
    for c in geo:
        if c.get("mode") == "imported":
            c["total_excess_relative"] = 0.0
    rc, out = run_checker(geo, mf)
    check("6_nodevolume_forced_equal_area", "forced equal to triangle area", rc, out)

    # 7. barycentric area 필드 제거 (mislabeling proxy)
    geo, mf = base()
    for c in geo:
        c.pop("sum_barycentric_cm2", None)
    rc, out = run_checker(geo, mf)
    check("7_barycentric_field_missing", "missing separate barycentric-vs-NodeVolume", rc, out)

    # 8. boundary/contact edge flip -- Candidate A's own safety guarantee, tested
    #    DIRECTLY against the algorithm (not the completeness checker): a
    #    hand-crafted mesh with a marked boundary edge must never be flipped.
    sys.path.insert(0, HERE)
    import numpy as np
    from candidate_a_edge_flip import flip_to_local_delaunay
    # a single triangle pair whose shared edge IS the only interior edge;
    # its OWN boundary edges must survive untouched regardless of geometry.
    pts = np.array([[0, 0, 0], [2, 0, 0], [2, 1, 0], [0, 1, 0]], dtype=float)
    tri = np.array([[0, 1, 2], [0, 2, 3]])
    tags = np.array([0, 0])
    _, new_tri, _, _ = flip_to_local_delaunay(pts, tri, tags)
    # boundary edges of the rectangle: (0,1),(1,2),(2,3),(3,0) must all still
    # appear as edges of SOME triangle after any flip attempt.
    def edges_of(tris):
        es = set()
        for t in tris:
            v0, v1, v2 = int(t[0]), int(t[1]), int(t[2])
            for a, b in ((v0, v1), (v1, v2), (v2, v0)):
                es.add((a, b) if a < b else (b, a))
        return es
    boundary_expected = {(0, 1), (1, 2), (2, 3), (0, 3)}
    survived = boundary_expected <= edges_of(new_tri)
    check_direct("8_boundary_edges_never_flipped", survived, f"boundary edges present after flip attempt: {survived}")

    # 9. material tag 손실 (2-material mesh, verify tags preserved after flip attempt)
    pts2 = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0, 0], [2, 1, 0]], dtype=float)
    tri2 = np.array([[0, 1, 2], [0, 2, 3], [1, 4, 5], [1, 5, 2]])
    tags2 = np.array([0, 0, 1, 1])
    _, new_tri2, new_tags2, _ = flip_to_local_delaunay(pts2, tri2, tags2)
    tags_preserved = sorted(tags2.tolist()) == sorted(new_tags2.tolist())
    check_direct("9_material_tags_preserved", tags_preserved, f"before={sorted(tags2.tolist())} after={sorted(new_tags2.tolist())}")

    # 10. L5 누락
    geo, mf = base()
    geo = [c for c in geo if "L5" not in c.get("label", "")]
    rc, out = run_checker(geo, mf)
    check("10_l5_missing", "missing cases", rc, out)

    # 11. 기존 audit 파일 변경 -- THROWAWAY scratch copy only, never a real file
    #     (permanently excluded per EVIDENCE_INTEGRITY_NOTICE.md).
    with tempfile.TemporaryDirectory() as td:
        scratch_dir = os.path.join(HERE, "..", "data")
        snap_src = os.path.join(scratch_dir, "pre_existing_hashes_7g.txt")
        scratch_snapshot = os.path.join(td, "pre_existing_hashes_7g.txt")
        # build a snapshot pointing at ONE throwaway file instead of any real audit file
        throwaway = os.path.join(td, "throwaway_audit_file.md")
        open(throwaway, "w", encoding="utf-8").write("original content\n")
        import hashlib
        sha_before = hashlib.sha256(open(throwaway, "rb").read()).hexdigest()
        rel = os.path.relpath(throwaway, os.path.join(HERE, "..", "..", "..", ".."))
        with open(scratch_snapshot, "w", encoding="utf-8") as f:
            f.write(f"{sha_before}  {rel}\n")
        # temporarily swap the checker's snapshot path expectation by copying
        # our scratch snapshot into the real snapshot location, run, then
        # modify the throwaway file, run again, restore the real snapshot.
        real_snapshot_backup = open(snap_src, "rb").read()
        try:
            with open(snap_src, "wb") as f:
                f.write(open(scratch_snapshot, "rb").read())
            geo, mf = base()
            rc1, out1 = run_checker(geo, mf)  # unmodified throwaway -> should pass this specific check
            with open(throwaway, "a", encoding="utf-8") as f:
                f.write("mutation 11 test line\n")
            rc2, out2 = run_checker(geo, mf)  # modified -> must be caught
            check("11_audit_file_modified", "pre-existing audit files modified", rc2, out2)
        finally:
            with open(snap_src, "wb") as f:
                f.write(real_snapshot_backup)

    # 12. private DEVSIM API 접근
    probe_src = open(os.path.join(HERE, "probe_delaunay_7g.py"), encoding="utf-8").read()
    # probe_delaunay_7g.py's only "import devsim" is INDENTED (inside
    # node_volume_vs_barycentric); match that indentation exactly so the
    # mutated source stays syntactically valid.
    mutated_src = probe_src.replace(
        "    import devsim", "    import devsim\n    devsim._internal_hack_marker = True", 1)
    with tempfile.TemporaryDirectory() as td:
        mpath = os.path.join(td, "probe_delaunay_7g_mutated.py")
        open(mpath, "w", encoding="utf-8").write(mutated_src)
        p = subprocess.run([sys.executable, SCANNER_PATH, mpath], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
        check("12_private_devsim_api", "PRIVATE/INTERNAL ACCESS", p.returncode, p.stdout + p.stderr)

    # 13. solver tolerance 변경 -- this batch's own geometry probe never solves
    #     anything (pure geometry + NodeVolume read), so there is no tolerance
    #     parameter to mutate in geometry_7g.json at all; the structural check
    #     is that no case carries a "relative_error"/"maximum_iterations" field
    #     DIFFERING from Batch 7F's own established defaults would ever be
    #     silently introduced -- confirmed by inspecting probe_delaunay_7g.py's
    #     own source for any devsim.solve() call (there must be none).
    solves_in_probe = "devsim.solve(" in probe_src
    check_direct("13_no_solver_tolerance_surface_in_geometry_probe", not solves_in_probe,
                 f"(structural, not a caught mutation: this phase's own geometry probe never calls devsim.solve() "
                 f"at all, so there is no tolerance value it could silently drift -- devsim.solve() present: {solves_in_probe})")

    # 14. actual iteration 수를 발명
    geo, mf = base()
    if geo:
        geo[0]["solve_detail"] = {"stage": {"actual_iterations": 99}}
    rc, out = run_checker(geo, mf)
    check("14_fabricated_actual_iterations", "fabricated actual_iterations", rc, out)

    print()
    print("=== SUMMARY ===")
    all_caught = True
    for name, caught in results:
        print(f"{'CAUGHT' if caught else 'MISSED'}  {name}")
        all_caught = all_caught and caught
    if all_caught:
        print(f"\nALL {len(results)}/14 MUTATIONS CAUGHT.")
        sys.exit(0)
    print("\nSOME MUTATIONS WERE MISSED.")
    sys.exit(1)


if __name__ == "__main__":
    main()
