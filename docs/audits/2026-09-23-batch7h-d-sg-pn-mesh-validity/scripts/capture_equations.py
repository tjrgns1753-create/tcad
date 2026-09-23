"""Batch 7H-D section 3/5 (no solve): capture the public simple_physics helper
sources, every model/equation string the PRODUCTION setup functions register
(by wrapping the public devsim.* model/equation calls with a logger), and the
silicon parameter values DEVSIM actually uses. Writes data/production_sg_path.json."""
import inspect
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

import devsim  # noqa: E402
import devsim.python_packages.simple_physics as sp  # noqa: E402
import devsim.python_packages.model_create as mc  # noqa: E402

LOG = []


def wrap(name):
    orig = getattr(devsim, name)

    def f(*a, **k):
        LOG.append({"call": name, **{kk: (str(v) if not isinstance(v, (int, float, str, list)) else v) for kk, v in k.items()}})
        return orig(*a, **k)
    setattr(devsim, name, f)
    for mod in (sp, mc):  # helpers did `from devsim import *`; patch their namespace too
        if hasattr(mod, name):
            setattr(mod, name, f)
    return orig


def main():
    originals = {n: wrap(n) for n in ("node_model", "edge_model", "element_model", "contact_node_model", "contact_edge_model",
                                      "equation", "contact_equation", "set_parameter", "node_solution", "set_node_values")}
    from tcad.device.devsim.semiconductor_equation import (setup_semiconductor_potential_equation,
                                                           setup_drift_diffusion_equation)
    # minimal 1D device, NO solve
    devsim.create_1d_mesh(mesh="m")
    devsim.add_1d_mesh_line(mesh="m", pos=-1e-5, ps=1e-6, tag="L")
    devsim.add_1d_mesh_line(mesh="m", pos=1e-5, ps=1e-6, tag="R")
    devsim.add_1d_contact(mesh="m", name="left", tag="L", material="metal")
    devsim.add_1d_contact(mesh="m", name="right", tag="R", material="metal")
    devsim.add_1d_region(mesh="m", material="Si", region="Si", tag1="L", tag2="R")
    devsim.finalize_mesh(mesh="m")
    devsim.create_device(mesh="m", device="d")
    originals["node_model"](device="d", region="Si", name="NetDoping", equation="0")
    setup_semiconductor_potential_equation("d", "Si", ["left", "right"], 300.0)
    setup_drift_diffusion_equation("d", "Si", ["left", "right"])
    params = {}
    for p in ("T", "kT", "V_t", "q", "ElectronCharge", "Permittivity", "n_i", "mu_n", "mu_p", "taun", "taup", "n1", "p1"):
        try:
            params[p] = devsim.get_parameter(device="d", region="Si", name=p)
        except Exception as e:  # recorded, not hidden
            params[p] = f"ERR {e}"
    eqs = {}
    for e in ("PotentialEquation", "ElectronContinuityEquation", "HoleContinuityEquation"):
        try:
            eqs[e] = devsim.get_equation_command(device="d", region="Si", name=e)
        except Exception as ex:
            eqs[e] = f"ERR {ex}"
    ceqs = {}
    for c in ("left",):
        for e in ("PotentialEquation", "ElectronContinuityEquation", "HoleContinuityEquation"):
            try:
                ceqs[f"{c}:{e}"] = devsim.get_contact_equation_command(device="d", contact=c, name=e)
            except Exception as ex:
                ceqs[f"{c}:{e}"] = f"ERR {ex}"
    srcs = {n: inspect.getsource(getattr(sp, n)) for n in ("SetSiliconParameters", "CreateSiliconPotentialOnly",
                                                            "CreateSiliconPotentialOnlyContact", "CreateSiliconDriftDiffusion",
                                                            "CreateSiliconDriftDiffusionAtContact", "CreateSRH", "CreateECE",
                                                            "CreateHCE", "CreatePE", "GetContactBiasName")}
    for n in ("CreateElectronCurrent", "CreateHoleCurrent", "CreateBernoulli"):
        for mod in (mc, sp):
            if hasattr(mod, n):
                srcs[n] = inspect.getsource(getattr(mod, n))
    import devsim.python_packages as pp
    srcs["_files"] = {"simple_physics": sp.__file__, "model_create": mc.__file__}
    out = {"devsim_version": getattr(devsim, "__version__", None), "parameters": params, "equation_commands": eqs,
           "contact_equation_commands": ceqs, "registered_models_in_order": LOG, "helper_sources": srcs}
    with open(os.path.join(HERE, "..", "data", "production_sg_path.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, default=str)
    print("devsim", out["devsim_version"])
    print("params", params)
    print("equations", json.dumps(eqs, default=str)[:1500])
    for L in LOG:
        if L["call"] in ("edge_model", "node_model") and any(k in L.get("name", "") for k in
                                                              ("Current", "Charge", "USRH", "Intrinsic", "ElectricField", "Flux", "Bern")):
            if ":" not in L["name"]:
                print(L["call"], L["name"], "=", L.get("equation"))
    devsim.delete_device(device="d")
    devsim.delete_mesh(mesh="m")


if __name__ == "__main__":
    main()
