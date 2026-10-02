#!/usr/bin/env python3
"""E6M: limited 2D-1D consistency of the E6K p-n problem (GitHub-hosted runner only). PLAN fixed before any solve:
docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/PLAN.md. AUDIT path: the production gate (apply_doping) is called and must REFUSE the 2D step junction;
doping is then written directly with the public DEVSIM API and the unmodified production sweep is run. Nothing here enables a production PN measurement.
usage: test_pn_2d_1d_consistency_real.py [out_dir]   (writes pn_2d_consistency.json and arrays.npz; six devices, 42 solves planned)"""
import json
import math
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AUDIT / "scripts"))
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/scripts"))

import e6m_metrics as M  # noqa: E402
import judge_e6m as J  # noqa: E402

E6K = ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out"
E6J_JSON = ROOT / "docs/audits/2026-10-01-batch7h-e6j-current-unit-and-pn-plan/data/remote_run_36759423132/remote-run-24/outputs/e6j_out/gui_unit_contract.json"
LENGTH_SCALE = 1.0e-4
DOPING = {"Donors", "Acceptors", "NetDoping"}
C_MIN, C_MAX = "Si_xmin", "Si_xmax"


class Arr(dict):
    @property
    def files(self):
        return list(self.keys())


class Obs:
    """Pass-through observer (original calls unchanged): counts devsim.solve, records doping writes, and after each solve READS the listed arrays."""

    def __init__(self, dv, device):
        self.dv, self.device, self.solves, self.writes, self.snaps, self._orig = dv, device, 0, [], [], {}
        self.solve_attempts, self.solve_failures, self.snapshot_failures, self.call_log = 0, 0, 0, []

    def install(self):
        for n in ("solve", "node_model", "set_node_values"):
            self._orig[n] = getattr(self.dv, n)
        o = dict(self._orig)

        def solve(*a, **k):
            self.solve_attempts += 1
            call = {"attempt": self.solve_attempts, "status": "started"}
            self.call_log.append(call)
            try:
                r = o["solve"](*a, **k)
            except Exception:
                self.solve_failures += 1
                call["status"] = "solve_failed"
                raise
            self.solves += 1
            call["status"] = "solve_succeeded"
            try:
                self.snaps.append(self.snapshot())
            except Exception:
                self.snapshot_failures += 1
                call["snapshot_status"] = "failed"
                raise
            call["snapshot_status"] = "recorded"
            return r

        def node_model(*a, **k):
            if k.get("name") in DOPING:
                self.writes.append(("node_model", k["name"]))
            return o["node_model"](*a, **k)

        def set_node_values(*a, **k):
            if k.get("name") in DOPING:
                self.writes.append(("set_node_values", k["name"]))
            return o["set_node_values"](*a, **k)
        self.dv.solve, self.dv.node_model, self.dv.set_node_values = solve, node_model, set_node_values

    def restore(self):
        for n, fn in self._orig.items():
            setattr(self.dv, n, fn)

    def snapshot(self):
        dv, dev = self.dv, self.device
        snap = {"index": self.solves, "bias_min": float(dv.get_parameter(device=dev, name=f"{C_MIN}_bias")), "bias_max": float(dv.get_parameter(device=dev, name=f"{C_MAX}_bias"))}
        snap["Potential"] = np.array(dv.get_node_model_values(device=dev, region="Si", name="Potential"))
        try:
            snap["Electrons"] = np.array(dv.get_node_model_values(device=dev, region="Si", name="Electrons"))
            snap["Holes"] = np.array(dv.get_node_model_values(device=dev, region="Si", name="Holes"))
        except Exception:  # noqa: BLE001  (Poisson-only solve)
            pass
        snap["ElectricField"] = np.array(dv.get_edge_model_values(device=dev, region="Si", name="ElectricField"))
        snap["has_DD"] = "Electrons" in snap
        return snap


def canonical(path):
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_step_junction_doping
    from tcad.physics.wafer_state_accumulation import advance_wafer_state, initial_wafer_state_from_recipe
    pr = build_process_result({"final_mesh": path, "snapshots": []})
    doped = apply_step_junction_doping(pr, region="Si", junction_axis="x", junction_position_um=0.0, donor_conc_cm3=M.N_DOP, acceptor_conc_cm3=M.N_DOP, chemical_state="ACTIVE")
    base = initial_wafer_state_from_recipe({"x_extent_um": 40.0, "silicon_depth_um": M.H_UM, "grid_delta_um": 0.0})
    return advance_wafer_state(base, doped, "doping"), doped


def write_mesh(pts, tris, tag):
    import meshio
    from tcad.backends.viennaps import session
    si = int(session.require_viennaps().Material.Si)
    path = Path(tempfile.mkdtemp(prefix="e6m_")) / f"{tag}.vtu"
    meshio.write(str(path), meshio.Mesh(pts, [("triangle", tris)], cell_data={"Material": [np.full(len(tris), si, dtype=np.int32)]}))
    return str(path)


def nodes_of_contact(dv, device, contact):
    els = dv.get_element_node_list(device=device, region="Si", contact=contact)
    return sorted({int(i) for el in els for i in el})


def run_level(dv, lv, x_cm, arr):
    from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
    from tcad.device.devsim.doping_mapping import UnsupportedDopingState, apply_doping
    from tcad.device.devsim.mesh_import import import_process_result
    from conformity_e6h import check_conformity
    rec = {"geometry_import": {"regions": [], "conformity_pass": False, "pre_solve_geometry_ok": False, "area_gate": {"pass": False, "A": 0.0, "S": 0.0},
                               "contacts": {C_MIN: {"n_nodes": 0, "x_cm": [0.0, 0.0], "y_cm": [0.0, 0.0]}, C_MAX: {"n_nodes": 0, "x_cm": [0.0, 0.0], "y_cm": [0.0, 0.0]}}},
           "gate": {"raised": False, "resolution": "", "reason_code": "", "doping_writes": 0, "solves": 0},
           "audit_doping": {"canonical_checked": 0, "canonical_unresolved": 0, "canonical_mismatch": 0}, "devices": {}}
    pts, tris = M.build_mesh(x_cm)
    arr[f"{lv}__points_um"], arr[f"{lv}__triangles"] = pts, tris
    pre = M.geometry_checks(pts, tris)
    conf = check_conformity(pts, tris)
    rec["geometry_import"]["conformity_pass"] = bool(conf["pass"])
    rec["geometry_import"]["conformity"] = {k: v for k, v in conf.items() if k != "pass"}
    rec["geometry_import"]["pre_import"] = pre
    path = write_mesh(pts, tris, lv)
    state, doped = canonical(path)
    for d in M.DIRECTIONS:
        name = f"e6m_{lv}_{d}"
        dev = {"voltages": list(M.VOLTAGES[d]), "currents": [], "solves": 0, "expected_solves": 2 + len(M.VOLTAGES[d]), "error": None, "converged": False, "metadata": {}, "params": {}, "solve_log": []}
        rec["devices"][d] = dev
        imported, obs, t0 = None, None, time.time()
        try:
            imported = import_process_result(doped, mesh_name=f"{name}_mesh", device_name=name, contact_regions=["Si"], contact_axis="x", length_scale_to_cm=LENGTH_SCALE)
            x = np.array(dv.get_node_model_values(device=name, region="Si", name="x"))
            y = np.array(dv.get_node_model_values(device=name, region="Si", name="y"))
            if d == "fwd":      # geometry / import facts once per mesh, before any solve
                gi = rec["geometry_import"]
                gi["regions"] = list(imported.regions)
                ag = imported.area_conservation["Si"]
                gi["area_gate"] = {"pass": bool(ag["pass"]), "A": float(ag["A"]), "S": float(ag["S"]), "relative_uncertainty": float(ag["relative_uncertainty"])}
                gi["devsim_contacts"] = list(imported.contacts)
                for cn in (C_MIN, C_MAX):
                    idx = nodes_of_contact(dv, name, cn)
                    gi["contacts"][cn] = {"n_nodes": len(idx), "x_cm": [float(x[idx].min()), float(x[idx].max())], "y_cm": [float(y[idx].min()), float(y[idx].max())]}
                ok = (pre["area_rel_err"] <= J.LIM["area_rel"] and pre["obtuse_triangles"] == 0 and pre["degenerate_triangles"] == 0 and conf["pass"] and gi["area_gate"]["pass"]
                      and gi["regions"] == ["Si"] and all(gi["contacts"][c]["n_nodes"] == 3 for c in (C_MIN, C_MAX)))
                gi["pre_solve_geometry_ok"] = bool(ok)
                # production gate: the real apply_doping must refuse this 2D step junction (0 writes, 0 solves)
                gobs = Obs(dv, name)
                gobs.install()
                try:
                    apply_doping(name, "Si", state, length_scale_to_cm=LENGTH_SCALE)
                except UnsupportedDopingState as exc:
                    ps = exc.physics_status or {}
                    rec["gate"].update({"raised": True, "resolution": str(ps.get("resolution")), "reason_code": str(ps.get("reason_code")), "message": str(exc)[:400]})
                finally:
                    gobs.restore()
                    rec["gate"].update({"doping_writes": len(gobs.writes), "solves": gobs.solves,
                                        "solve_attempts": gobs.solve_attempts})
            # Each fresh device must have its own complete canonical query BEFORE any audit writes.
            dev["canonical_audit"] = M.canonical_checks(state, x, y, LENGTH_SCALE)
            if d == "fwd":
                rec["audit_doping"] = dict(dev["canonical_audit"])
            if not (rec["geometry_import"]["pre_solve_geometry_ok"] and rec["gate"]["raised"] and rec["gate"]["reason_code"] == J.GATE_REASON
                    and rec["gate"]["doping_writes"] == 0 and rec["gate"]["solves"] == 0
                    and rec["gate"].get("solve_attempts", 0) == 0 and rec["audit_doping"]["canonical_mismatch"] == 0):
                raise RuntimeError("STOP: geometry / gate / canonical-doping precondition not met; no solve for this mesh")
            dv.edge_from_node_model(device=name, region="Si", node_model="x")
            dv.edge_from_node_model(device=name, region="Si", node_model="y")
            obs = Obs(dv, name)
            obs.install()

            def write_audit_doping():
                # Public API, same node models and order as apply_doping; guarded above the first write.
                donors, acceptors = M.N_DOP * (x >= 0), M.N_DOP * (x <= 0)
                for nm, vals in (("Donors", donors), ("Acceptors", acceptors), ("NetDoping", donors - acceptors)):
                    dv.node_model(device=name, region="Si", name=nm, equation="0")
                    dv.set_node_values(device=name, region="Si", name=nm, values=[float(t) for t in vals])

            result = M.guarded_audit(
                dev["canonical_audit"], int(len(x)), write_audit_doping,
                lambda: run_pn_junction_iv_sweep(device=name, region="Si", all_contacts=imported.contacts, sweep_contact=C_MIN,
                                                sweep_voltages=list(M.VOLTAGES[d]), fixed_contacts={C_MAX: 0.0}))
            dev["metadata"] = {k: v for k, v in result.metadata.items() if k != "current_convention"}
            dev["currents"] = [{"V": v, "I_min": float(p.currents[C_MIN]), "I_max": float(p.currents[C_MAX])} for v, p in zip(M.VOLTAGES[d], result.points)]
            dev["params"] = {n: dv.get_parameter(device=name, region="Si", name=n) for n in J.PARAMS + ("V_t",)}
            dev["converged"] = all(math.isfinite(c["I_min"]) and math.isfinite(c["I_max"]) for c in dev["currents"])
            g = lambda n: np.array(dv.get_node_model_values(device=name, region="Si", name=n))  # noqa: E731
            e = lambda n: np.array(dv.get_edge_model_values(device=name, region="Si", name=n))  # noqa: E731
            geo = {"x": x, "y": y, "NodeVolume": g("NodeVolume"), "Donors": g("Donors"), "Acceptors": g("Acceptors"), "NetDoping": g("NetDoping"), "edge_x0": e("x@n0"), "edge_x1": e("x@n1"),
                   "edge_y0": e("y@n0"), "edge_y1": e("y@n1"), "EdgeLength": e("EdgeLength"), "element_nodes": np.array(dv.get_element_node_list(device=name, region="Si"))}
            for k, v in geo.items():
                arr[M.akey(lv, d, k)] = v
            for vb in M.SNAP_BIASES[d]:
                hit = [s for s in obs.snaps if s["has_DD"] and abs(s["bias_min"] - vb) < 1e-12 and abs(s["bias_max"]) < 1e-12]
                if hit:
                    for a in M.SNAP_ARRAYS:
                        arr[M.akey(lv, d, a, vb)] = hit[-1][a]
        except Exception as exc:  # noqa: BLE001
            dev["error"] = repr(exc)[:500]
            dev["traceback"] = traceback.format_exc()[-1500:]
        finally:
            if obs is not None:
                dev["solves"] = obs.solves
                dev.update(solve_attempts=obs.solve_attempts, solve_failures=obs.solve_failures,
                           snapshot_failures=obs.snapshot_failures, solve_call_log=obs.call_log)
                dev["solve_log"] = [{"index": s["index"], "bias_min": s["bias_min"], "bias_max": s["bias_max"], "has_DD": s["has_DD"]} for s in obs.snaps]
                obs.restore()
            if imported is not None:
                try:
                    dv.delete_device(device=imported.device)
                    dv.delete_mesh(mesh=imported.mesh)
                except Exception:  # noqa: BLE001
                    pass
        dev["wall_s"] = round(time.time() - t0, 2)
        print(lv, d, "solves", dev["solves"], "error", dev["error"], "wall", dev["wall_s"], flush=True)
    return rec


def run(out_dir):
    plan_sha = J.require_plan(AUDIT / "PLAN.md")
    from tcad.device.devsim import backend
    dv = backend.require_devsim()
    e6k_json, e6k_npz, e6j = json.load(open(E6K / "pn_1d_diagnostic.json")), np.load(E6K / "states.npz"), json.load(open(E6J_JSON))
    raw = {"plan_sha256": plan_sha, "H_um": M.H_UM, "judge_version": J.VERSION, "levels": {}}
    arr = Arr()
    for lv in M.LEVELS:
        x_cm = M.e6k_snapshot(e6k_npz, lv, "rev", 0.0)["x"]
        raw["levels"][lv] = run_level(dv, lv, x_cm, arr)
    raw["total_solves"] = sum(d["solves"] for L in raw["levels"].values() for d in L["devices"].values())
    raw["leaked_devices"] = list(dv.get_device_list())
    try:
        raw["summary"] = M.compute(raw, arr, e6k_json, e6k_npz)
    except Exception as exc:  # noqa: BLE001
        raw["summary_error"] = repr(exc)[:500]
    verdict = J.judge(raw, arr, e6k_json, e6k_npz, e6j)
    raw["verdicts"] = verdict
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "pn_2d_consistency.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(raw, f, indent=1, default=str)
        np.savez_compressed(os.path.join(out_dir, "arrays.npz"), **arr)
    for k, v in verdict.items():
        if isinstance(v, dict) and "verdict" in v:
            print(k, v["verdict"], [c["name"] for c in v.get("checks", []) if not c["pass"]][:5], v.get("problems", [])[:3])
    print("total solves:", raw["total_solves"], "leaked devices:", raw["leaked_devices"])
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
