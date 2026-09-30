#!/usr/bin/env python3
"""Batch 7H-E6J representative GUI check of the 2D DD current unit contract: one E6I supported input (one_sided n = 8, +1 mV, uniform ACTIVE 1e16 donors)
plus the CHEMICAL / UNKNOWN controls. Reuses the E6I helpers; does NOT repeat the E6I matrix.
usage: test_gui_current_unit_contract_real.py [out_dir]   (writes gui_unit_contract.json; exit 0 only if every check passes)"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_uniform_resistor_dd_current_real as e6i  # noqa: E402

E6I_JSON = ROOT / "docs/audits/2026-10-01-batch7h-e6i-uniform-resistor-dd/data/remote_run_36756889121/remote-run-23/outputs/e6i_out/resistor_dd.json"
MESSAGEBOX = e6i.MESSAGEBOX
GUI_LINE = re.compile(r"Voltage source pin: (\S+) = ([-+0-9.]+) V -> I = ([-+0-9.eE]+) (\S+)\s+Multimeter \(GND\) pin: (\S+) = [-+0-9.]+ V -> I = ([-+0-9.eE]+) (\S+)")
LEGACY_A = re.compile(r"I = [-+0-9.eE]+ A(\s|$)")


def run(out_dir):
    from tcad.device.devsim import backend
    dv = backend.require_devsim()
    checks = []

    def check(name, ok, detail=None):
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    P, T = e6i.mesh_arrays("one_sided", 8)
    path = e6i.write_mesh(P, T, "e6j_one_sided_8")
    state, doped = e6i.canonical(path, "ACTIVE")
    direct = e6i.one_bias(dv, doped, state, 1.0e-3, "e6j_direct")
    e6i_ref = json.load(open(E6I_JSON))["meshes"]["one_sided_8"]["biases"]["+1mV"]
    th = direct["theory"]
    check("direct path entered production DD (3 solves)", direct["solves"] == 3, direct["solves"])
    check("raw I_max unchanged vs committed E6I value (1e-12 relative)", abs(direct["I_max_total"] - e6i_ref["I_max_total"]) <= 1e-12 * abs(e6i_ref["I_max_total"]),
          [direct["I_max_total"], e6i_ref["I_max_total"]])
    check("raw I_min unchanged vs committed E6I value (1e-12 relative)", abs(direct["I_min_total"] - e6i_ref["I_min_total"]) <= 1e-12 * abs(e6i_ref["I_min_total"]),
          [direct["I_min_total"], e6i_ref["I_min_total"]])
    check("raw I_max equals theory G V (1e-9 relative)", abs(direct["I_max_total"] - th["I_ref"]) <= 1e-9 * th["I_ref"], [direct["I_max_total"], th["I_ref"]])
    md = direct["metadata"]
    check("sweep metadata carries machine-readable unit", md.get("current_unit") == "A/cm" and md.get("current_normalization") == "per_out_of_plane_depth"
          and md.get("device_dimension") == 2, {k: md.get(k) for k in ("current_unit", "current_normalization", "device_dimension")})
    check("explicit-depth conversion CONTROL (test depth 1 um = 1e-4 cm): 1.6e-4 A/cm x 1e-4 cm = 1.6e-8 A", abs(direct["I_max_total"] * 1.0e-4 - 1.6e-8) <= 1e-17,
          direct["I_max_total"] * 1.0e-4)

    import tkinter  # noqa: F401
    import tcad_2d_stagewise as gui
    modal = []
    originals = {n: getattr(gui.messagebox, n) for n in MESSAGEBOX if hasattr(gui.messagebox, n)}
    for n in originals:
        setattr(gui.messagebox, n, lambda *a, _n=n, **k: modal.append((_n, a[:2])))
    app = gui.TCADApplication()
    gui_out = {}
    try:
        app.withdraw()
        app.meas_voltage_var.set(1.0e-3)
        app.meas_axis_var.set("x")
        app.meas_source_pin.set("max")
        for label in ("ACTIVE", "CHEMICAL", "UNKNOWN"):
            st, dp = e6i.canonical(path, label)
            app.wafer_state, app.last_doped_result, app.last_final_mesh = st, dp, path
            obs = e6i.Observer(dv)
            log0, modal0 = app.log.get("1.0", "end-1c"), len(modal)
            obs.install()
            try:
                app.run_measurement()
            finally:
                obs.restore()
            log = app.log.get("1.0", "end-1c")[len(log0):]
            m = GUI_LINE.search(log)
            ps = app.last_physics_status if isinstance(app.last_physics_status, dict) else None
            fb = (ps or {}).get("first_blocked_node") or {}
            gui_out[label] = {"log": log, "solves": obs.solves, "doping_writes": len(obs.writes), "dialogs": [d[0] for d in modal[modal0:]],
                              "printed": list(m.groups()) if m else None, "legacy_A_line_present": bool(LEGACY_A.search(log)),
                              "leaked_devices": list(dv.get_device_list()),
                              "physics_status": None if ps is None else {
                                  "resolution": ps.get("resolution"), "reason_code": ps.get("reason_code"),
                                  "entry_parameters": [e.get("parameter") for e in ps.get("entries", [])],
                                  "entry_notes": [str(e.get("note"))[:200] for e in ps.get("entries", [])],
                                  "blocked_nodes": ps.get("blocked_nodes"), "total_nodes": ps.get("total_nodes"),
                                  "first_blocked_reason": fb.get("reason"), "notes": ps.get("notes")}}
    finally:
        app.destroy()
        for n, fn in originals.items():
            setattr(gui.messagebox, n, fn)
    a = gui_out["ACTIVE"]
    p = a["printed"]
    check("GUI ACTIVE: block printed with source and ground lines", p is not None and a["solves"] >= 1 and not a["leaked_devices"], a["printed"])
    check("GUI ACTIVE: unit printed is A/cm on both lines", bool(p) and p[3] == "A/cm" and p[6] == "A/cm", p)
    check("GUI ACTIVE: no legacy plain-A current line", not a["legacy_A_line_present"])
    check("GUI ACTIVE: per-unit-depth note shown", "per unit out-of-plane depth" in a["log"])
    check("GUI ACTIVE: source pin / voltage", bool(p) and p[0] == "Si_xmax" and abs(float(p[1]) - 1.0e-3) < 1e-9, p)
    check("GUI ACTIVE: printed source current equals direct raw (1e-6, printed digits)", bool(p) and abs(float(p[2]) - direct["I_max_total"]) <= 1e-6 * abs(direct["I_max_total"]), p)
    check("GUI ACTIVE: printed ground current equals direct raw (1e-6), sign kept", bool(p) and abs(float(p[5]) - direct["I_min_total"]) <= 1e-6 * abs(direct["I_min_total"])
          and float(p[5]) < 0 < float(p[2]), p)
    for label in ("CHEMICAL", "UNKNOWN"):
        b = gui_out[label]
        ps = b["physics_status"] or {}
        check(f"GUI {label}: 0 solves, 0 doping writes, no measurement block, no numeric current line, no leaked device",
              b["solves"] == 0 and b["doping_writes"] == 0 and "DEVSIM MEASUREMENT" not in b["log"] and b["printed"] is None and not LEGACY_A.search(b["log"])
              and not b["leaked_devices"], {k: b[k] for k in ("solves", "doping_writes", "printed")})
        check(f"GUI {label}: physics_status resolution UNSUPPORTED_BY_MODEL and a real entry names the activation state",
              ps.get("resolution") == "UNSUPPORTED_BY_MODEL" and "dopant_activation_state" in (ps.get("entry_parameters") or [])
              and bool(ps.get("blocked_nodes")) and ps.get("blocked_nodes") == ps.get("total_nodes"), ps)
    summary = {"pass": all(c["pass"] for c in checks), "checks": checks, "direct": {k: direct[k] for k in ("I_max_total", "I_min_total", "Ie_max", "Ih_max", "solves", "metadata", "theory")},
               "gui": gui_out}
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "gui_unit_contract.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(summary, f, indent=1, default=str)
    for c in checks:
        print(("PASS " if c["pass"] else "FAIL ") + c["name"])
    print("GUI CURRENT UNIT CONTRACT " + ("PASSED" if summary["pass"] else "FAILED"))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else None))
