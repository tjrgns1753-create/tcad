"""Batch 7H-B required mutations (tests 3-7). Each injects one defect and the
corresponding check must detect it; unmutated controls run alongside.
Nothing here writes into data/ except the log captured by the caller."""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT_AUDIT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import formulas as fm  # noqa: E402
import fixtures as fx  # noqa: E402
import devsim_probe as dp  # noqa: E402
import judgments as jd  # noqa: E402
import run_fixtures as rf  # noqa: E402

RESULTS = []


def rec(name, detected, detail):
    RESULTS.append((name, bool(detected)))
    print(f"[{name}] {'DETECTED' if detected else 'MISSED'}  {detail}")


def main():
    res = json.load(open(os.path.join(ROOT_AUDIT, "data", "fixture_results.json"), encoding="utf-8"))

    # M1 endpoint mapping (real DEVSIM read of P5)
    import devsim
    p, t = fx.as_arrays("P5_interior_obtuse_Delaunay")
    pc = p * 1e-4
    dev, region, mesh = dp.import_fixture(devsim, pc, t, "mut_P5")
    m = dp.read_models(devsim, dev, region)
    devsim.delete_device(device=dev)
    devsim.delete_mesh(mesh=mesh)
    area = sum(fm.tri_area(pc[list(tt)]) for tt in t)
    tol = dp.ABS_FACTOR * dp.EPS * area

    def recon_ok(mm, key):
        r = rf.reconstructions(mm, pc)[key]
        return all(dp.match(d, q, tol) for d, q in zip(mm["NodeVolume"], r))
    ctrl = dp.verify_import(m, pc, t)["edge_endpoint_mapping_proven"] and recon_ok(m, "F6c") and recon_ok(m, "F6d")
    m1 = copy.deepcopy(m)
    m1["edge_n0"] = np.roll(m1["edge_n0"], 1)
    m2 = copy.deepcopy(m)
    m2["el_en1"][0], m2["el_en2"][0] = m["el_en2"][0], m["el_en1"][0]
    det1 = (not dp.verify_import(m1, pc, t)["edge_endpoint_mapping_proven"]) and not recon_ok(m1, "F6c")
    det2 = not recon_ok(m2, "F6d")
    rec("M1_endpoint_mapping", ctrl and det1 and det2,
        f"control_ok={ctrl} edge_n0_rolled_detected={det1} element_en1_en2_swap_detected={det2} devices_left={devsim.get_device_list()}")

    # M2 cotangent sign: F2 area conservation must break
    orig_cot = fm._cot
    p5, t5 = fx.as_arrays("T5_strong_obtuse")
    a5 = fm.tri_area(p5)
    ctrl = abs(fm.node_areas(p5, t5, "F2").sum() - a5) <= 1e-12 * a5
    fm._cot = lambda a, b, c: -orig_cot(a, b, c)
    mut = abs(fm.node_areas(p5, t5, "F2").sum() - a5) <= 1e-12 * a5
    fm._cot = orig_cot
    rec("M2_cotangent_sign", ctrl and not mut, f"control_conserves_area={ctrl} mutant_conserves_area={mut}")

    # M3 absolute -> signed: the F3 prediction must stop matching DEVSIM on obtuse fixtures
    orig_ptn = fm.per_triangle_node

    def f3_matches(names):
        out = {}
        for n in names:
            q, tt = fx.as_arrays(n)
            qc = q * 1e-4
            ar = sum(fm.tri_area(qc[list(x)]) for x in tt)
            pred = fm.node_areas(qc, tt, "F3")
            out[n] = all(dp.match(d, v, dp.ABS_FACTOR * dp.EPS * ar) for d, v in zip(res[n]["NodeVolume"], pred))
        return out
    names = ["T3_right_isosceles", "T5_strong_obtuse", "P5_interior_obtuse_Delaunay"]
    ctrl = f3_matches(names)
    fm.per_triangle_node = lambda pp, rule: orig_ptn(pp, "F2" if rule == "F3" else rule)
    mut = f3_matches(names)
    fm.per_triangle_node = orig_ptn
    rec("M3_absolute_vs_signed", all(ctrl.values()) and not mut["T5_strong_obtuse"] and not mut["P5_interior_obtuse_Delaunay"],
        f"control={ctrl} mutant={mut}")

    # M4 boundary-vs-interior classification
    H_ctrl, _ = jd.judge(res)
    orig_ec = jd.edge_class
    jd.edge_class = lambda tris: {e: "boundary" for e in orig_ec(tris)}
    H_mut, _ = jd.judge(res)
    jd.edge_class = orig_ec
    rec("M4_boundary_interior_classification",
        H_ctrl["H4_interior_obtuse_also"] == jd.CONF and H_mut["H4_interior_obtuse_also"] != jd.CONF
        and H_mut["H3_boundary_triangles_only"] != jd.EXCL,
        f"control H3/H4={H_ctrl['H3_boundary_triangles_only']}/{H_ctrl['H4_interior_obtuse_also']} "
        f"mutant H3/H4={H_mut['H3_boundary_triangles_only']}/{H_mut['H4_interior_obtuse_also']}")

    # M5 result-dependent tolerance enlargement (throwaway copy of this audit folder)
    chk = os.path.join(HERE, "check_completeness_7hb.py")
    c = subprocess.run([sys.executable, chk, ROOT_AUDIT], capture_output=True, text=True, encoding="utf-8", errors="replace")
    with tempfile.TemporaryDirectory() as td:
        dst = os.path.join(td, "audit")
        shutil.copytree(ROOT_AUDIT, dst, ignore=shutil.ignore_patterns("__pycache__"))
        pp = os.path.join(dst, "scripts", "devsim_probe.py")
        s = open(pp, encoding="utf-8").read().replace("REL_TOL = 1e-11", "REL_TOL = 1e-6")
        open(pp, "w", encoding="utf-8", newline="\n").write(s)
        mt = subprocess.run([sys.executable, chk, dst], capture_output=True, text=True, encoding="utf-8", errors="replace")
    rec("M5_tolerance_enlargement", c.returncode == 0 and mt.returncode == 1 and "REL_TOL" in mt.stdout,
        f"control_rc={c.returncode} mutant_rc={mt.returncode} mutant_msg={mt.stdout.strip().splitlines()[-1] if mt.stdout.strip() else ''}")

    n_missed = sum(1 for _, d in RESULTS if not d)
    print(f"=== {len(RESULTS) - n_missed}/{len(RESULTS)} DETECTED ===")
    return n_missed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
