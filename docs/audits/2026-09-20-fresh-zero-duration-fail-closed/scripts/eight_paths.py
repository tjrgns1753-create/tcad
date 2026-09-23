# -*- coding: utf-8 -*-
"""Audit script (contract v2): fresh/inherited x thermal/LOCOS x zero/positive.

A fresh zero-duration step is a MATERIALIZATION (a new virgin Si domain), not an
identity, so a prior WaferState is NEVER assumed to describe it. This script
therefore measures fresh paths twice (or four times):
  * prior = None                 -> the exact initial state from the transition's bounds
  * prior = doped, SAME bounds   -> fail-closed (equal bounds do not prove equal history)
  * prior = doped, OTHER bounds  -> fail-closed
  * prior = doped + extra SiN    -> fail-closed
and only inherited zero-duration paths are expected to keep the prior object.

Per path it records: exported-mesh materials, the full `state_transition` dict, whether the
prior state object was returned, the resulting cells (material, bounds, lifecycle), the
number of ACTIVE cells, active attachments, unresolved-ledger entries, the query
donor/acceptor/net/status, and the counted (pass-through, not trapped) calls of
Oxidation() / setInitialOxideThickness() / Process() / Process.apply() /
LocosOxidation._build_locos_geometry().

Supersedes scripts/eight_paths_SUPERSEDED_CONTRACT_BUG.py (kept, not re-run).
Writes raw/eight_paths_v2.json.
"""
import json
import sys
import tempfile
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO))

import meshio
import numpy as np

from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import save_volume_mesh
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.physics.wafer_state_v2 import (
    GeometryTransform, attach_dopant, initialize_wafer_state, uniform_inventory_integral,
)
from tcad.process.oxidation.locos import LocosOxidation
from tcad.process.oxidation.thermal import ThermalOxidation

vps = session.require_viennaps()
COUNTS = {"Oxidation_constructed": 0, "setInitialOxideThickness": 0, "Process_constructed": 0,
          "Process_apply": 0, "_build_locos_geometry": 0}


class _OxSpy:
    def __init__(self, real):
        object.__setattr__(self, "_r", real)

    def __getattr__(self, n):
        a = getattr(self._r, n)
        if n == "setInitialOxideThickness":
            def w(*x, **k):
                COUNTS["setInitialOxideThickness"] += 1
                return a(*x, **k)
            return w
        return a


class _ProcSpy:
    def __init__(self, real):
        self._r = real

    def apply(self):
        COUNTS["Process_apply"] += 1
        return self._r.apply()

    def __getattr__(self, n):
        return getattr(self._r, n)


_orig_ox, _orig_proc, _orig_bld = vps.Oxidation, vps.Process, LocosOxidation._build_locos_geometry


def _ox(*a, **k):
    COUNTS["Oxidation_constructed"] += 1
    return _OxSpy(_orig_ox(*a, **k))


def _proc(*a, **k):
    COUNTS["Process_constructed"] += 1
    return _ProcSpy(_orig_proc(*a, **k))


def _bld(self, *a, **k):
    COUNTS["_build_locos_geometry"] += 1
    return _orig_bld(self, *a, **k)


vps.Oxidation, vps.Process = _ox, _proc
LocosOxidation._build_locos_geometry = _bld


def reset():
    for k in COUNTS:
        COUNTS[k] = 0


def mesh_names(path):
    m = meshio.read(path)
    tags = set()
    for b, d in zip(m.cells, m.cell_data["Material"]):
        if b.type == "triangle":
            tags |= {int(t) for t in np.asarray(d)}
    return sorted(str(vps.Material(t)).split("'")[1] for t in tags)


def same_mesh(a, b):
    x, y = meshio.read(a), meshio.read(b)
    if not np.array_equal(x.points, y.points) or len(x.cells) != len(y.cells):
        return False
    return all(np.array_equal(p.data, q.data) for p, q in zip(x.cells, y.cells)) and all(
        np.array_equal(p, q) for p, q in zip(x.cell_data["Material"], y.cell_data["Material"]))


def summarize(state, probes=((0.0, -0.25),)):
    out = {
        "cells": [{"material": c.material, "bounds_um": None if c.bounds_um is None else list(c.bounds_um),
                   "lifecycle": c.lifecycle, "instance": c.material_instance_id} for c in state.cells],
        "active_cell_count": len(state.active_cells()),
        "active_cells": [{"material": c.material, "bounds_um": list(c.bounds_um) if c.bounds_um else None}
                         for c in state.active_cells()],
        "active_attachments": len(state.attachments),
        "unresolved_ledger_entries": len(state.unresolved_inventory),
        "grid_delta_um": state.grid_delta_um, "queries": {},
    }
    for x, y in probes:
        q = state.net_doping_at(x, y)
        out["queries"][f"({x},{y})"] = {
            "donor": q.donor_concentration, "acceptor": q.acceptor_concentration, "net": q.net_doping,
            "status": (q.physics_status or {}).get("resolution")}
    return out


def doped_prior(bounds, grid, extra=None):
    s = initialize_wafer_state(cells=[("Si", bounds, "si#substrate")], grid_delta_um=grid)
    s = attach_dopant(
        s, species="P", polarity="donor", concentration_at=lambda x, y: 1e17,
        support_instance_id="si#substrate", support_region_um=bounds, model="uniform_v1",
        inventory_integral=uniform_inventory_integral(1e17))
    if extra:
        material, box = extra
        s = advance_wafer_state(
            s, None, "deposition",
            transform=GeometryTransform("deposition", representable=True,
                                        added_cells=((material, box, f"inst_{material}"),)))
    return s


GRID = 0.05
BASE = dict(grid_delta_um=GRID, x_extent_um=2.0, y_extent_um=1.0, temperature_c=1000.0, oxidant="Dry",
            silicon_depth_um=0.5, mask_material="Mask", mask_left_um=0.5, mask_right_um=1.5,
            pr_thickness_um=0.1, mask_spans_um=[[0.5, 1.5]], pad_oxide_thickness_um=0.1)
FRESH_BOUNDS = (-1.0, 1.0, -0.5, 0.0)
PRIORS = {
    "none": lambda: None,
    "same_bounds_doped": lambda: doped_prior(FRESH_BOUNDS, GRID),
    "different_bounds_doped": lambda: doped_prior((-2.0, 2.0, -2.0, 0.0), 0.1),
    "extra_SiN_doped": lambda: doped_prior(FRESH_BOUNDS, GRID, extra=("SiN", (-1.0, 1.0, 0.0, 0.1))),
}

out = {"contract": "v2: fresh zero-duration = materialization (never an identity)", "grid": GRID,
       "recipe_common": BASE, "paths": []}
tmp = tempfile.mkdtemp(prefix="paths_v2_", dir=session._ascii_scratch_dir())
ref = session.make_mask_spans(GRID, 2.0, 1.0, [], 0.1, substrate_depth_um=1.5)
ref_mesh = save_volume_mesh(ref, str(Path(tmp) / "ref_virgin"), floor_depth_um=0.5)
out["reference_virgin_si_materials"] = mesh_names(ref_mesh)


def run_path(cls, inherited, hours, prior_name):
    reset()
    label = f"{cls.__name__} {'inherited' if inherited else 'fresh'} t={hours} prior={prior_name}"
    recipe = dict(BASE, time_hours=hours)
    domain = before = None
    if inherited:
        domain = session.create_domain(GRID, 2.0, 1.0)
        vps.MakePlane(domain, 0.0, vps.Material.Si).apply()
        before = save_volume_mesh(domain, str(Path(tmp) / f"before_{len(out['paths'])}"), floor_depth_um=0.5)
    reset()
    step = cls(inherited_domain=domain)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = step.run(recipe, str(Path(tmp) / f"run_{len(out['paths'])}"))
    counts = dict(COUNTS)
    prior = PRIORS[prior_name]()
    out_state = advance_wafer_state(prior, build_process_result(res), "oxidation")
    probes = ((0.0, -0.25), (0.0, 0.05)) if prior_name == "extra_SiN_doped" else ((0.0, -0.25),)
    rec = {
        "path": label, "prior": prior_name,
        "domain_materials": sorted(str(m).split("'")[1] for m in step.last_domain.getMaterialsInDomain()),
        "exported_mesh_materials": mesh_names(res["final_mesh"]),
        "state_transition": res.get("state_transition"),
        "physics_status_resolution": (res.get("physics_status") or {}).get("resolution"),
        "counts": counts,
        "prior_state_object_returned": (out_state is prior) if prior is not None else None,
        "prior_state_before": summarize(prior, probes) if prior is not None else None,
        "state_after": summarize(out_state, probes),
    }
    if inherited:
        rec["input_domain_object_returned"] = step.last_domain is domain
        rec["exported_mesh_identical_to_input_export"] = same_mesh(before, res["final_mesh"])
    else:
        rec["exported_mesh_identical_to_virgin_si_reference"] = same_mesh(ref_mesh, res["final_mesh"])
    out["paths"].append(rec)
    sa = rec["state_after"]
    q = next(iter(sa["queries"].values()))
    print(f"{label:62s} mats={rec['exported_mesh_materials']} kind={(rec['state_transition'] or {}).get('kind')} "
          f"inh={(rec['state_transition'] or {}).get('inherited')} calls={list(counts.values())} "
          f"prior_returned={rec['prior_state_object_returned']} active_cells={sa['active_cell_count']} "
          f"attach={sa['active_attachments']} ledger={sa['unresolved_ledger_entries']} "
          f"q(net={q['net']},status={q['status']})")


# the six requested zero-duration paths (+ every fresh prior variant)
for cls in (ThermalOxidation, LocosOxidation):
    for prior_name in PRIORS:
        run_path(cls, False, 0.0, prior_name)
for cls in (ThermalOxidation, LocosOxidation):
    run_path(cls, True, 0.0, "same_bounds_doped")
# positive-time (UNSUPPORTED) regression paths, with a doped prior
for cls in (ThermalOxidation, LocosOxidation):
    for inherited in (False, True):
        run_path(cls, inherited, 0.5, "same_bounds_doped")

out["scratch"] = tmp
(HERE.parent / "raw" / "eight_paths_v2.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print("PATHS V2 DONE")
