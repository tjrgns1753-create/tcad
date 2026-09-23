"""Batch 7H-A required mutations. Each injects exactly one defect into the
exact checker / exact flip / invariant data and requires the corresponding
gate to detect it. Unmutated controls are run alongside each one."""
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "docs", "audits", "2026-09-22-batch7f-step-junction-root-cause", "scripts"))

import exact_geometry as eg  # noqa: E402
import exact_flip as ef  # noqa: E402
import test_exact_synthetic as ts  # noqa: E402

RESULTS = []


def rec(name, detected, detail):
    RESULTS.append((name, detected))
    print(f"[{name}] {'DETECTED' if detected else 'MISSED'}  {detail}")


def changed_invariants(inv_b, inv_a):
    return [k for k in ("n_triangles", "tag_counter", "boundary_edge_set", "interface_edge_set", "non_manifold_edge_set",
                        "duplicate_triangle_set", "zero_area_set", "inverted_set", "total_area2_int") if inv_b[k] != inv_a[k]]


def synthetic_run_failures():
    ts.RESULTS.clear()
    ok = ts.run()
    return ok, [n for n, good in ts.RESULTS if not good]


KITE = np.array([[-1, 0], [0, -3], [1, 0], [0, 1]], dtype=np.float32)
KITE_TRIS = [[0, 1, 3], [1, 2, 3]]   # diagonal (1,3) is exactly non-Delaunay


def main():
    orig_classify = eg.classify_pair
    orig_eligible = ef.eligible

    ok, fails = synthetic_run_failures()
    rec("control_unmutated_synthetic_all_pass", ok, f"failures={fails}")

    # M1 shared touch reported as overlap
    def m1(ipts, ti, tj):
        v = orig_classify(ipts, ti, tj)
        return eg.POSITIVE if v == eg.TOUCH else v
    eg.classify_pair = m1
    ok, fails = synthetic_run_failures()
    eg.classify_pair = orig_classify
    rec("M1_touch_reported_as_overlap", (not ok) and "A1_shared_vertex_only" in fails and "A14_rev1_false_polygon_is_exact_touch" in fails,
        f"failed={fails}")

    # M2 small exact overlap reported as touch
    def m2(ipts, ti, tj):
        v = orig_classify(ipts, ti, tj)
        return eg.TOUCH if v == eg.POSITIVE else v
    eg.classify_pair = m2
    ok, fails = synthetic_run_failures()
    eg.classify_pair = orig_classify
    rec("M2_small_overlap_reported_as_touch", (not ok) and "A13_exact_positive_below_rev1_area_tol" in fails
        and "A5_small_exact_positive_overlap" in fails, f"failed={fails}")

    # M3 material-interface edge flip allowed
    tags2 = [0, 1]
    ipts, _ = eg.exact_integer_points(KITE)
    inv_b = eg.mesh_exact_invariants(ipts, KITE_TRIS, tags2)
    _, _, iset, _ = eg.edge_sets(KITE_TRIS, tags2)
    prot = frozenset(e for e, _ in iset)
    t_ctrl, g_ctrl, _ = ef.exact_flip(KITE, KITE_TRIS, tags2, protected=prot)
    ctrl_changed = changed_invariants(inv_b, eg.mesh_exact_invariants(ipts, t_ctrl, g_ctrl))
    ef.eligible = lambda edge, own, tags, protected: len(own) == 2
    t_mut, g_mut, _ = ef.exact_flip(KITE, KITE_TRIS, tags2, protected=prot)
    ef.eligible = orig_eligible
    mut_changed = changed_invariants(inv_b, eg.mesh_exact_invariants(ipts, t_mut, g_mut))
    rec("M3_interface_edge_flip_allowed", ctrl_changed == [] and "interface_edge_set" in mut_changed,
        f"control_changed={ctrl_changed} mutant_changed={mut_changed}")

    # M4 protected boundary/contact edge flip allowed. A 1-owner boundary edge
    # has no second triangle, so it cannot be flipped at all; the gate that
    # protects boundary/contact edges is the `protected` set, so the mutant
    # ignores `protected` on an edge declared as a contact edge.
    tags1 = [0, 0]
    contact_edge = frozenset({(1, 3)})
    t_ctrl, _, _ = ef.exact_flip(KITE, KITE_TRIS, tags1, protected=contact_edge)
    ef.eligible = lambda edge, own, tags, protected: len(own) == 2 and tags[own[0][0]] == tags[own[1][0]]
    t_mut, _, _ = ef.exact_flip(KITE, KITE_TRIS, tags1, protected=contact_edge)
    ef.eligible = orig_eligible

    def has_edge(tris, e):
        return any(set(e) <= set(t) for t in tris)
    rec("M4_protected_contact_edge_flip_allowed", has_edge(t_ctrl, (1, 3)) and not has_edge(t_mut, (1, 3)),
        f"control_keeps_edge={has_edge(t_ctrl, (1, 3))} mutant_keeps_edge={has_edge(t_mut, (1, 3))}")

    # M5 tag Counter loss
    t_ok, g_ok, _ = ef.exact_flip(KITE, KITE_TRIS, tags1)
    inv_b1 = eg.mesh_exact_invariants(ipts, KITE_TRIS, tags1)
    ctrl = changed_invariants(inv_b1, eg.mesh_exact_invariants(ipts, t_ok, g_ok))
    g_bad = list(g_ok)
    g_bad[0] = 7
    mut = changed_invariants(inv_b1, eg.mesh_exact_invariants(ipts, t_ok, g_bad))
    rec("M5_tag_counter_loss", ctrl == [] and "tag_counter" in mut, f"control_changed={ctrl} mutant_changed={mut}")

    # M6 contact node set change (real DEVSIM import of a small mesh)
    import devsim
    from structured_mesh import import_structured_device
    pts = np.array([[0, 0], [1, 0], [2, 0], [0, 1], [1, 1], [2, 1]], dtype=np.float32)
    tris = np.array([[0, 1, 4], [0, 4, 3], [1, 2, 5], [1, 5, 4]])
    def contact_sets(name):
        region, _, contacts = import_structured_device(devsim, pts, tris, np.zeros(4, dtype=np.int64),
                                                       f"d7h_{name}", f"m7h_{name}", 1e-4)
        s = {c: sorted({int(v) for e in devsim.get_element_node_list(device=f"d7h_{name}", region=region, contact=c)
                        for v in e}) for c in contacts}
        devsim.delete_device(device=f"d7h_{name}")
        devsim.delete_mesh(mesh=f"m7h_{name}")
        return s

    def contact_node_sets_equal(a, b):   # same comparison run_7h_l3.py applies per contact
        return a.keys() == b.keys() and all(a[c] == b[c] for c in a)

    first, second = contact_sets("mut_a"), contact_sets("mut_b")
    mutated = {c: list(s) for c, s in second.items()}
    k0 = sorted(mutated)[0]
    mutated[k0] = mutated[k0][1:]
    rec("M6_contact_node_set_change", contact_node_sets_equal(first, second) and not contact_node_sets_equal(first, mutated),
        f"real_sets={first} control_equal={contact_node_sets_equal(first, second)} "
        f"mutant_equal={contact_node_sets_equal(first, mutated)} devices_left={devsim.get_device_list()}")

    # M7 A->B->A oscillation (criterion forced true every pass)
    _, _, rep = ef.exact_flip(KITE, KITE_TRIS, tags1, violation_fn=lambda *a: True, max_passes=5)
    rec("M7_ABA_oscillation", rep["terminated"] == "OSCILLATION_DETECTED",
        f"terminated={rep['terminated']} flips={[(h['old_diagonal'], h['new_diagonal']) for h in rep['history']]}")
    _, _, rep_ok = ef.exact_flip(KITE, KITE_TRIS, tags1)
    rec("control_exact_criterion_no_oscillation", rep_ok["terminated"] == "no_exact_violations_remaining",
        f"terminated={rep_ok['terminated']}")

    n_missed = sum(1 for _, d in RESULTS if not d)
    print(f"=== {len(RESULTS) - n_missed}/{len(RESULTS)} DETECTED/PASSED ===")
    return n_missed == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
