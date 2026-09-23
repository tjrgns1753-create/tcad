# -*- coding: utf-8 -*-
"""TEST-ONLY helper: an explicit initial Si/SiO2 stack WITH an explicit test mask,
saved once and re-loaded independently for every etch experiment.

Provenance (unchanged from Batch 1): ``DIRECT_EXPLICIT_GEOMETRY``.
  * The SiO2 is a structure the TEST STATES as an input (``MakePlane``). It is not an
    oxidation growth result, not a deposited oxide, not a Deal-Grove result, and no
    Si consumption is implied. This module says nothing about oxidation kinetics.
  * The mask is a test-input structure that exists BEFORE the etch (``remask_domain`` on
    the explicit stack, opaque spans + one open window recorded). It is not lithography
    and not a process result.

What this adds to Batch 1's `_explicit_oxide_fixture` (which is reused, not changed):
  1. the post-mask / pre-etch state is saved to a `.vpsd` file (sha256 recorded) and every
     experiment starts from its OWN freshly loaded copy;
  2. mask creation is measured before/after: the native Si and SiO2 level sets must not
     have moved;
  3. region definitions (open-window central core, protected bands) derived from the
     window, the grid and the recipe's isotropic reach -- never from a measurement of the
     result;
  4. measurements that keep three things apart: REQUESTED input, NATIVE level-set position
     (exact, exporter-free; used for every verdict), and EXPORTED-mesh cross-section (kept
     as a corroborating view; it carries the grid-proportional exporter representation
     offset of unidentified cause and is never read as growth or Si consumption).

`vps.Oxidation` is trapped (counted, restored in a `finally`) around the whole fixture
construction AND around every etch run; `vps.Process` is trapped around fixture
construction only (the etch itself legitimately uses it).
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _explicit_oxide_fixture as oxfix  # noqa: E402

PROVENANCE = oxfix.PROVENANCE
#: numerical "unchanged" threshold: the same 0.001 um the original tests and
#: `_log_etch_material_summary()` use as their noise floor (an inherited project convention,
#: not fitted to any result here).
UNCHANGED_UM = 0.001


@contextlib.contextmanager
def forbid_oxidation(module):
    """Trap `vps.Oxidation` only (counted; restored in `finally`)."""
    counts = {"Oxidation": 0}
    original = module.Oxidation
    try:
        module.Oxidation = oxfix._Trap("Oxidation", counts)
        yield counts
    finally:
        module.Oxidation = original


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ------------------------------------------------------------------ native level sets
def native_surfaces(domain) -> Dict[str, np.ndarray]:
    """{material name: (n, 2) surface nodes of that material's level set}."""
    import viennals as vls

    material_map = domain.getMaterialMap()
    out = {}
    for i, level_set in enumerate(domain.getLevelSets()):
        mesh = vls.Mesh()
        vls.ToSurfaceMesh(level_set, mesh).apply()
        name = str(material_map.getMaterialAtIdx(i)).split("'")[1]
        out[name] = np.array(mesh.getNodes())[:, :2]
    return out


def _stats(nodes: np.ndarray, x_lo: float, x_hi: float) -> Dict[str, Any]:
    sel = nodes[(nodes[:, 0] >= x_lo) & (nodes[:, 0] <= x_hi)]
    if len(sel) == 0:
        return {"n": 0}
    return {"n": int(len(sel)), "y_min": float(sel[:, 1].min()), "y_max": float(sel[:, 1].max()),
            "y_mean": float(sel[:, 1].mean())}


# ------------------------------------------------------- exported cross-section (scanline)
def _column_extent(pts, tri, tag_mask, x0):
    ys = []
    sel = tri[tag_mask]
    if len(sel) == 0:
        return None
    xs = pts[sel][:, :, 0]
    for t in sel[(xs.min(axis=1) <= x0) & (xs.max(axis=1) >= x0)]:
        v = pts[t]
        for i in range(3):
            (xa, ya), (xb, yb) = v[i], v[(i + 1) % 3]
            if xa == xb:
                if xa == x0:
                    ys += [ya, yb]
            elif (xa - x0) * (xb - x0) <= 0:
                ys.append(ya + (x0 - xa) / (xb - xa) * (yb - ya))
    return [float(min(ys)), float(max(ys))] if ys else None


def exported_cross_section(mesh_path: str, module, x_lo: float, x_hi: float, n_cols: int = 9):
    """Per material, over `n_cols` columns strictly inside [x_lo, x_hi]: how many columns contain
    the material, and the mean top / bottom of its vertical extent."""
    m = oxfix._read_mesh(mesh_path, module)
    pts, tris, tags, names = m["points"], m["triangles"], m["tags"], m["names"]
    xs = np.linspace(x_lo, x_hi, n_cols + 2)[1:-1]
    out = {"n_columns": n_cols, "materials": {}}
    for tag, name in names.items():
        ext = [_column_extent(pts, tris, tags == tag, float(x)) for x in xs]
        present = [e for e in ext if e]
        out["materials"][name] = {
            "columns_present": len(present),
            "top_mean": float(np.mean([e[1] for e in present])) if present else None,
            "bottom_mean": float(np.mean([e[0] for e in present])) if present else None,
        }
    return out


# ------------------------------------------------------------------------- regions
@dataclass
class Regions:
    """Where things are measured, derived from the window, the grid and the recipe's
    lateral reach -- never from the result being judged."""
    window_um: Tuple[float, float]
    core_um: Tuple[float, float]
    protected_bands_um: List[Tuple[float, float]]
    reach_um: float
    edge_margin_cells: int
    basis: str


def derive_regions(window_um, x_extent_um, grid_um, reach_um, *, edge_margin_cells=4,
                   domain_edge_margin_cells=8) -> Regions:
    """core: the window shrunk on both sides by (lateral reach + edge_margin_cells*grid), so it
    lies beyond every mask-edge effect; bands: under the mask, beyond the same reach from the
    window edge and `domain_edge_margin_cells` grid cells inside the domain edge."""
    lo, hi = window_um
    inset = reach_um + edge_margin_cells * grid_um
    core = (lo + inset, hi - inset)
    if not core[0] < core[1]:
        raise ValueError(f"window {window_um} is too narrow for reach {reach_um} + {edge_margin_cells} cells")
    hx = x_extent_um / 2.0
    left = (-hx + domain_edge_margin_cells * grid_um, lo - inset)
    right = (hi + inset, hx - domain_edge_margin_cells * grid_um)
    for b in (left, right):
        if not b[0] < b[1]:
            raise ValueError(f"protected band {b} is empty; enlarge the domain")
    return Regions(
        window_um=tuple(window_um), core_um=core, protected_bands_um=[left, right], reach_um=reach_um,
        edge_margin_cells=edge_margin_cells,
        basis=(f"core = window shrunk by (reach {reach_um:g} + {edge_margin_cells} cells x {grid_um:g}) "
               f"on each side; bands = beyond the same reach from the window edge, "
               f"{domain_edge_margin_cells} cells inside the domain edge"))


def region_metrics(native: Dict[str, np.ndarray], mesh_path: str, module, x_lo: float, x_hi: float) -> Dict[str, Any]:
    """Native (exact) and exported (corroborating) measurements of ONE region. Never mixed."""
    si, ox = _stats(native["Si"], x_lo, x_hi), _stats(native["SiO2"], x_lo, x_hi)
    native_block = {
        "Si_top": si, "SiO2_top": ox,
        "oxide_thickness_mean": (ox["y_mean"] - si["y_mean"]) if si["n"] and ox["n"] else None,
        "Si_flatness_um": (si["y_max"] - si["y_min"]) if si["n"] else None,
    }
    return {"native": native_block, "exported": exported_cross_section(mesh_path, module, x_lo, x_hi)}


# ------------------------------------------------------------------------- baseline
@dataclass
class MaskedStackBaseline:
    provenance: str
    vpsd_path: str
    vpsd_sha256: str
    baseline_mesh_path: str
    requested: Dict[str, Any]
    regions: Regions
    forbidden_call_counts: Dict[str, int]
    native_pre_mask: Dict[str, np.ndarray]
    native_post_mask: Dict[str, np.ndarray]
    mask_creation_native_shift_um: Dict[str, float]     # max |dy| of Si / SiO2 level sets
    pre_mask: Dict[str, Any]                            # exported measurements, window core
    post_mask: Dict[str, Any]
    baseline_region_metrics: Dict[str, Any]
    module: Any = field(repr=False, default=None)


def build_masked_explicit_stack(
    out_dir, *, x_extent_um, y_extent_um, silicon_depth_um, oxide_top_um, grid_delta_um,
    mask_spans_um, mask_height_um, mask_material, reach_um, name="explicit_masked",
) -> MaskedStackBaseline:
    from tcad.backends.viennaps import session
    from tcad.backends.viennaps.io import save_volume_mesh

    module = session.require_viennaps()
    spans = sorted((float(a), float(b)) for a, b in mask_spans_um)
    # the open window is the gap between the two opaque spans
    gaps = [(spans[i][1], spans[i + 1][0]) for i in range(len(spans) - 1)]
    if len(gaps) != 1:
        raise ValueError("this helper supports exactly one central open window")
    window = gaps[0]
    regions = derive_regions(window, x_extent_um, grid_delta_um, reach_um)
    floor = float(silicon_depth_um)

    with oxfix.forbid_oxidation_and_process(module) as counts:
        domain = session.create_domain(grid_delta_um, x_extent_um, y_extent_um)
        module.MakePlane(domain, 0.0, module.Material.Si).apply()
        module.MakePlane(domain, float(oxide_top_um), module.Material.SiO2, True).apply()
        native_pre = native_surfaces(domain)
        mesh_pre = save_volume_mesh(domain, str(Path(out_dir) / f"{name}_premask"), floor_depth_um=floor)
        session.remask_domain(domain, grid_delta_um, x_extent_um, spans, mask_height_um, mask_material)
        native_post = native_surfaces(domain)
        mesh_post = save_volume_mesh(domain, str(Path(out_dir) / f"{name}_postmask"), floor_depth_um=floor)
        vpsd = str(Path(out_dir) / f"{name}_baseline.vpsd")
        session.save_domain_state(domain, vpsd)

    shift = {}
    for material in ("Si", "SiO2"):
        a, b = native_pre[material], native_post[material]
        a, b = a[np.lexsort((a[:, 1], a[:, 0]))], b[np.lexsort((b[:, 1], b[:, 0]))]
        shift[material] = (float(np.abs(a[:, 1] - b[:, 1]).max()) if a.shape == b.shape
                           else float("nan"))
    x0, x1 = regions.core_um
    requested = {
        "provenance": PROVENANCE,
        "note": "explicit initial Si/SiO2 stack + explicit test mask, all stated as inputs; "
                "not grown, not deposited, not lithography",
        "si_surface_y_um": 0.0, "si_floor_um": -floor,
        "sio2": {"top_y_um": float(oxide_top_um), "thickness_um": float(oxide_top_um),
                 "covers": "whole width"},
        "mask": {"material": mask_material, "opaque_spans_um": spans, "open_window_um": list(window),
                 "height_um": float(mask_height_um),
                 "note": "exists BEFORE the etch; sits on the oxide top over the opaque spans"},
        "grid_delta_um": float(grid_delta_um), "x_extent_um": float(x_extent_um),
        "y_extent_um": float(y_extent_um),
    }
    native_regions = region_metrics(native_post, mesh_post, module, x0, x1)
    return MaskedStackBaseline(
        provenance=PROVENANCE, vpsd_path=vpsd, vpsd_sha256=sha256_file(vpsd),
        baseline_mesh_path=mesh_post, requested=requested, regions=regions,
        forbidden_call_counts=dict(counts), native_pre_mask=native_pre, native_post_mask=native_post,
        mask_creation_native_shift_um=shift,
        pre_mask=region_metrics(native_pre, mesh_pre, module, x0, x1),
        post_mask=native_regions, baseline_region_metrics=native_regions, module=module)


# ------------------------------------------------------------------------- etch run
@dataclass
class EtchOutcome:
    label: str
    model: str
    recipe: Dict[str, Any]
    final_mesh: str
    result: Dict[str, Any]
    copy_matches_baseline: Dict[str, Any]
    oxidation_calls: int
    warnings_raised: List[str]
    native_after: Dict[str, np.ndarray] = field(repr=False, default_factory=dict)
    core_before: Dict[str, Any] = field(default_factory=dict)
    core_after: Dict[str, Any] = field(default_factory=dict)
    bands_before: List[Dict[str, Any]] = field(default_factory=list)
    bands_after: List[Dict[str, Any]] = field(default_factory=list)


def run_etch_on_independent_copy(baseline: MaskedStackBaseline, model: str, recipe: Dict[str, Any],
                                 out_dir, label: str) -> EtchOutcome:
    """Load the saved post-mask state as a FRESH domain, prove it equals the baseline, run the
    registered etch step on it, measure. The saved file and every other copy are untouched."""
    from tcad.backends.viennaps import session
    from tcad.backends.viennaps.io import save_volume_mesh
    import tcad.process.etching  # noqa: F401
    from tcad.process import registry

    module = baseline.module
    assert sha256_file(baseline.vpsd_path) == baseline.vpsd_sha256, "baseline .vpsd changed on disk"
    domain = session.load_domain_state(baseline.vpsd_path)
    before_native = native_surfaces(domain)
    # the copy must equal the baseline BEFORE the etch (native level sets + exported mesh, exactly)
    copy_mesh = save_volume_mesh(domain, str(Path(out_dir) / f"{label}_copy_preetch"),
                                 floor_depth_um=-baseline.requested["si_floor_um"])
    a, b = oxfix._read_mesh(baseline.baseline_mesh_path, module), oxfix._read_mesh(copy_mesh, module)
    same_mesh = (a["points"].shape == b["points"].shape and bool(np.array_equal(a["points"], b["points"]))
                 and bool(np.array_equal(a["triangles"], b["triangles"])) and bool(np.array_equal(a["tags"], b["tags"])))
    native_dev = {m: (float(np.abs(before_native[m][np.lexsort((before_native[m][:, 1], before_native[m][:, 0]))][:, 1]
                                 - baseline.native_post_mask[m][np.lexsort((baseline.native_post_mask[m][:, 1],
                                                                             baseline.native_post_mask[m][:, 0]))][:, 1]).max())
                      if before_native[m].shape == baseline.native_post_mask[m].shape else float("nan"))
                  for m in ("Si", "SiO2")}
    match = {"exported_mesh_identical": same_mesh, "native_max_abs_dy_um": native_dev}

    core, bands = baseline.regions.core_um, baseline.regions.protected_bands_um
    core_before = region_metrics(before_native, copy_mesh, module, *core)
    bands_before = [region_metrics(before_native, copy_mesh, module, *bnd) for bnd in bands]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with forbid_oxidation(module) as counts:
            step = registry.get("etching", model)(inherited_domain=domain)
            result = step.run(dict(recipe), str(Path(out_dir) / label))
    after_native = native_surfaces(step.last_domain)
    core_after = region_metrics(after_native, result["final_mesh"], module, *core)
    bands_after = [region_metrics(after_native, result["final_mesh"], module, *bnd) for bnd in bands]
    return EtchOutcome(
        label=label, model=model, recipe=dict(recipe), final_mesh=result["final_mesh"], result=result,
        copy_matches_baseline=match, oxidation_calls=counts["Oxidation"],
        warnings_raised=[str(w.message) for w in caught], native_after=after_native,
        core_before=core_before, core_after=core_after, bands_before=bands_before, bands_after=bands_after)


# ---------------------------------------------------------------------- derived deltas
def native_removal(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Vertical removal from NATIVE level-set positions: Si = drop of the Si surface; oxide =
    loss of oxide thickness (SiO2 surface minus Si surface). Positive = removed."""
    b, a = before["native"], after["native"]
    return {
        "si_removed_um": b["Si_top"]["y_mean"] - a["Si_top"]["y_mean"],
        "oxide_removed_um": b["oxide_thickness_mean"] - a["oxide_thickness_mean"],
        "oxide_thickness_before_um": b["oxide_thickness_mean"],
        "oxide_thickness_after_um": a["oxide_thickness_mean"],
    }


def exported_view(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """The exported-mesh corroboration, reported separately from the native verdict quantities."""
    def g(block, material, key):
        return block["exported"]["materials"].get(material, {}).get(key)
    return {
        "sio2_columns_present_before": g(before, "SiO2", "columns_present"),
        "sio2_columns_present_after": g(after, "SiO2", "columns_present") or 0,
        "si_top_before": g(before, "Si", "top_mean"), "si_top_after": g(after, "Si", "top_mean"),
    }


def describe_baseline(b: MaskedStackBaseline) -> str:
    r = b.requested
    nat = b.baseline_region_metrics["native"]
    exp = b.baseline_region_metrics["exported"]["materials"]
    return (
        f"[{b.provenance}] REQUESTED (input): Si surface y=0 floor {r['si_floor_um']}; SiO2 top y={r['sio2']['top_y_um']} "
        f"(thickness {r['sio2']['thickness_um']}); mask {r['mask']['material']} spans {r['mask']['opaque_spans_um']} "
        f"window {r['mask']['open_window_um']} height {r['mask']['height_um']}; grid {r['grid_delta_um']}\n"
        f"  REGIONS: window {b.regions.window_um} core {tuple(round(v, 4) for v in b.regions.core_um)} "
        f"bands {[tuple(round(v, 4) for v in x) for x in b.regions.protected_bands_um]} -- {b.regions.basis}\n"
        f"  NATIVE (post-mask, core): Si top {nat['Si_top']['y_mean']:.6f}, SiO2 top {nat['SiO2_top']['y_mean']:.6f}, "
        f"oxide thickness {nat['oxide_thickness_mean']:.6f}\n"
        f"  EXPORTED (post-mask, core columns): Si top {exp['Si']['top_mean']:.6f}, SiO2 bottom {exp['SiO2']['bottom_mean']:.6f} "
        f"top {exp['SiO2']['top_mean']:.6f} (interface offset vs native is an exporter representation offset)\n"
        f"  mask creation moved native Si/SiO2 level sets by (max |dy| um): {b.mask_creation_native_shift_um}\n"
        f"  saved baseline {Path(b.vpsd_path).name} sha256={b.vpsd_sha256[:16]}...; forbidden calls during build: "
        f"{b.forbidden_call_counts}")


def verify_baseline_pristine(baseline: MaskedStackBaseline, out_dir, label="pristine_probe") -> Dict[str, Any]:
    """After any number of etch runs: the saved `.vpsd` is byte-identical and a NEW copy still
    exports exactly the baseline mesh -- so no experiment changed another's starting state."""
    from tcad.backends.viennaps import session
    from tcad.backends.viennaps.io import save_volume_mesh

    domain = session.load_domain_state(baseline.vpsd_path)
    mesh = save_volume_mesh(domain, str(Path(out_dir) / label), floor_depth_um=-baseline.requested["si_floor_um"])
    a, b = oxfix._read_mesh(baseline.baseline_mesh_path, baseline.module), oxfix._read_mesh(mesh, baseline.module)
    return {"vpsd_sha256_unchanged": sha256_file(baseline.vpsd_path) == baseline.vpsd_sha256,
            "fresh_copy_export_identical": bool(
                a["points"].shape == b["points"].shape and np.array_equal(a["points"], b["points"])
                and np.array_equal(a["triangles"], b["triangles"]) and np.array_equal(a["tags"], b["tags"]))}
