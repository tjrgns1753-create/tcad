# -*- coding: utf-8 -*-
"""Audit script: fresh/inherited x thermal/LOCOS x zero/positive duration.

Records, for each of the 8 paths, the actual materials, `state_transition`,
`physics_status` reason, and how many times `vps.Oxidation()` was constructed,
`setInitialOxideThickness()` was called, `vps.Process` was constructed/applied
and `LocosOxidation._build_locos_geometry()` was entered -- by COUNTING (a
pass-through wrapper), not by trapping. Also records geometry evidence:
fresh -> identical to the neutral virgin-Si wafer; inherited -> the input
domain object is returned and its exported mesh is byte-for-byte the same.

A negative control (NOT a production path) shows what the old fresh-LOCOS
construction looked like, to prove the material check would notice it.
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
from tcad.physics.wafer_state_accumulation import (
    advance_wafer_state, initial_wafer_state_from_recipe,
)
from tcad.physics.wafer_state_v2 import attach_dopant, uniform_inventory_integral
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


_orig_ox, _orig_proc = vps.Oxidation, vps.Process
_orig_bld = LocosOxidation._build_locos_geometry


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


def areas(path):
    m = meshio.read(path)
    out = {}
    for b, d in zip(m.cells, m.cell_data["Material"]):
        if b.type != "triangle":
            continue
        p = m.points[b.data][:, :, :2]
        a = np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                   - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1])) / 2
        for t, v in zip(np.asarray(d), a):
            n = str(vps.Material(int(t))).split("'")[1]
            out[n] = out.get(n, 0.0) + float(v)
    return {k: round(v, 12) for k, v in sorted(out.items())}


def same_mesh_bytes(a, b):
    x, y = meshio.read(a), meshio.read(b)
    if not np.array_equal(x.points, y.points) or len(x.cells) != len(y.cells):
        return False
    return all(np.array_equal(p.data, q.data) for p, q in zip(x.cells, y.cells)) and all(
        np.array_equal(p, q) for p, q in zip(x.cell_data["Material"], y.cell_data["Material"]))


def doped_state(grid):
    s0 = initial_wafer_state_from_recipe({"x_extent_um": 2.0, "silicon_depth_um": 0.5, "grid_delta_um": grid})
    return attach_dopant(
        s0, species="P", polarity="donor", concentration_at=lambda x, y: 1e17,
        support_instance_id=s0.cells[0].material_instance_id, support_region_um=(-1.0, 1.0, -0.5, 0.0),
        model="uniform_v1", inventory_integral=uniform_inventory_integral(1e17))


GRID = 0.05
BASE = dict(grid_delta_um=GRID, x_extent_um=2.0, y_extent_um=1.0, temperature_c=1000.0, oxidant="Dry",
            silicon_depth_um=0.5, mask_material="Mask", mask_left_um=0.5, mask_right_um=1.5,
            pr_thickness_um=0.1, mask_spans_um=[[0.5, 1.5]], pad_oxide_thickness_um=0.1)
out = {"grid": GRID, "recipe_common": BASE, "paths": []}
tmp = tempfile.mkdtemp(prefix="eight_", dir=session._ascii_scratch_dir())

ref_dom = session.make_mask_spans(GRID, 2.0, 1.0, [], 0.1, substrate_depth_um=1.5)
ref_mesh = save_volume_mesh(ref_dom, str(Path(tmp) / "ref_virgin"), floor_depth_um=0.5)
out["reference_virgin_si"] = {"materials": mesh_names(ref_mesh), "areas": areas(ref_mesh)}

for cls in (ThermalOxidation, LocosOxidation):
    for inherited in (False, True):
        for hours in (0.0, 0.5):
            reset()
            label = f"{cls.__name__} {'inherited' if inherited else 'fresh'} t={hours}"
            recipe = dict(BASE, time_hours=hours)
            domain = before = None
            if inherited:
                domain = session.create_domain(GRID, 2.0, 1.0)
                vps.MakePlane(domain, 0.0, vps.Material.Si).apply()
                before = save_volume_mesh(domain, str(Path(tmp) / f"before_{label.replace(' ', '_')}"),
                                          floor_depth_um=0.5)
                COUNTS_BASE = dict(COUNTS)    # domain construction above uses MakePlane only
            step = cls(inherited_domain=domain)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = step.run(recipe, str(Path(tmp) / label.replace(" ", "_")))
            counts = dict(COUNTS)
            prior = doped_state(GRID)
            ps = build_process_result(res)
            after_state = advance_wafer_state(prior, ps, "oxidation")
            rec = {
                "path": label,
                "domain_materials": sorted(str(m).split("'")[1] for m in step.last_domain.getMaterialsInDomain()),
                "exported_mesh_materials": mesh_names(res["final_mesh"]),
                "exported_areas": areas(res["final_mesh"]),
                "state_transition": res.get("state_transition"),
                "physics_status_resolution": (res.get("physics_status") or {}).get("resolution"),
                "physics_status_reason_code": (res.get("physics_status") or {}).get("reason_code"),
                "counts": counts,
                "wafer_state": {
                    "returned_prior_state_object": after_state is prior,
                    "active_attachments_after": len(after_state.attachments),
                    "dopant_query_after": after_state.net_doping_at(0.0, -0.25).net_doping,
                    "dopant_query_status": (after_state.net_doping_at(0.0, -0.25).physics_status or {}).get("resolution"),
                },
            }
            if inherited:
                rec["input_domain_object_returned"] = step.last_domain is domain
                rec["exported_mesh_identical_to_input_export"] = same_mesh_bytes(before, res["final_mesh"])
            else:
                rec["exported_mesh_identical_to_virgin_si_reference"] = same_mesh_bytes(ref_mesh, res["final_mesh"])
            out["paths"].append(rec)
            print(f"{label:34s} mats={rec['exported_mesh_materials']} transition={rec['state_transition']} "
                  f"counts={counts} prior_kept={rec['wafer_state']['returned_prior_state_object']} "
                  f"attach={rec['wafer_state']['active_attachments_after']}")

# negative control: what the OLD fresh zero-duration LOCOS construction looked like (not a production path now)
reset()
step = LocosOxidation()
geometry, mats, flags = step._build_locos_geometry(dict(BASE, time_hours=0.0), vps)
from tcad.backends.viennaps.io import save_locos_volume_mesh
p = save_locos_volume_mesh(geometry, mats, flags, str(Path(tmp) / "old_style"), floor_depth_um=0.5)
out["negative_control_old_style_locos_stack"] = {
    "note": "direct call of the private builder -- NOT reachable from run() any more; proves the "
            "materials check distinguishes it from virgin Si",
    "exported_mesh_materials": mesh_names(p), "counts": dict(COUNTS)}
print("negative control (old-style stack):", out["negative_control_old_style_locos_stack"])

out["scratch"] = tmp
(HERE.parent / "raw" / "eight_paths.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print("EIGHT PATHS DONE")
