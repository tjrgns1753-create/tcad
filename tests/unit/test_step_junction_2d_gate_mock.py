#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Batch 7E -- state-level detection unit test (item A) for the 2D step-junction
mesh-convergence gate.

`tcad.physics.wafer_state_v2.active_step_junction_instances(state, material)` is the
ONLY sanctioned source of truth `canonical_node_doping()` uses to decide whether the
STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED gate might apply to a region -- never a
`DopingProfile.kind` string, never a GUI combobox's most recent selection (both can go
stale relative to what is actually attached to the wafer). This is a pure WaferStateV2
query with no DevSim dependency (the DIMENSION half of the real gate lives in
doping_mapping.py, exercised for real in test_step_junction_2d_gate_real.py).

  1. a 2D-shaped ACTIVE step_junction_v1 attachment is detected.
  2. uniform / gaussian_implant / implant_windows ACTIVE attachments are NOT
     false-positives (different `model` string).
  3. a CHEMICAL or UNKNOWN step_junction_v1 attachment is NOT detected here --
     it is already refused by the pre-existing, unrelated activation gate
     before this new check would ever matter (dopant_activation_state reason).
  4. a step_junction_v1 attachment on a DIFFERENT material/instance does not
     block an unrelated region's query.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import tcad.physics.wafer_state_v2 as v2
from tcad.mesh.interface import ProcessResult
from tcad.physics.doping import (
    apply_gaussian_implant_doping, apply_implant_windows_doping,
    apply_step_junction_doping, apply_uniform_doping,
)
from tcad.physics.wafer_state_accumulation import advance_wafer_state

SI = (-2.0, 2.0, -1.0, 0.0)
SIO2 = (-2.0, 2.0, 0.0, 0.3)
PR = ProcessResult(volume_mesh_path="unused.vtu")


def base():
    return v2.initialize_wafer_state(
        cells=[("Si", SI, "si#substrate"), ("SiO2", SIO2, "sio2#seed")], grid_delta_um=0.2)


def attach(kind_call):
    return advance_wafer_state(base(), kind_call, "doping")


def main():
    # ---- 1. ideal ACTIVE step junction is detected on its own instance --------------------------------------
    step = apply_step_junction_doping(PR, "Si", "x", 0.0, 1e17, 1e17, chemical_state="ACTIVE")
    s_step = attach(step)
    hit = v2.active_step_junction_instances(s_step, "Si")
    assert hit == ["si#substrate"], hit
    print(f"1. ACTIVE step_junction_v1 on Si -> detected: {hit}")

    # ---- 2. other ACTIVE doping kinds are NOT false positives -------------------------------------------------
    uni = attach(apply_uniform_doping(PR, donor_by_region_cm3={"Si": 1e17}, acceptor_by_region_cm3={"Si": 1e17}, chemical_state="ACTIVE"))
    assert v2.active_step_junction_instances(uni, "Si") == [], "uniform_v1 must never be detected as step_junction_v1"
    gauss = attach(apply_gaussian_implant_doping(PR, "Si", "x", 0.0, 0.3, donor_peak_conc_cm3=1e18, chemical_state="ACTIVE"))
    assert v2.active_step_junction_instances(gauss, "Si") == [], "gaussian_v1 must never be detected as step_junction_v1"
    win = attach(apply_implant_windows_doping(PR, "Si", "x", background_doping_cm3=1e16,
                                              windows=[{"min_um": 0.5, "max_um": 1.5, "conc_cm3": 1e19}], chemical_state="ACTIVE"))
    assert v2.active_step_junction_instances(win, "Si") == [], "implant_windows_v1 must never be detected as step_junction_v1"
    print("2. uniform_v1 / gaussian_v1 / implant_windows_v1 ACTIVE attachments -> not detected (model string is exact)")

    # ---- 3. CHEMICAL / UNKNOWN step junctions are not detected by THIS gate -----------------------------------
    # (they are already refused, for a DIFFERENT reason, by the pre-existing per-node
    # activation gate in canonical_node_doping() -- this function must stay silent so
    # that existing, unrelated reason stays visible instead of being masked.)
    for state_name in ("CHEMICAL", "UNKNOWN"):
        s = attach(apply_step_junction_doping(PR, "Si", "x", 0.0, 1e17, 1e17, chemical_state=state_name))
        assert v2.active_step_junction_instances(s, "Si") == [], f"{state_name} step_junction_v1 must not be detected by the 2D gate helper"
    print("3. CHEMICAL / UNKNOWN step_junction_v1 attachments -> not detected (left to the existing activation gate)")

    # ---- 4. a step junction on a DIFFERENT material/instance does not block an unrelated region ---------------
    assert v2.active_step_junction_instances(s_step, "SiO2") == [], \
        "a Si step junction must not be reported when querying the SiO2 instance"
    print("4. Si step_junction_v1 attachment queried against the unrelated SiO2 instance -> not detected")

    print("\nPASS: active_step_junction_instances() detects an ACTIVE step_junction_v1 attachment exactly, "
          "on its own instance only, and defers CHEMICAL/UNKNOWN to the existing activation gate.")


if __name__ == "__main__":
    main()
