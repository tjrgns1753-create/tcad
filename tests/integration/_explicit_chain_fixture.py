# -*- coding: utf-8 -*-
"""TEST-ONLY helper: an EXPLICIT INITIAL Si/SiO2 domain STATE that later process steps can continue from.

Provenance: ``DIRECT_EXPLICIT_GEOMETRY``. The SiO2 here is a structure the test STATES as an input. It is
  * NOT an oxidation growth result, NOT a deposited oxide, NOT a Deal-Grove result;
  * built by ``MakePlane(...).apply()`` (explicit initial geometry, allowed) with ``vps.Oxidation`` and
    ``vps.Process`` both trapped for the whole construction (counted, then restored);
  * saved as a ``.vpsd`` state (SHA-256 recorded) so every scenario loads its OWN independent copy.
It says nothing about oxidation kinetics, Si consumption, or any oxide thickness a process produced.

Why a new helper instead of ``_explicit_oxide_fixture.build_explicit_si_sio2_stack`` (Batch 1, approved and frozen):
that function keeps its ``domain`` as a local variable and never saves it, so a later process step cannot continue
from it. It is reused here for what it already provides -- the trap context manager and the exported-mesh
measurement -- and is not modified.

Three things are kept apart everywhere: REQUESTED input values, NATIVE level-set positions and EXPORTED-mesh
measurements. The plain exporter places the Si/SiO2 interface a grid-proportional distance from the native
level-set position (an exporter representation offset of unidentified cause, see the Batch 2 audit); it is reported,
never read as oxide growth or Si consumption.

Every coordinate a test judges is MEASURED from a real domain or mesh -- nothing is copied from an earlier oxidation run.
"""
from __future__ import annotations

import contextlib
import hashlib
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _explicit_oxide_fixture as oxfix  # Batch 1 helper: reused, never modified

PROVENANCE = oxfix.PROVENANCE
_FLOAT32_ULP_REL = 2.0 ** -23


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sample_columns(x_extent_um: float, n: int = 9, margin_um: float = 0.5) -> np.ndarray:
    """Interior columns, kept away from the domain side walls (which are not part of any process claim)."""
    half = 0.5 * x_extent_um - margin_um
    return np.linspace(-half, half, n)


def native_eps(scale_um: float, *, ulps: int = 16) -> float:
    """Comparison bound for two readings of the SAME native level set: `ulps` float64 ulps of the coordinate scale (the
    surface is read by linear interpolation of double-precision level-set values). A preserved material must agree with
    itself to this bound -- measured drift of Si / SiO2 under later deposition, etch and re-mask steps is 0."""
    return ulps * 2.0 ** -52 * max(float(scale_um), 1.0)


def native_request_tolerance(grid_delta_um: float) -> float:
    """Bound for comparing a NATIVE level-set position with the REQUESTED input value (two different statements).

    THIS BOUND IS OBSERVATIONAL, NOT MECHANISM-DERIVED. The native reading of a freshly built explicit stack differs from
    the requested value by a tiny offset whose cause is UNKNOWN_NUMERICAL_REPRESENTATION_OFFSET: the installed ViennaLS
    5.8.5 / ViennaPS 4.6.2 wheels ship no C++ headers or sources and their stubs and docstrings say nothing about it, so no
    mechanism is asserted for it.
      * definition basis   : the offset observed on the explicit stacks, plus a factor-10 margin: 1e-11 * grid.
      * observed offset    : 1.0e-12 * grid (Si top -1e-13 on the 0.1 um grid, -5e-14 on the 0.05 um grid), and over the
                             pre-registered matrix in docs/audits/2026-09-21-batch4-explicit-oxide-chaining-litho/
                             raw/native_request_offset_matrix.out.txt.
      * verified range     : only the grids / oxide heights of that matrix (and of these two tests).
      * one more observation (same audit file): with the reader `vls.ToSurfaceMesh(level_set, mesh, 0.05, eps)` the
                             observed offset was 1.1e-16 / 1e-13 / 1e-10 um for eps = 1e-15 / 1e-12 (its default, used by
                             `native_column_tops`) / 1e-9 on the 0.1 um grid, i.e. it followed eps * grid in those three cases.
                             It is recorded as an observation only: it does not show whether the STORED level set is offset,
                             and no source or document was found that states what eps does.
      * outside that range : UNKNOWN. The bound is not widened to fit a result; a stack outside the range must be measured
                             first."""
    return 1.0e-11 * float(grid_delta_um)


def exported_tolerance(grid_delta_um: float) -> float:
    """Bound for comparing an EXPORTED interface position between two different exports: one tenth of the level-set
    cell. This is the bound the two migrated tests already carried (`TOL = 0.01` on the 0.1 um grid, `0.1*grid_delta`),
    kept, not retuned. Two exports of the same native surface differ by an exporter representation offset (measured
    <= 0.0099 * grid on the explicit stacks); a tenth of a cell is above that offset yet far below any real geometry
    change of a preserved material, whose exactness is settled by the NATIVE comparison instead."""
    return 0.1 * float(grid_delta_um)


def geometry_eps(points, *, ulps: int = 4) -> float:
    """Same-point tolerance derived from float32 coordinate spacing (the exported meshes are float32): `ulps` ulps of the
    largest coordinate. It is a serialization bound, not a physical resolution."""
    return ulps * _FLOAT32_ULP_REL * float(np.abs(np.asarray(points)[:, :2]).max())


@contextlib.contextmanager
def count_solver_calls(module):
    """Count -- do NOT block -- `vps.Oxidation` and `vps.Process` calls (pass-through). Restored in `finally`. Used where a
    step may legitimately call `Process` (an etch, a deposition) while another step (zero-duration oxidation) must not."""
    counts = {"Oxidation": 0, "Process": 0}
    original_oxidation, original_process = module.Oxidation, module.Process

    def oxidation(*a, **k):
        counts["Oxidation"] += 1
        return original_oxidation(*a, **k)

    def process(*a, **k):
        counts["Process"] += 1
        return original_process(*a, **k)

    try:
        module.Oxidation, module.Process = oxidation, process
        yield counts
    finally:
        module.Oxidation, module.Process = original_oxidation, original_process


# ------------------------------------------------------------------------------- native level sets
def _ymax_at(nodes, lines, xs):
    """Highest crossing y of the level-set surface polyline with each vertical line x (NaN if none)."""
    xs = np.asarray(xs, dtype=float)
    if len(lines) == 0:
        return np.full(len(xs), np.nan)
    p, q = nodes[lines[:, 0]], nodes[lines[:, 1]]
    x1, y1, x2, y2 = p[:, 0], p[:, 1], q[:, 0], q[:, 1]
    X = xs[:, None]
    inside = (x1 - X) * (x2 - X) <= 0
    dx = x2 - x1
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(dx != 0, (X - x1) / dx, 0.0)
    y = np.where(inside, y1 + t * (y2 - y1), -np.inf).max(axis=1)
    y[~np.isfinite(y)] = np.nan
    return y


def native_column_tops(domain, xs) -> Dict[str, np.ndarray]:
    """{material: top y of that material's NATIVE level set at each column x}, from real surface meshes.

    Level sets are nested, so the top of material k at a column is the top of its own level set; the thickness of
    material k at that same column is (top_k - top_{k-1}). Only same-column values are ever compared."""
    import viennals as vls

    material_map = domain.getMaterialMap()
    out: Dict[str, np.ndarray] = {}
    for i, level_set in enumerate(domain.getLevelSets()):
        mesh = vls.Mesh()
        vls.ToSurfaceMesh(level_set, mesh).apply()
        nodes = np.array(mesh.getNodes(), dtype=float).reshape(-1, 3)[:, :2]
        lines = np.array(mesh.getLines(), dtype=np.int64).reshape(-1, 2)
        out[str(material_map.getMaterialAtIdx(i)).split("'")[1]] = _ymax_at(nodes, lines, xs)
    return out


def native_level_set_order(domain) -> List[str]:
    material_map = domain.getMaterialMap()
    return [str(material_map.getMaterialAtIdx(i)).split("'")[1] for i in range(int(domain.getNumberOfLevelSets()))]


# ------------------------------------------------------------------------------ exported meshes
def read_exported(mesh_path, module) -> Dict[str, Any]:
    """Points / triangles / tags / names of an exported volume mesh (via the Batch 1 measurement code)."""
    return oxfix.measure_exported_mesh(str(mesh_path), module)["_mesh"]


def exported_columns(mesh_path, module, xs) -> Dict[str, Dict[str, np.ndarray]]:
    """{material: {'ymin': [...], 'ymax': [...]}} of each material's vertical extent at each column x of the EXPORTED mesh
    (NaN where the material is absent at that column). Columns are compared with the same x, never max(y) over a window."""
    m = read_exported(mesh_path, module)
    pts, tris, tags, names = m["points"], m["triangles"], m["tags"], m["names"]
    xs = np.asarray(xs, dtype=float)
    out: Dict[str, Dict[str, np.ndarray]] = {}
    for tag, name in names.items():
        sel = tris[tags == tag]
        ymin, ymax = np.full(len(xs), np.nan), np.full(len(xs), np.nan)
        if len(sel):
            tx = pts[sel][:, :, 0]
            lo, hi = tx.min(axis=1), tx.max(axis=1)
            for j, x in enumerate(xs):
                ys = []
                for t in sel[(lo <= x) & (hi >= x)]:
                    v = pts[t]
                    for a, b in ((0, 1), (1, 2), (2, 0)):
                        (xa, ya), (xb, yb) = v[a], v[b]
                        if xa == xb:
                            if xa == x:
                                ys += [ya, yb]
                        elif (xa - x) * (xb - x) <= 0:
                            ys.append(ya + (x - xa) / (xb - xa) * (yb - ya))
                if ys:
                    ymin[j], ymax[j] = min(ys), max(ys)
        out[name] = {"ymin": ymin, "ymax": ymax}
    return out


def exported_material_summary(mesh_path, module) -> Dict[str, Any]:
    """Per-material x/y range and triangle count of the exported mesh (Batch 1 measurement code)."""
    return oxfix.measure_exported_mesh(str(mesh_path), module)["per_material"]


# --------------------------------------------------------------------------------------- the state
@dataclass
class ExplicitChainState:
    """An explicit initial Si/SiO2 domain state, saved as `.vpsd`, with what was requested / measured natively /
    measured on the exported mesh. NOT an oxidation result, NOT a deposited oxide."""
    provenance: str
    vpsd_path: str
    vpsd_sha256: str
    mesh_path: str
    requested: Dict[str, Any]
    forbidden_call_counts: Dict[str, int]
    level_set_order: List[str]
    columns_um: np.ndarray
    native_tops: Dict[str, np.ndarray]                # native level-set top per material at `columns_um`
    exported_columns: Dict[str, Dict[str, np.ndarray]]  # exported vertical extent per material at `columns_um`
    exported_summary: Dict[str, Any]
    module: Any = field(repr=False, default=None)
    # STRONG references to every independent domain ever handed out, with the label of the load that produced it. They are
    # kept alive on purpose: an `id()` is only unique among LIVE objects, so identity can be judged only while all of them exist.
    _domains: List[Any] = field(default_factory=list, repr=False)
    _labels: List[str] = field(default_factory=list, repr=False)

    def load_independent_copy(self, label: str):
        """A NEW domain loaded from the saved `.vpsd` (each call reads the file again; nothing is copied in memory, so no
        solver/domain state is shared between scenarios). The saved file must be byte-identical to its recorded SHA-256
        every time (a scenario that mutated the shared file would be caught here). The new object must be a different
        object from every domain handed out before, compared by identity (`is`), not by a recorded `id()`."""
        from tcad.backends.viennaps import session

        assert sha256_file(self.vpsd_path) == self.vpsd_sha256, "the initial .vpsd changed on disk"
        domain = session.load_domain_state(self.vpsd_path)
        for previous in self._domains:
            assert domain is not previous, "a domain object was handed out twice"
        self._domains.append(domain)
        self._labels.append(label)
        return domain

    @property
    def load_labels(self) -> List[str]:
        return list(self._labels)

    @property
    def copies_loaded(self) -> List[int]:
        """Report-only view: the id() of every held domain, derived from the strong-reference list (never stored)."""
        return [id(d) for d in self._domains]

    def assert_independent_loads(self, expected_labels) -> None:
        """Every scenario performed its OWN load, and all the domains handed out are pairwise different, still-alive objects."""
        assert self._labels == list(expected_labels), (
            f"the loads performed differ from the scenarios run: {self._labels} != {list(expected_labels)}")
        assert len(set(self._labels)) == len(self._labels), f"a scenario label was used twice: {self._labels}"
        for i, a in enumerate(self._domains):
            for b in self._domains[i + 1:]:
                assert a is not b, "one domain object served two scenarios"
        ids = self.copies_loaded
        assert len(set(ids)) == len(ids), "held domains share an id (impossible for distinct live objects)"
        assert self.pristine(), "the saved initial .vpsd was modified"

    def pristine(self) -> bool:
        return sha256_file(self.vpsd_path) == self.vpsd_sha256


def build_explicit_chain_state(out_dir, *, x_extent_um: float, y_extent_um: float, silicon_depth_um: float,
                               oxide_top_um: float, grid_delta_um: float, columns: int = 9,
                               name: str = "explicit_chain_initial", include_oxide: bool = True,
                               extra_columns_um=()) -> ExplicitChainState:
    """Explicit initial stack: Si half-space (surface y = 0) plus a SiO2 plane over the whole width whose top is the
    REQUESTED `oxide_top_um`. No mask, no resist, no oxidation model, no process solver.

    `include_oxide=False` builds the Si half-space ALONE. It exists only so a test can prove that its SiO2 assertions
    really fail when the initial oxide is missing (a false-green guard); the resulting state is not a valid chaining input."""
    for label, value in (("x_extent_um", x_extent_um), ("y_extent_um", y_extent_um),
                         ("silicon_depth_um", silicon_depth_um), ("oxide_top_um", oxide_top_um),
                         ("grid_delta_um", grid_delta_um)):
        if not (isinstance(value, (int, float)) and math.isfinite(value) and value > 0):
            raise ValueError(f"{label} must be a finite positive number, got {value!r}")
    if oxide_top_um >= y_extent_um:
        raise ValueError("oxide_top_um must lie inside y_extent_um")
    if oxide_top_um < 2.0 * grid_delta_um:
        # refuse instead of retuning: a stack thinner than two cells cannot carry a measurable Si/SiO2 pair
        raise ValueError("oxide_top_um must be at least two grid cells")

    from tcad.backends.viennaps import session
    from tcad.backends.viennaps.io import save_volume_mesh

    module = session.require_viennaps()
    xs = np.unique(np.concatenate([sample_columns(x_extent_um, columns), np.asarray(list(extra_columns_um), dtype=float)]))
    requested = {
        "provenance": PROVENANCE, "note": "explicit initial structure; not grown, not deposited",
        "si": {"x_um": [-x_extent_um / 2.0, x_extent_um / 2.0], "surface_y_um": 0.0,
               "export_floor_um": -float(silicon_depth_um)},
        "sio2": ({"top_y_um": float(oxide_top_um), "covers": "whole width"} if include_oxide else None),
        "grid_delta_um": float(grid_delta_um), "y_extent_um": float(y_extent_um),
    }
    with oxfix.forbid_oxidation_and_process(module) as counts:
        domain = session.create_domain(grid_delta_um, x_extent_um, y_extent_um)
        module.MakePlane(domain, 0.0, module.Material.Si).apply()
        if include_oxide:
            module.MakePlane(domain, float(oxide_top_um), module.Material.SiO2, True).apply()
        vpsd =str(Path(out_dir) / f"{name}.vpsd")
        session.save_domain_state(domain, vpsd)
        mesh_path = save_volume_mesh(domain, str(Path(out_dir) / name), floor_depth_um=silicon_depth_um)
        native = native_column_tops(domain, xs)
        order = native_level_set_order(domain)
    return ExplicitChainState(
        provenance=PROVENANCE, vpsd_path=vpsd, vpsd_sha256=sha256_file(vpsd), mesh_path=mesh_path,
        requested=requested, forbidden_call_counts=dict(counts), level_set_order=order, columns_um=xs,
        native_tops=native, exported_columns=exported_columns(mesh_path, module, xs),
        exported_summary=exported_material_summary(mesh_path, module), module=module)


def describe(state: ExplicitChainState) -> str:
    """Requested / native / exported kept apart, in one printable block."""
    r = state.requested
    nat = {k: round(float(np.nanmean(v)), 6) for k, v in state.native_tops.items()}
    exp = {k: (round(float(np.nanmean(v["ymin"])), 6), round(float(np.nanmean(v["ymax"])), 6))
           for k, v in state.exported_columns.items()}
    sio2_top = r["sio2"]["top_y_um"] if r["sio2"] else None
    return (f"[{state.provenance}] REQUESTED (input): Si surface y=0, export floor {r['si']['export_floor_um']}; "
            f"SiO2 top y={sio2_top}; grid {r['grid_delta_um']}\n"
            f"  NATIVE level-set tops (mean over {len(state.columns_um)} columns), order {state.level_set_order}: {nat}\n"
            f"  EXPORTED mesh column extents (ymin, ymax): {exp}\n"
            f"  (any native-vs-exported difference is an exporter representation offset; it is not oxide growth or Si consumption)\n"
            f"  forbidden calls while building: {state.forbidden_call_counts}; initial .vpsd sha256={state.vpsd_sha256[:16]}...")


# ---------------------------------------------------------------------------------- shared measurement / checks
class StageMeasure:
    """One step's result measured twice, at the state's columns: on its persisted NATIVE domain and on its EXPORTED mesh."""

    def __init__(self, state: ExplicitChainState, result, module):
        from tcad.backends.viennaps import session

        self.result = result
        domain = session.load_domain_state(result.domain_state_path)
        self.native = native_column_tops(domain, state.columns_um)
        self.native_order = native_level_set_order(domain)
        self.exported = exported_columns(result.volume_mesh_path, module, state.columns_um)
        self.summary = exported_material_summary(result.volume_mesh_path, module)
        self.transition = (getattr(result, "metadata", None) or {}).get("state_transition")

    @property
    def materials(self) -> List[str]:
        return sorted(self.summary)


def run_steps_from_state(state: ExplicitChainState, tmp, tag: str, steps):
    """Run `steps` on a NEW independent copy of the saved initial state via run_flow(initial_domain=...). Returns
    (results, solver-call counts, [StageMeasure, ...]); Oxidation / Process are COUNTED (pass-through), not blocked."""
    import os
    import warnings

    from tcad.process.flow import run_flow

    domain = state.load_independent_copy(tag)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")            # inherited-domain notices about ignored initial-geometry keys
        with count_solver_calls(state.module) as calls:
            results = run_flow(steps, os.path.join(str(tmp), tag), initial_domain=domain)
    return results, dict(calls), [StageMeasure(state, r, state.module) for r in results]


def assert_si_sio2_preserved(state: ExplicitChainState, stage: StageMeasure, grid_delta_um: float, where: str,
                             sio2_columns=None) -> None:
    """Si and SiO2 keep the geometry of the explicit initial state: NATIVE level sets to float64 rounding, EXPORTED
    vertical extent at each column to a tenth of a cell, and present in exactly the same columns. `sio2_columns`
    (boolean per state column) restricts the SiO2 comparison to columns that are not legitimately etched -- Si is always
    compared at every column."""
    n_eps, e_tol = native_eps(state.requested["y_extent_um"]), exported_tolerance(grid_delta_um)
    all_cols = np.ones(len(state.columns_um), dtype=bool)
    for mat, cols in (("Si", all_cols), ("SiO2", all_cols if sio2_columns is None else np.asarray(sio2_columns, dtype=bool))):
        assert mat in stage.native and mat in stage.exported, (
            f"{where}: {mat} vanished (native {sorted(stage.native)}, exported {stage.materials})")
        n0, n1 = state.native_tops[mat][cols], stage.native[mat][cols]
        assert np.all(np.isfinite(n1)) and np.max(np.abs(n1 - n0)) <= n_eps, (
            f"{where}: native {mat} level set moved by {np.nanmax(np.abs(n1 - n0)):.3g} um")
        e0, e1 = state.exported_columns[mat], stage.exported[mat]
        assert np.array_equal(np.isnan(e0["ymax"])[cols], np.isnan(e1["ymax"])[cols]), f"{where}: {mat} columns changed"
        for key in ("ymin", "ymax"):
            d = np.nanmax(np.abs(e1[key][cols] - e0[key][cols]))
            assert d <= e_tol, f"{where}: exported {mat} {key} moved by {d:.4f} um (> {e_tol:.4f}, a tenth of a cell)"


def _reason_matches(message: str, expected) -> bool:
    if callable(expected):
        return bool(expected(message))
    parts = (expected,) if isinstance(expected, str) else tuple(expected)
    return bool(parts) and all(isinstance(p, str) and p and p in message for p in parts)


def assert_fails(check, label: str, expected) -> None:
    """False-green guard with an EXACT reason. `check` must fail with an AssertionError whose message matches `expected`:
    a substring, a tuple of substrings (ALL must appear) or a predicate `message -> bool`.

      * `check` succeeds                                  -> AssertionError "FALSE GREEN"
      * AssertionError, message does not match `expected` -> AssertionError "WRONG FAILURE REASON" (an unrelated failure
        must not pass as sensitivity evidence)
      * any other exception type                          -> propagates unchanged (never swallowed)
      * AssertionError matching `expected`                -> the sensitivity check passes
    """
    if not (callable(expected) or (isinstance(expected, str) and expected)
            or (isinstance(expected, tuple) and expected and all(isinstance(p, str) and p for p in expected))):
        raise TypeError(f"assert_fails({label!r}): `expected` must be a non-empty str, a non-empty tuple of str, or a predicate")
    try:
        check()
    except AssertionError as exc:
        message = str(exc)
        if not _reason_matches(message, expected):
            raise AssertionError(
                f"WRONG FAILURE REASON for {label!r}: the check failed, but not for the expected reason.\n"
                f"  expected: {expected!r}\n  actual:   {message[:300]}") from exc
        print(f"    [sensitivity OK] {label}: fails for the expected reason  ({message.splitlines()[0][:110]})")
        return
    raise AssertionError(f"FALSE GREEN: the check did not fail when {label}")
