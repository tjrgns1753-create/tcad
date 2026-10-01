#!/usr/bin/env python3
"""E6K: first production-path 1D symmetric p-n junction diagnostic (GitHub-hosted runner only). Plan fixed before the run:
docs/audits/2026-10-01-e6k-pn-1d-diagnostic/PN_PLAN_v2.md. Judge: scripts/judge_e6k.py (six separate verdicts, never an overall PASS).
usage: test_pn_1d_diagnostic_real.py [out_dir]   (writes pn_1d_diagnostic.json and states.npz)
No tolerance / step / lifetime / mobility / mesh change after any result; a failed device is recorded and not retried. DEVSIM public API only."""
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
AUDIT = ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(AUDIT / "scripts"))

import judge_e6k as J  # noqa: E402
import pn_reference as R  # noqa: E402

E6J_JSON = ROOT / "docs/audits/2026-10-01-batch7h-e6j-current-unit-and-pn-plan/data/remote_run_36759423132/remote-run-24/outputs/e6j_out/gui_unit_contract.json"
N_ACC = N_DON = 1.0e17
HALF_UM = 20.0
LENGTH_SCALE = 1.0e-4
NODE_CAP = 20000
FWD = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
REV = [-0.25, -0.5, -0.75, -1.0]
SPACING_NM = [500.0, 100.0, 8.0, 4.0, 8.0, 100.0, 500.0]
POSITIONS_UM = [-20.0, -2.0, -0.3, 0.0, 0.3, 2.0, 20.0]
S_UM = [3.0, 5.0, 8.0]


def key(v):
    return f"{v:.1f}"


def rectangle_result(half_um, tag):
    import meshio
    from tcad.backends.viennaps import session
    from tcad.mesh.viennaps_adapter import build_process_result
    si = int(session.require_viennaps().Material.Si)
    pts = np.array([[-half_um, -1.0, 0.0], [half_um, -1.0, 0.0], [half_um, 0.0, 0.0], [-half_um, 0.0, 0.0]])
    path = Path(tempfile.mkdtemp(prefix="e6k_")) / f"{tag}.vtu"
    meshio.write(str(path), meshio.Mesh(pts, [("triangle", np.array([[0, 1, 2], [0, 2, 3]]))], cell_data={"Material": [np.full(2, si, dtype=np.int32)]}))
    return build_process_result({"final_mesh": str(path), "snapshots": []})


def canonical(kind, half_um, tag):
    from tcad.physics.doping import apply_step_junction_doping, apply_uniform_doping
    from tcad.physics.wafer_state_accumulation import advance_wafer_state, initial_wafer_state_from_recipe
    pr = rectangle_result(half_um, tag)
    if kind == "pn":
        doped = apply_step_junction_doping(pr, region="Si", junction_axis="x", junction_position_um=0.0, donor_conc_cm3=N_DON, acceptor_conc_cm3=N_ACC, chemical_state="ACTIVE")
    else:
        doped = apply_uniform_doping(pr, donor_by_region_cm3={"Si": 1.0e16}, acceptor_by_region_cm3={"Si": 0.0}, chemical_state="ACTIVE")
    base = initial_wafer_state_from_recipe({"x_extent_um": 2.0 * half_um, "silicon_depth_um": 1.0, "grid_delta_um": 0.0})
    return advance_wafer_state(base, doped, "doping")


class Obs:
    """Pass-through observer: every original call is made unchanged; after each devsim.solve it READS (never writes) the arrays listed in `ARRAYS`."""
    DOPING = {"Donors", "Acceptors", "NetDoping"}

    def __init__(self, dv, device):
        self.dv, self.device, self.solves, self.writes, self.values, self.snaps, self._orig = dv, device, 0, [], {}, [], {}

    def install(self):
        for n in ("solve", "node_model", "set_node_values"):
            self._orig[n] = getattr(self.dv, n)
        o = dict(self._orig)

        def solve(*a, **k):
            r = o["solve"](*a, **k)
            self.solves += 1
            self.snaps.append(self.snapshot())
            return r

        def node_model(*a, **k):
            if k.get("name") in self.DOPING:
                self.writes.append(("node_model", k["name"]))
            return o["node_model"](*a, **k)

        def set_node_values(*a, **k):
            if k.get("name") in self.DOPING:
                self.writes.append(("set_node_values", k["name"]))
                self.values[k["name"]] = sorted(set(float(v) for v in k.get("values", [])))
            return o["set_node_values"](*a, **k)
        self.dv.solve, self.dv.node_model, self.dv.set_node_values = solve, node_model, set_node_values

    def restore(self):
        for n, fn in self._orig.items():
            setattr(self.dv, n, fn)

    def snapshot(self):
        dv, dev = self.dv, self.device
        snap = {"index": self.solves, "bias": {c: float(dv.get_parameter(device=dev, name=f"{c}_bias")) for c in ("l", "r")}, "read": ["x", "Potential"]}
        snap["x"] = np.array(dv.get_node_model_values(device=dev, region="Si", name="x"))
        snap["Potential"] = np.array(dv.get_node_model_values(device=dev, region="Si", name="Potential"))
        try:
            snap["Electrons"] = np.array(dv.get_node_model_values(device=dev, region="Si", name="Electrons"))
            snap["Holes"] = np.array(dv.get_node_model_values(device=dev, region="Si", name="Holes"))
            snap["read"] += ["Electrons", "Holes"]
        except Exception:  # noqa: BLE001  (Poisson-only solve: no carrier solutions yet)
            pass
        snap["ElectricField"] = np.array(dv.get_edge_model_values(device=dev, region="Si", name="ElectricField"))
        snap["read"].append("ElectricField")
        snap["has_DD"] = "Electrons" in snap
        return snap


def build_device(dv, name, positions_um, spacing_nm):
    mesh = f"{name}_mesh"
    dv.create_1d_mesh(mesh=mesh)
    last = len(positions_um) - 1
    for i, (pos, ps) in enumerate(zip(positions_um, spacing_nm)):
        kw = {"tag": "l"} if i == 0 else {"tag": "r"} if i == last else {}
        dv.add_1d_mesh_line(mesh=mesh, pos=pos * LENGTH_SCALE, ps=ps * 1.0e-7, **kw)
    dv.add_1d_contact(mesh=mesh, name="l", tag="l", material="metal")
    dv.add_1d_contact(mesh=mesh, name="r", tag="r", material="metal")
    dv.add_1d_region(mesh=mesh, material="Si", region="Si", tag1="l", tag2="r")
    dv.finalize_mesh(mesh=mesh)
    dv.create_device(mesh=mesh, device=name)
    return mesh


def run_device(dv, name, kind, positions_um, spacing_nm, voltages, expected_solves):
    from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
    from tcad.device.devsim.doping_mapping import apply_doping
    rec = {"name": name, "voltages": voltages, "expected_solves": expected_solves, "production_calls": 0, "solves": 0, "error": None, "converged": False, "writes_ok": False}
    t0 = time.time()
    mesh = None
    obs = None
    try:
        half = max(abs(positions_um[0]), abs(positions_um[-1]))
        state = canonical(kind, half, name)
        mesh = build_device(dv, name, positions_um, spacing_nm)
        n_nodes = len(dv.get_node_model_values(device=name, region="Si", name="x"))
        rec["nodes"] = n_nodes
        rec["dimension"] = int(dv.get_dimension(device=name))
        if n_nodes > NODE_CAP:
            raise RuntimeError(f"TOO_MANY_NODES {n_nodes} > {NODE_CAP}")
        obs = Obs(dv, name)
        obs.install()
        apply_doping(name, "Si", state, length_scale_to_cm=LENGTH_SCALE)
        rec["doping_writes"] = sorted(set(n for _, n in obs.writes))
        rec["donors"], rec["acceptors"], rec["netdoping"] = obs.values.get("Donors"), obs.values.get("Acceptors"), obs.values.get("NetDoping")
        expected = ([0.0, N_DON], [0.0, N_ACC]) if kind == "pn" else ([1.0e16], [0.0])
        rec["writes_ok"] = rec["donors"] == expected[0] and rec["acceptors"] == expected[1]
        rec["production_calls"] = 1
        result = run_pn_junction_iv_sweep(device=name, region="Si", all_contacts=["l", "r"], sweep_contact="l", sweep_voltages=list(voltages), fixed_contacts={"r": 0.0})
        rec["metadata"] = {k: v for k, v in result.metadata.items() if k != "current_convention"}
        rec["has_current_convention_note"] = "current_convention" in result.metadata
        rec["currents"] = [{"V": v, "I_l": float(p.currents["l"]), "I_r": float(p.currents["r"])} for v, p in zip(voltages, result.points)]
        rec["params"] = {n: dv.get_parameter(device=name, region="Si", name=n) for n in ("ElectronCharge", "n_i", "T", "V_t", "mu_n", "mu_p", "taun", "taup", "Permittivity")}
        rec["converged"] = all(math.isfinite(c["I_l"]) and math.isfinite(c["I_r"]) for c in rec["currents"])
        rec["result_metadata_obj"] = result.metadata
    except Exception as exc:  # noqa: BLE001
        rec["error"] = repr(exc)[:500]
        rec["traceback"] = traceback.format_exc()[-1800:]
    finally:
        if obs is not None:
            rec["solves"] = obs.solves
            rec["snaps"] = obs.snaps
            obs.restore()
        try:
            dv.delete_device(device=name)
            if mesh:
                dv.delete_mesh(mesh=mesh)
        except Exception:  # noqa: BLE001
            pass
    rec["wall_s"] = round(time.time() - t0, 2)
    return rec


def snap_at(rec, v, dd=True):
    best = None
    for s in rec.get("snaps", []):
        if abs(s["bias"]["l"] - v) < 1e-12 and abs(s["bias"]["r"]) < 1e-12 and (s["has_DD"] or not dd):
            best = s
    return best


def field_metrics(s):
    x, e = s["x"], s["ElectricField"]
    ok = len(e) == len(x) - 1 and bool(np.all(np.diff(x) > 0))
    if not ok:
        return {"E_max": None, "W_E": None, "ordering_ok": False}
    xm = 0.5 * (x[:-1] + x[1:])
    return {"E_max": float(np.max(np.abs(e))), "W_E": float(R.width_from_field(list(xm), list(np.abs(e)))), "ordering_ok": True}


def current_at(rec, v):
    for c in rec.get("currents", []):
        if abs(c["V"] - v) < 1e-12:
            return c["I_l"]
    return None


def run(out_dir):
    from tcad.characterization.interface import format_current
    from tcad.device.devsim import backend
    dv = backend.require_devsim()
    out = {"plan": "PN_PLAN_v2.md", "devices": {}, "notes": []}
    # 1D unit control (uniform resistor) through the same production path
    ctl = run_device(dv, "ctl", "res", [-1.0, 1.0], [20.0, 20.0], [1.0e-3], 3)
    out["devices"]["control"] = {k: v for k, v in ctl.items() if k not in ("snaps", "result_metadata_obj")}
    unit = {"established_by_control": False, "control_ratio": None, "metadata_unit_1d": "UNREAD", "metadata_dimension_1d": None, "formatted_1d": None}
    if not ctl["error"]:
        p = ctl["params"]
        n0 = 0.5 * (1.0e16 + math.sqrt(1.0e32 + 4 * p["n_i"] ** 2))
        p0 = p["n_i"] ** 2 / n0
        sigma = p["ElectronCharge"] * (p["mu_n"] * n0 + p["mu_p"] * p0)
        i_l, i_r = ctl["currents"][0]["I_l"], ctl["currents"][0]["I_r"]
        ratio = i_l / (sigma * 1.0e-3 / 2.0e-4)
        unit.update({"control_ratio": ratio, "control_I_l": i_l, "control_I_r": i_r, "sigma_S_per_cm": sigma, "theory_sigma_V_over_L": sigma * 1.0e-3 / 2.0e-4,
                     "established_by_control": bool(abs(ratio - 1.0) <= J.TOL["unit_control"] and abs(i_l + i_r) <= 1.0e-6 * abs(i_l)),
                     "metadata_unit_1d": ctl["metadata"].get("current_unit"), "metadata_dimension_1d": ctl["metadata"].get("device_dimension"),
                     "formatted_1d": format_current(i_l, ctl["result_metadata_obj"]), "metadata_has_2D_note": ctl["has_current_convention_note"]})
    try:
        e6j = json.load(open(E6J_JSON))
        unit["e6j_checks"] = len(e6j["checks"])
        unit["e6j_failed_checks"] = sum(1 for c in e6j["checks"] if not c["pass"])
    except Exception as exc:  # noqa: BLE001
        unit["e6j_failed_checks"] = None
        unit["e6j_error"] = repr(exc)[:200]
    metrics = {"unit": unit, "devices": {"control": {"production_calls": ctl["production_calls"], "solves": ctl["solves"], "expected_solves": 3, "dimension": ctl.get("dimension"),
                                                     "writes_ok": ctl["writes_ok"], "error": ctl["error"], "converged": ctl["converged"]}},
               "J": {}, "Emax": {}, "WE": {}, "ref": {}, "ref_E": {}, "minority": {"s_um": S_UM, "dev": [None] * 3, "ref": [None] * 3}}
    npz = {}
    if unit["established_by_control"]:
        recs = {}
        for k in range(3):
            level = f"L{k}"
            sp = [s / 2 ** k for s in SPACING_NM]
            for tag, volts in (("fwd", FWD), ("rev", REV)):
                name = f"{level}_{tag}"
                recs[name] = run_device(dv, name, "pn", POSITIONS_UM, sp, volts, 2 + len(volts))
                d = recs[name]
                out["devices"][name] = {k_: v_ for k_, v_ in d.items() if k_ not in ("snaps", "result_metadata_obj")}
                metrics["devices"][name] = {k_: d.get(k_) for k_ in ("production_calls", "solves", "expected_solves", "dimension", "writes_ok", "error", "converged")}
            J_l, E_l, W_l = {}, {}, {}
            for v in (0.3, 0.5, 0.6):
                J_l[key(v)] = current_at(recs[f"{level}_fwd"], v)
            for v in (-0.5, -1.0):
                J_l[key(v)] = current_at(recs[f"{level}_rev"], v)
            for v in (0.0, -1.0):
                s = snap_at(recs[f"{level}_rev"], v)
                fm = field_metrics(s) if s else {"E_max": None, "W_E": None}
                E_l[key(v)], W_l[key(v)] = fm["E_max"], fm["W_E"]
            metrics["J"][level], metrics["Emax"][level], metrics["WE"][level] = J_l, E_l, W_l
        # reference from the production constants read on the L2 device
        any_params = next((r["params"] for r in recs.values() if r.get("params")), None)
        if any_params:
            p = R.params(any_params["ElectronCharge"], any_params["n_i"], any_params["T"], any_params["mu_n"], any_params["mu_p"], any_params["taun"], any_params["taup"],
                         any_params["Permittivity"], N_ACC, N_DON, HALF_UM * 1e-4, HALF_UM * 1e-4)
            out["reference_parameters"] = {k_: v_ for k_, v_ in p.items()}
            refs = {}
            for v in (0.3, 0.5, 0.6, -0.5, -1.0, 0.0):
                refs[key(v)] = R.reference(p, v)
            metrics["ref"] = {k_: refs[k_] for k_ in ("0.5", "0.6", "-0.5", "-1.0")}
            metrics["ref_E"] = {key(v): {"E_max": R.depletion(p, v)["E_max"], "W": R.depletion(p, v)["W"]} for v in (0.0, -1.0)}
            out["reference_all"] = refs
            s = snap_at(recs["L2_fwd"], 0.6)
            if s is not None and "Holes" in s:
                x_n = R.depletion(p, 0.6)["x_n"]
                p_n0 = p["n_i"] ** 2 / p["N_D"]
                metrics["minority"]["dev"] = [float(np.interp(x_n + sv * 1e-4, s["x"], s["Holes"]) - p_n0) for sv in S_UM]
                metrics["minority"]["ref"] = [float(R.minority_excess_profile(p, 0.6, sv * 1e-4)) for sv in S_UM]
        for name, d in recs.items():
            for s in d.get("snaps", []):
                if s["has_DD"]:
                    for arr in ("x", "Potential", "Electrons", "Holes", "ElectricField"):
                        npz[f"{name}__{s['index']}__bias{s['bias']['l']:+.3f}__{arr}"] = s[arr]
    out["metrics"] = {k_: v_ for k_, v_ in metrics.items()}
    verdict = J.judge(metrics)
    out["verdicts"] = verdict
    out["table"] = {}
    for level, jl in metrics["J"].items():
        out["table"][level] = {v: {"I_l_raw": jl.get(v), "J_model": (out.get("reference_all", {}).get(v) or {}).get("J_model"),
                                   "J_diff": (out.get("reference_all", {}).get(v) or {}).get("J_diff"), "J_srh": (out.get("reference_all", {}).get(v) or {}).get("J_srh"),
                                   "rel_err": J.rel(jl.get(v), (out.get("reference_all", {}).get(v) or {}).get("J_model")) if (out.get("reference_all", {}).get(v) or {}).get("J_model") else None}
                               for v in ("0.3", "0.5", "0.6", "-0.5", "-1.0")}
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "pn_1d_diagnostic.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, indent=1, default=str)
        if npz:
            np.savez_compressed(os.path.join(out_dir, "states.npz"), **npz)
    for c, v in verdict.items():
        print(c, v["verdict"], [x["name"] for x in v["checks"] if not x["pass"]][:6])
    print("total solves:", sum(d.get("solves", 0) for d in out["devices"].values()), "leaked devices:", list(dv.get_device_list()))
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
