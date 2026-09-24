"""Batch 7H-E1 step B: AUDIT-ONLY SHADOW (never production), one variant per subprocess, remote only.

Same mesh file (sha256 checked) imported with the same production arguments into a new device; node coordinates and
element list must hash-equal the control device; Donors / Acceptors / NetDoping are written with the public DEVSIM API
from the canonical per-node arrays recorded during the control (sha256 checked, node order proven). Then the UNMODIFIED
production routine run_pn_junction_iv_sweep runs exactly as the GUI calls it. devsim.solve is wrapped only to snapshot
after each call. Measurements (C0/C1/C2/C3) follow the 7H-D2 worker definitions, rewritten for this device's contact
names (worker_d2.measure hard-codes contacts 'left'/'right').
usage: shadow_e1.py <work dir> <S0|S12>   -> <work>/shadow_<V>.json, <work>/shadow_<V>_states.npz"""
import json
import os
import sys
import time
import traceback

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import common_e1 as ce  # noqa: E402

UM, Q = 1e-4, 1.6e-19
CUTS_UM = (-0.25, -0.10, 0.0, 0.10, 0.25)
FLAGS = ("extended_model", "extended_equation", "extended_solver")
PARAMS = ("Permittivity", "ElectronCharge", "n_i", "T", "kT", "V_t", "mu_n", "mu_p", "n1", "p1", "taun", "taup")


def flags(dv):
    out = {}
    for n in FLAGS:
        try:
            out[n] = dv.get_parameter(name=n)
        except Exception as e:  # noqa: BLE001
            out[n] = "UNSET: " + str(e).strip()[:50]
    return out


def measure(dv, dev, contacts):
    nv = lambda n: np.array(dv.get_node_model_values(device=dev, region="Si", name=n))  # noqa: E731
    ev = lambda n: np.array(dv.get_edge_model_values(device=dev, region="Si", name=n))  # noqa: E731
    x, psi, n, p = nv("x"), nv("Potential"), nv("Electrons"), nv("Holes")
    usrh, vol = nv("USRH"), nv("NodeVolume")
    for m in ("x", "node_index"):
        dv.edge_from_node_model(device=dev, region="Si", node_model=m)
    n0, n1 = ev("node_index@n0").astype(int), ev("node_index@n1").astype(int)
    cpl = ev("EdgeCouple")
    Fn, Fp = ev("ElectronCurrent") * cpl, ev("HoleCurrent") * cpl
    out = {"C0": {}, "C1": {}, "C2": {}, "C3": {}}
    for c in contacts:
        e_ = float(dv.get_contact_current(device=dev, contact=c, equation="ElectronContinuityEquation"))
        h_ = float(dv.get_contact_current(device=dev, contact=c, equation="HoleContinuityEquation"))
        out["C0"][c] = {"n": e_, "p": h_, "total": e_ + h_}
    for c, cset in ((contacts[0], x == x.min()), (contacts[1], x == x.max())):
        a, b = cset[n0], cset[n1]
        s = np.where(a & ~b, 1.0, np.where(b & ~a, -1.0, 0.0))
        out["C1"][c] = {"total": float(np.sum(s * (Fn + Fp))), "n_edges": int(np.count_nonzero(s))}
    xum = x / UM
    for xc in CUTS_UM:
        L = xum < xc
        a, b = L[n0], L[n1]
        s = np.where(a & ~b, 1.0, np.where(b & ~a, -1.0, 0.0))
        out["C2"][f"{xc:+.2f}"] = {"n": float(np.sum(s * Fn)), "p": float(np.sum(s * Fp)), "total": float(np.sum(s * (Fn + Fp))),
                                   "n_edges": int(np.count_nonzero(s)), "nodes_on_cut": int(np.sum(xum == xc))}
    ks = [f"{xc:+.2f}" for xc in CUTS_UM]
    for ka, kb, xa, xb in zip(ks[:-1], ks[1:], CUTS_UM[:-1], CUTS_UM[1:]):
        m = (xum >= xa) & (xum < xb)
        g = float(Q * np.sum(usrh[m] * vol[m]))
        out["C3"][f"{ka}..{kb}"] = {"dI_n": out["C2"][kb]["n"] - out["C2"][ka]["n"], "q_int_U": g,
                                    "dI_p": out["C2"][kb]["p"] - out["C2"][ka]["p"],
                                    "dI_total": out["C2"][kb]["total"] - out["C2"][ka]["total"]}
    vt = float(dv.get_parameter(device=dev, region="Si", name="V_t"))
    ni = float(dv.get_parameter(device=dev, region="Si", name="n_i"))
    fin = bool(np.all(np.isfinite(n)) and np.all(np.isfinite(p)) and np.all(np.isfinite(psi)))
    out["positive_finite"] = bool(fin and n.min() > 0 and p.min() > 0)
    if fin and n.min() > 0 and p.min() > 0:
        phin, phip = psi - vt * np.log(n / ni), psi + vt * np.log(p / ni)
        out["qf_dev_V"] = float(max(np.max(np.abs(phin - np.median(phin))), np.max(np.abs(phip - np.median(phip)))))
        out["mass_action_dev"] = float(np.max(np.abs(n * p / ni ** 2 - 1)))
    else:
        out["qf_dev_V"] = {"value": None, "status": "CARRIERS_NOT_POSITIVE_FINITE"}
        out["mass_action_dev"] = {"value": None, "status": "CARRIERS_NOT_POSITIVE_FINITE"}
    out["psi_contact_V"] = {contacts[0]: float(psi[x == x.min()].mean()), contacts[1]: float(psi[x == x.max()].mean())}
    out["max_abs_ElectricField_V_per_cm"] = float(np.max(np.abs(ev("ElectricField"))))
    out["n_range"] = [float(n.min()), float(n.max())]
    out["p_range"] = [float(p.min()), float(p.max())]
    out["bias_readback"] = {c: float(dv.get_parameter(device=dev, name=f"{c}_bias")) for c in contacts}
    return out, {"psi": psi, "n": n, "p": p}


def main():
    work, var = os.path.abspath(sys.argv[1]), sys.argv[2]
    import devsim as dv
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.physics.doping import apply_step_junction_doping
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
    prod = ce.load_strict(os.path.join(work, "prod.json"))
    arr = np.load(os.path.join(work, "prod_arrays.npz"))
    out = {"variant": var, "label": "AUDIT-ONLY SHADOW - not a production-supported result", "flags_at_start": flags(dv)}
    states = {}
    t0 = time.time()
    try:
        if var == "S12":
            dv.set_parameter(name="extended_model", value=True)
            dv.set_parameter(name="extended_equation", value=True)
        out["flags_set"] = flags(dv)
        mesh = os.path.join(work, prod["mesh_file"]["name"])
        g = ce.GUI
        ident = {"mesh_file_sha256_equal": ce.sha_file(mesh) == prod["mesh_file"]["sha256"]}
        pr = build_process_result({"final_mesh": mesh, "snapshots": []})
        d = g["doping"]
        doped = apply_step_junction_doping(pr, region=d["region"], junction_axis=d["junction_axis"],
                                           junction_position_um=d["junction_position_um"], donor_conc_cm3=d["donor_conc_cm3"],
                                           acceptor_conc_cm3=d["acceptor_conc_cm3"], chemical_state=d["chemical_state"])
        i = dict(g["import"])
        i["mesh_name"], i["device_name"] = "shadow_mesh", "shadow_device"
        imp = import_process_result(doped, mesh_name=i["mesh_name"], device_name=i["device_name"], contact_regions=i["contact_regions"],
                                    contact_axis=i["contact_axis"], length_scale_to_cm=i["length_scale_to_cm"],
                                    refine_near_um=i["refine_near_um"], refine_axis=i["refine_axis"])
        dev = imp.device
        x = np.array(dv.get_node_model_values(device=dev, region="Si", name="x"))
        y = np.array(dv.get_node_model_values(device=dev, region="Si", name="y"))
        el = np.array(dv.get_element_node_list(device=dev, region="Si"), dtype=np.int64)
        pf = prod["region_facts"]["Si"]
        ident.update({"x_sha256_equal": ce.sha(x.tobytes()) == pf["x_sha256"], "y_sha256_equal": ce.sha(y.tobytes()) == pf["y_sha256"],
                      "elements_sha256_equal": ce.sha(el.tobytes()) == pf["elements_sha256"],
                      "contacts_equal": list(imp.contacts) == prod["contacts"],
                      "regions_equal": list(dv.get_region_list(device=dev)) == prod["regions"],
                      "doping_sha256_equal": all(ce.sha(arr[k].tobytes()) == prod["capture"]["doping_sha256"][k]
                                                 for k in ("Donors", "Acceptors", "NetDoping")),
                      "doping_node_order_proven": bool(np.array_equal(arr["query_x_um"], x / UM) and np.array_equal(arr["query_y_um"], y / UM))})
        nvol = np.array(dv.get_node_model_values(device=dev, region="Si", name="NodeVolume"))
        ident["inventory_equal"] = (float((arr["Donors"] * nvol).sum()) == prod["doping_prechecks"]["inventory_donor_cm-1"]
                                    and float((arr["Acceptors"] * nvol).sum()) == prod["doping_prechecks"]["inventory_acceptor_cm-1"])
        out["identity"] = ident
        out["identity_ok"] = all(ident.values())
        if not out["identity_ok"]:
            out["status"] = "SHADOW_IDENTITY_FAIL"
            raise SystemExit
        for name in ("Donors", "Acceptors", "NetDoping"):       # same public calls as tcad apply_doping writes
            dv.node_model(device=dev, region="Si", name=name, equation="0")
            dv.set_node_values(device=dev, region="Si", name=name, values=[float(v) for v in arr[name]])
        contacts = list(imp.contacts)
        src = contacts[1] if g["measure"]["source_pin"] == "max" else contacts[0]
        gnd = contacts[0] if src == contacts[1] else contacts[1]
        out["sweep"] = {"sweep_contact": src, "voltage": g["measure"]["voltage"], "fixed": {gnd: g["measure"]["gnd_voltage"]}}
        calls = []
        orig = dv.solve

        def snap(*a, **k):
            t = time.time()
            try:
                r = orig(*a, **k)
                calls.append({"k": {kk: vv for kk, vv in k.items()}, "ok": True, "wall_s": round(time.time() - t, 3)})
                return r
            except Exception as e:  # noqa: BLE001
                calls.append({"k": {kk: vv for kk, vv in k.items()}, "ok": False, "error": repr(e)[:200], "wall_s": round(time.time() - t, 3)})
                raise
            finally:
                if len(calls) == 2 and calls[-1]["ok"] and "equilibrium_0V" not in out:
                    m, s = measure(dv, dev, contacts)
                    out["equilibrium_0V"] = m
                    states.update({f"{kk}_0V": v for kk, v in s.items()})
        dv.solve = snap
        try:
            res = run_pn_junction_iv_sweep(device=dev, region="Si", all_contacts=contacts, sweep_contact=src,
                                           sweep_voltages=[g["measure"]["voltage"]], fixed_contacts={gnd: g["measure"]["gnd_voltage"]})
            out["converged"] = True
            out["production_routine_currents"] = [pt.currents for pt in res.points]
            m, s = measure(dv, dev, contacts)
            out["bias_point"] = m
            states.update({f"{kk}_bias": v for kk, v in s.items()})
        except Exception as e:  # noqa: BLE001
            out["converged"] = False
            out["error"] = repr(e)[:300]
        finally:
            dv.solve = orig
        out["solve_calls"] = calls
        out["parameters"] = {p: float(dv.get_parameter(device=dev, region="Si", name=p)) for p in PARAMS}
        out["flags_at_end"] = flags(dv)
        dv.delete_device(device=dev)
        dv.delete_mesh(mesh=imp.mesh)
        out["devices_left"] = list(dv.get_device_list())
    except SystemExit:
        pass
    except Exception as e:  # noqa: BLE001
        out["error"] = repr(e)[:500]
        out["traceback"] = traceback.format_exc()[-2000:]
    out["wall_s"] = round(time.time() - t0, 1)
    if states:
        p = os.path.join(work, f"shadow_{var}_states.npz")
        np.savez_compressed(p, **states)
        out["states_npz_sha256"] = ce.sha_file(p)
    ce.dump_strict(out, os.path.join(work, f"shadow_{var}.json"))
    print(f"[shadow_e1] {var} identity_ok={out.get('identity_ok')} converged={out.get('converged')} error={'error' in out}", flush=True)


if __name__ == "__main__":
    main()
