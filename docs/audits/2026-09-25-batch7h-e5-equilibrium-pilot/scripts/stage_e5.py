"""Batch 7H-E5 remote worker (PLAN sections 2-6). Runs {D2D, D1D_J0, D1D_J1} x {S0, S12}, 6 independent runs, each its
own device, own precision setting, own solve calls, own JSON. devsim.solve is NOT trapped in this batch -- unlike
7H-E2/E3/E4, running real solves is the whole point. usage: stage_e5.py <out dir>"""
import os
import sys
import time
import traceback

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
E1S = os.path.join(HERE, "..", "..", "2026-09-24-batch7h-e1-production-step-junction-equivalence", "scripts")
sys.path.insert(0, os.path.abspath(E1S))
import common_e1 as ce  # noqa: E402
import shadow_e1 as se1  # noqa: E402  (measure(): qf/mass-action/currents, reused after DD succeeds)
import devices_e5 as de5  # noqa: E402

PLAN_SHA = "924395fb86a72658853a9b8ffd7827cdb0ddf6c1473d55609af09764ce8802fa"
CUTS_UM = [-0.25, -0.10, 0.0, 0.10, 0.25]
T0 = time.time()


def log(msg):
    print(f"[e5 {time.time() - T0:8.1f}s] {msg}", flush=True)


def run_one(dv, work, label, kind_device, kind_doping, variant):
    """One of the 6 registered runs. Returns the result dict; never raises (errors are captured in it)."""
    out = {"label": label, "device_kind": kind_device, "doping_kind": kind_doping, "variant": variant, "solve_calls": []}
    t0 = time.time()
    try:
        if variant == "S12":
            dv.set_parameter(name="extended_model", value=True)
            dv.set_parameter(name="extended_equation", value=True)
        out["flags"] = se1.flags(dv)
        device = f"e5_{label}"
        region = "Si"
        if kind_device == "2D":
            imp, ident = de5.import_e4_candidate(work)
            out["mesh_identity"] = ident
            if not ident["equal"]:
                out["stop"] = "MESH_INPUT_IDENTITY_FAIL"
                return out
            device = imp.device
            contacts = sorted(imp.contacts)  # Si_xmin, Si_xmax -> xmin first, matches shadow_e1.measure()'s convention
        else:
            xs = de5.grid_1d_um(de5.H_UM, kind_doping)
            contacts = de5.build_1d(dv, xs, device)
            out["mesh_1d"] = {"n_nodes": len(xs), "h_um": de5.H_UM, "x_half_um": de5.X_HALF_UM}
        out["contacts"] = contacts
        out["doping"] = de5.write_doping(dv, device, region, kind_doping)

        from tcad.device.devsim.semiconductor_equation import setup_semiconductor_potential_equation, setup_drift_diffusion_equation
        setup_semiconductor_potential_equation(device, region, contacts, 300.0)
        c1 = de5.solve_call(dv, out["solve_calls"], absolute_error=1.0, relative_error=1e-6, maximum_iterations=100)
        out["poisson_converged"] = c1["converged"]
        if not c1["converged"]:
            out["status"] = "POISSON_NOT_CONVERGED"
            out["poisson_measure"] = de5.measure_poisson(dv, device, region, contacts)
            out["cut_profile_poisson_only"] = de5.cut_profile(dv, device, region, CUTS_UM)
            out["doping_integrals"] = de5.doping_integrals(dv, device, region, kind_doping)
        else:
            out["poisson_measure"] = de5.measure_poisson(dv, device, region, contacts)
            setup_drift_diffusion_equation(device, region, contacts)
            c2 = de5.solve_call(dv, out["solve_calls"], absolute_error=1e10, relative_error=1e-6, maximum_iterations=100)
            out["dd_converged"] = c2["converged"]
            if not c2["converged"]:
                out["status"] = "DD_NOT_CONVERGED"
                out["cut_profile"] = de5.cut_profile(dv, device, region, CUTS_UM)
                out["doping_integrals"] = de5.doping_integrals(dv, device, region, kind_doping)
            else:
                m = se1.measure(dv, device, contacts)
                out["equilibrium_measure"] = m
                out["cut_profile"] = de5.cut_profile(dv, device, region, CUTS_UM)
                out["doping_integrals"] = de5.doping_integrals(dv, device, region, kind_doping)
                y_bad = out["poisson_measure"].get("y_symmetry_max_spread_V")
                phys_ok = (bool(m.get("positive_finite")) and (y_bad is None or y_bad <= 1e-6)
                          and out["doping_integrals"]["all_finite"]
                          and m["psi_contact_V"][contacts[0]] != m["psi_contact_V"][contacts[1]])
                out["status"] = "CONVERGED_OK" if phys_ok else "CONVERGED_BUT_PHYSICALLY_INVALID"
        out["analytic_reference"] = de5.analytic_reference(dv, device, region)
        if kind_device == "2D":
            dv.delete_device(device=device)
            dv.delete_mesh(mesh=imp.mesh)
        else:
            dv.delete_device(device=device)
            dv.delete_mesh(mesh="m_" + device)
    except Exception as e:  # noqa: BLE001
        out["error"] = repr(e)[:500]
        out["traceback"] = traceback.format_exc()[-3000:]
        out["status"] = out.get("status", "ERROR")
    finally:
        if variant == "S12":   # only S12 ever set these True; restore E1's own "leave S0 untouched/unset" convention
            try:
                dv.set_parameter(name="extended_model", value=False)
                dv.set_parameter(name="extended_equation", value=False)
            except Exception:  # noqa: BLE001
                pass
    out["wall_s"] = round(time.time() - t0, 1)
    log(f"{label}: status={out.get('status')} poisson_converged={out.get('poisson_converged')} "
        f"dd_converged={out.get('dd_converged')} calls={len(out['solve_calls'])} ({out['wall_s']}s)")
    return out


def main():
    outd = os.path.abspath(sys.argv[1])
    os.makedirs(outd, exist_ok=True)
    import devsim as dv
    results = {"plan_sha256_expected": PLAN_SHA, "runs": {}}
    total_calls = 0
    for kind_device, kind_doping, dev_label in (("2D", "J0", "D2D"), ("1D", "J0", "D1D_J0"), ("1D", "J1", "D1D_J1")):
        for variant in ("S0", "S12"):
            label = f"{dev_label}_{variant}"
            log(f"===== {label} =====")
            r = run_one(dv, outd, label, kind_device, kind_doping, variant)
            results["runs"][label] = r
            total_calls += len(r.get("solve_calls", []))
            ce.dump_strict(r, os.path.join(outd, f"e5_{label}.json"))
    results["devices_left"] = list(dv.get_device_list())
    results["total_solve_calls"] = total_calls
    ce.dump_strict(results, os.path.join(outd, "e5_result.json"))
    log(f"done: devices_left={results['devices_left']} total_solve_calls={total_calls}")
    return 0 if not results["devices_left"] else 1


if __name__ == "__main__":
    sys.exit(main())
