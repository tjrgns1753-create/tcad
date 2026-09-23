"""Batch 7H-C: run every configuration in its own subprocess (DEVSIM global
parameters must not leak between configurations) and store raw results."""
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
sys.path.insert(0, os.path.join(HERE, "..", "..", "2026-09-23-batch7h-b-nodevolume-mechanism", "scripts"))
import formulas as fm  # noqa: E402

FIX = json.load(open(os.path.join(DATA, "fixtures_7hc.json"), encoding="utf-8"))["fixtures"]
BASE = ["M1", "M2", "M3", "M4"]
VAR = ["M4_mirror", "M4_rot180", "M4_scale2"]


def negative_signed_volume_on_free(mesh):
    f = FIX[mesh]
    P = np.array(f["points_um"]) * 1e-4
    vol = fm.node_areas(P, f["triangles"], "F2")
    return int((vol < 0).sum())


def configs():
    c = []
    for m in BASE + VAR:
        for fl in ("E1", "E2"):
            c.append({"id": f"A_{m}_{fl}", "exp": "laplace", "mesh": m, "flux": fl})
    for m in BASE:
        c.append({"id": f"C3_{m}_E1", "exp": "poisson", "mesh": m, "flux": "E1"})
    # capability spike: signed overrides
    for m in ("M3", "M4", "M4_mirror", "M4_scale2"):
        c.append({"id": f"OV_edge_signed_laplace_{m}", "exp": "laplace", "mesh": m, "flux": "E1",
                  "overrides": {"edge_couple_model": "signed"}})
    for m in ("M3", "M4"):
        c.append({"id": f"OV_edge_signed_poisson_{m}", "exp": "poisson", "mesh": m, "flux": "E1",
                  "overrides": {"edge_couple_model": "signed"}})
        if negative_signed_volume_on_free(m) == 0:
            c.append({"id": f"OV_edge_and_volume_signed_poisson_{m}", "exp": "poisson", "mesh": m, "flux": "E1",
                      "overrides": {"edge_couple_model": "signed", "node_volume_model": "signed"}})
            c.append({"id": f"OV_volume_only_signed_poisson_{m}", "exp": "poisson", "mesh": m, "flux": "E1",
                      "overrides": {"node_volume_model": "signed"}})
        else:
            c.append({"id": f"OV_signed_volume_SKIPPED_{m}", "skip": f"{negative_signed_volume_on_free(m)} negative signed node volumes"})
    for m in ("M3", "M4"):
        c.append({"id": f"EL_default_{m}", "exp": "element", "mesh": m})
        c.append({"id": f"EL_signed_{m}", "exp": "element", "mesh": m, "overrides": {"element_edge_couple_model": "signed"}})
    # capability spike: does each documented parameter take effect (x2 models)?
    c += [{"id": "X2_edge_couple_M3", "exp": "laplace", "mesh": "M3", "flux": "E1", "overrides": {"edge_couple_model": "x2"}},
          {"id": "X2_node_volume_M2", "exp": "poisson", "mesh": "M2", "flux": "E1", "overrides": {"node_volume_model": "x2"}},
          {"id": "EV_default_M2", "exp": "poisson_edgevol", "mesh": "M2", "flux": "E1"},
          {"id": "X2_edge_node_volume_M2", "exp": "poisson_edgevol", "mesh": "M2", "flux": "E1", "overrides": {"edge_node_volume_models": "x2"}},
          {"id": "ELV_default_M2", "exp": "poisson_elemvol", "mesh": "M2", "flux": "E1"},
          {"id": "X2_element_node_volume_M2", "exp": "poisson_elemvol", "mesh": "M2", "flux": "E1", "overrides": {"element_node_volume_models": "x2"}},
          {"id": "X2_element_edge_couple_M3", "exp": "element", "mesh": "M3", "overrides": {"element_edge_couple_model": "x2"}},
          {"id": "IF_default", "exp": "laplace", "mesh": "IF4", "flux": "E1"},
          {"id": "IF_edge_signed", "exp": "laplace", "mesh": "IF4", "flux": "E1", "overrides": {"edge_couple_model": "signed"}},
          {"id": "SP_default_M4", "exp": "simple_physics", "mesh": "M4"},
          {"id": "SP_edge_signed_M4", "exp": "simple_physics", "mesh": "M4", "overrides": {"edge_couple_model": "signed"}}]
    return c


def main():
    out = {}
    py = sys.executable
    for cfg in configs():
        if "skip" in cfg:
            out[cfg["id"]] = cfg
            print(cfg["id"], "SKIPPED:", cfg["skip"])
            continue
        p = subprocess.run([py, os.path.join(HERE, "dev_run.py"), json.dumps(cfg)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        txt = p.stdout
        if "===RESULT_JSON===" not in txt:
            r = {"cfg": cfg, "error": f"no result rc={p.returncode} tail={(txt + p.stderr)[-600:]}"}
        else:
            r = json.loads(txt.split("===RESULT_JSON===", 1)[1].strip().splitlines()[0])
        out[cfg["id"]] = r
        if "error" in r:
            print(cfg["id"], "ERROR", r["error"][:200])
        else:
            regs = r["regions"]
            s = " ".join(f"{rn}:Linf={g.get('Linf_free_V', float('nan')):.3e}" for rn, g in regs.items())
            print(cfg["id"], s, "I=", r["contact_current"])
    with open(os.path.join(DATA, "results_7hc.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True)


if __name__ == "__main__":
    main()
