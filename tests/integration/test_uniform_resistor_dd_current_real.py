#!/usr/bin/env python3
"""Low-field drift-diffusion current of a uniformly doped (1e16 cm^-3 donors, ACTIVE) Si resistor through the PRODUCTION path (Batch 7H-E6I).
Criteria, fixed before the run: docs/audits/2026-10-01-batch7h-e6i-uniform-resistor-dd/CRITERIA.md. Judge: scripts/resistor_judge.py.

usage: test_uniform_resistor_dd_current_real.py [out_dir]   (writes resistor_dd.json there; exit code 0 only if every criterion passes)

Path per bias (fresh device each, exactly what the GUI does): import_process_result -> apply_doping(canonical WaferStateV2) ->
run_pn_junction_iv_sweep(sweep_voltages=[V], fixed_contacts={gnd: 0}). DEVSIM public API only; no tolerance / model / order change."""
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "docs/audits/2026-10-01-batch7h-e6i-uniform-resistor-dd"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AUDIT / "scripts"))
sys.path.insert(0, str(ROOT / "docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/scripts"))

from resistor_judge import BIASES, judge, theory  # noqa: E402

EXPECTED_PARAMS = {"ElectronCharge": 1.6e-19, "n_i": 1.0e10, "T": 300.0, "mu_n": 400.0, "mu_p": 200.0, "taun": 1.0e-8, "taup": 1.0e-8}
DONOR, ACCEPTOR = 1.0e16, 0.0
H_CM, L_CM = 0.5e-4, 2.0e-4
LENGTH_SCALE = 1.0e-4
MESHES = [("uniform", 8)] + [(f, n) for f in ("one_sided", "two_sided") for n in (8, 16, 32)]
MESSAGEBOX = ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel")
DOPING_MODELS = {"Donors", "Acceptors", "NetDoping"}


def mesh_arrays(family, n):
    from test_mesh_gate_poisson_transition_real import build
    P, T, _ = build(family, n)
    P = P.copy()
    P[:, 0] -= 1.0          # exact binary shifts into the canonical frame x in [-1, 1], y in [-0.5, 0] um
    P[:, 1] -= 0.5
    return P, T


def write_mesh(P, T, tag):
    import meshio
    from tcad.backends.viennaps import session
    si = int(session.require_viennaps().Material.Si)
    path = Path(tempfile.mkdtemp(prefix="e6i_")) / f"{tag}.vtu"
    meshio.write(str(path), meshio.Mesh(P, [("triangle", T)], cell_data={"Material": [np.full(len(T), si, dtype=np.int32)]}))
    return str(path)


def canonical(path, chemical_state):
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_uniform_doping
    from tcad.physics.wafer_state_accumulation import advance_wafer_state, initial_wafer_state_from_recipe
    base = initial_wafer_state_from_recipe({"x_extent_um": 2.0, "silicon_depth_um": 0.5, "grid_delta_um": 0.25})
    pr = build_process_result({"final_mesh": path, "snapshots": []})
    doped = apply_uniform_doping(pr, donor_by_region_cm3={"Si": DONOR}, acceptor_by_region_cm3={"Si": ACCEPTOR}, chemical_state=chemical_state)
    return advance_wafer_state(base, doped, "doping"), doped


class Observer:
    """Pass-through counter of devsim.solve and doping writes (the real calls still happen)."""

    def __init__(self, dv):
        self.dv, self.solves, self.writes, self.values, self._orig = dv, 0, [], {}, {}

    def install(self):
        for n in ("solve", "node_model", "set_node_values"):
            self._orig[n] = getattr(self.dv, n)
        o = dict(self._orig)

        def solve(*a, **k):
            self.solves += 1
            return o["solve"](*a, **k)

        def node_model(*a, **k):
            if k.get("name") in DOPING_MODELS:
                self.writes.append(("node_model", k["name"]))
            return o["node_model"](*a, **k)

        def set_node_values(*a, **k):
            if k.get("name") in DOPING_MODELS:
                self.writes.append(("set_node_values", k["name"]))
                self.values[k["name"]] = sorted(set(k.get("values", [])))
            return o["set_node_values"](*a, **k)
        self.dv.solve, self.dv.node_model, self.dv.set_node_values = solve, node_model, set_node_values

    def restore(self):
        for n, fn in self._orig.items():
            setattr(self.dv, n, fn)


def one_bias(dv, doped, state, voltage, tag):
    from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
    from tcad.device.devsim.doping_mapping import apply_doping
    from tcad.device.devsim.mesh_import import import_process_result
    from devsim.python_packages.simple_physics import ece_name as ECE, hce_name as HCE
    obs = Observer(dv)
    obs.install()
    imported = None
    t0 = time.time()
    try:
        imported = import_process_result(doped, mesh_name=f"{tag}_mesh", device_name=f"{tag}_device", contact_regions=["Si"], contact_axis="x",
                                         length_scale_to_cm=LENGTH_SCALE)
        dev, reg = imported.device, "Si"
        c_min, c_max = imported.contacts[0], imported.contacts[1]
        apply_doping(dev, reg, state, length_scale_to_cm=LENGTH_SCALE)
        result = run_pn_junction_iv_sweep(device=dev, region=reg, all_contacts=imported.contacts, sweep_contact=c_max, sweep_voltages=[voltage],
                                          fixed_contacts={c_min: 0.0})
        point = result.points[0]
        params = {n: dv.get_parameter(device=dev, region=reg, name=n) for n in ("ElectronCharge", "n_i", "T", "V_t", "mu_n", "mu_p", "taun", "taup", "Permittivity")}
        cur = {}
        for contact in (c_min, c_max):
            cur[contact] = {"e": dv.get_contact_current(device=dev, contact=contact, equation=ECE), "h": dv.get_contact_current(device=dev, contact=contact, equation=HCE)}
        g = lambda name: np.array(dv.get_node_model_values(device=dev, region=reg, name=name))  # noqa: E731
        x, psi, n, p, vol, usrh = g("x"), g("Potential"), g("Electrons"), g("Holes"), g("NodeVolume"), g("USRH")
        th = theory(DONOR, ACCEPTOR, params["n_i"], params["ElectronCharge"], params["mu_n"], params["mu_p"], H_CM, L_CM)
        x0 = x.min()
        psi_ref = float(np.mean(psi[x == x0]))
        psi_lin = np.abs(psi - (psi_ref + voltage * (x - x0) / (x.max() - x0)))
        states_finite = bool(all(np.all(np.isfinite(a)) for a in (x, psi, n, p, vol, usrh)))
        rec = {"voltage": voltage, "contacts": [c_min, c_max], "solves": obs.solves, "wall_s": round(time.time() - t0, 2), "params": params,
               "I_max_total": float(point.currents[c_max]), "I_min_total": float(point.currents[c_min]),
               "Ie_max": float(cur[c_max]["e"]), "Ih_max": float(cur[c_max]["h"]), "Ie_min": float(cur[c_min]["e"]), "Ih_min": float(cur[c_min]["h"]),
               "finite_arrays": states_finite, "nodes": int(len(x)),
               "n_uniformity": float(np.max(np.abs(n / th["n0"] - 1.0))), "p_min_over_p0": float(np.min(p) / th["p0"]), "p_max_over_p0": float(np.max(p) / th["p0"]),
               "psi_lin": float(np.max(psi_lin) / max(abs(voltage), 1.0e-3)),
               "max_abs_USRH": float(np.max(np.abs(usrh))), "recombination_current_A_per_cm": float(params["ElectronCharge"] * np.sum(usrh * vol)),
               "metadata": dict(result.metadata),
               "doping_writes": sorted(set(nm for _, nm in obs.writes)), "donors": obs.values.get("Donors"), "acceptors": obs.values.get("Acceptors"),
               "netdoping": obs.values.get("NetDoping"), "theory": th}
        return rec
    finally:
        obs.restore()
        if imported is not None:
            dv.delete_device(device=imported.device)
            dv.delete_mesh(mesh=imported.mesh)


def gui_part(dv, path, direct):
    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui
    modal = []
    originals = {n: getattr(gui.messagebox, n) for n in MESSAGEBOX if hasattr(gui.messagebox, n)}
    for n in originals:
        setattr(gui.messagebox, n, lambda *a, _n=n, **k: modal.append((_n, a[:2])))
    app = gui.TCADApplication()
    out = {}
    try:
        app.withdraw()
        app.meas_voltage_var.set(1.0e-3)
        app.meas_axis_var.set("x")
        app.meas_source_pin.set("max")
        for label in ("ACTIVE", "CHEMICAL", "UNKNOWN"):
            state, doped = canonical(path, label)
            app.wafer_state, app.last_doped_result, app.last_final_mesh = state, doped, path
            obs = Observer(dv)
            log0, modal0 = app.log.get("1.0", "end-1c"), len(modal)
            obs.install()
            try:
                app.run_measurement()
            finally:
                obs.restore()
            log = app.log.get("1.0", "end-1c")[len(log0):]
            # E6J: the GUI now prints the unit of the 2D per-unit-depth current ("A/cm"); the number is still parsed and compared
            m = re.search(r"Voltage source pin: (\S+) = ([-+0-9.]+) V -> I = ([-+0-9.eE]+) A/cm\s+Multimeter \(GND\) pin: (\S+) = [-+0-9.]+ V -> I = ([-+0-9.eE]+) A/cm", log)
            status = app.last_physics_status if isinstance(app.last_physics_status, dict) else None
            out[label] = {"solves": obs.solves, "doping_writes": len(obs.writes), "measurement_block": "DEVSIM MEASUREMENT" in log,
                          "source_pin": m.group(1) if m else None, "source_V": m.group(2) if m else None,
                          "source_I_A_printed": float(m.group(3)) if m else None, "gnd_I_A_printed": float(m.group(5)) if m else None,
                          "dialogs": [d[0] for d in modal[modal0:]], "dialog_text": [str(d[1])[:160] for d in modal[modal0:]],
                          "physics_status_resolution": (status or {}).get("resolution"), "physics_status_reason": (status or {}).get("reason_code"),
                          "leaked_devices": list(dv.get_device_list())}
    finally:
        app.destroy()
        for n, fn in originals.items():
            setattr(gui.messagebox, n, fn)
    a = out["ACTIVE"]
    d_src, d_gnd = direct["I_max_total"], direct["I_min_total"]
    checks = [
        ("GUI ACTIVE prints a measurement block", a["measurement_block"] and a["source_I_A_printed"] is not None),
        ("GUI source current equals direct path (1e-6, printed digits)", a["source_I_A_printed"] is not None and abs(a["source_I_A_printed"] - d_src) <= 1e-6 * abs(d_src)),
        ("GUI ground current equals direct path (1e-6)", a["gnd_I_A_printed"] is not None and abs(a["gnd_I_A_printed"] - d_gnd) <= 1e-6 * abs(d_gnd)),
        ("GUI ACTIVE ran >= 1 solve and no dialog error", a["solves"] >= 1 and "showerror" not in a["dialogs"] and not a["leaked_devices"]),
    ]
    for label in ("CHEMICAL", "UNKNOWN"):
        b = out[label]
        checks.append((f"GUI {label}: 0 solves, 0 doping writes, no measurement block, no info dialog, no leaked device, UNSUPPORTED_BY_MODEL",
                       b["solves"] == 0 and b["doping_writes"] == 0 and not b["measurement_block"] and "showinfo" not in b["dialogs"]
                       and not b["leaked_devices"] and b["physics_status_resolution"] == "UNSUPPORTED_BY_MODEL"))
    return out, [{"name": n, "pass": bool(ok)} for n, ok in checks]


def run(out_dir):
    from tcad.device.devsim import backend
    dv = backend.require_devsim()
    meshes, raw = {}, []
    first_direct = None
    gui_path = None
    for family, n in MESHES:
        key = f"{family}_{n}"
        P, T = mesh_arrays(family, n)
        path = write_mesh(P, T, key)
        if key == "one_sided_8":
            gui_path = path
        state, doped = canonical(path, "ACTIVE")
        biases = {}
        for label, v in BIASES.items():
            rec = one_bias(dv, doped, state, v, f"{key}_{label.replace('+', 'p').replace('-', 'm')}")
            biases[label] = rec
            print(key, label, "I_max %.6e I_min %.6e Ie_max %.6e Ih_max %.3e solves %d" % (rec["I_max_total"], rec["I_min_total"], rec["Ie_max"], rec["Ih_max"], rec["solves"]), flush=True)
        meshes[key] = {"family": family, "n": n, "triangles": int(len(T)), "biases": biases}
    p0 = meshes["uniform_8"]["biases"]["+1mV"]["params"]
    th = theory(DONOR, ACCEPTOR, p0["n_i"], p0["ElectronCharge"], p0["mu_n"], p0["mu_p"], H_CM, L_CM)
    verdict = judge(th, meshes)
    extra = []
    for key, m in meshes.items():
        for label, rec in m["biases"].items():
            ok_params = all(rec["params"][k] == v for k, v in EXPECTED_PARAMS.items())
            ok_doping = rec["donors"] == [DONOR] and rec["acceptors"] == [ACCEPTOR] and rec["netdoping"] == [DONOR - ACCEPTOR] and rec["solves"] == 3
            extra.append({"name": f"{key} {label}: production constants as pre-registered, canonical doping values written, 3 solves", "pass": bool(ok_params and ok_doping)})
    gui, gui_checks = gui_part(dv, gui_path, meshes["one_sided_8"]["biases"]["+1mV"])
    leaked = list(dv.get_device_list())
    final = bool(verdict["pass"] and all(c["pass"] for c in extra) and all(c["pass"] for c in gui_checks) and not leaked)
    summary = {"pass": final, "theory": th, "meshes": meshes, "judge": verdict, "input_checks": extra, "gui": gui, "gui_checks": gui_checks, "leaked_devices": leaked,
               "expected_params": EXPECTED_PARAMS}
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "resistor_dd.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(summary, f, indent=1, default=str)
    print("theory:", json.dumps(th))
    print("judge failed checks:", json.dumps(verdict["failed"], default=str)[:4000])
    print("input failed:", [c["name"] for c in extra if not c["pass"]], "gui failed:", [c["name"] for c in gui_checks if not c["pass"]])
    print("UNIFORM RESISTOR DD CURRENT " + ("PASSED" if final else "FAILED"))
    return 0 if final else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
