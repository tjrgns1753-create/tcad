#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless GUI process dispatch must never hang on a modal dialog -- and must say what each outcome really is.

Root cause of the original bug (docs/handoffs/gui-modal-hang-fix.md, investigations A/B):
run_oxidation()/run_etch()/run_deposition()/etc. used to call `messagebox.showinfo()` unconditionally after a real ViennaPS
success, and `messagebox.showerror()` on failure -- genuine Tk modal dialogs that block the calling thread in `wait_window()`
until someone dismisses them. In a headless/automated session (`app.withdraw()` already called) nobody is present to click,
so the call hung forever (a live py-spy stack trace showed the Tk main thread parked in `showinfo` inside `run_oxidation`).
The fix: `_notify_info()` is log-only, `_notify_error()` always logs and raises a real dialog only while the window is
viewable (`winfo_viewable()`, a LIVE check).

THE CONTRACT THIS TEST PINS: on a hidden GUI, the success, identity, unsupported and worker-failure paths run through the REAL
GUI dispatch (`subprocess.run` -> `tcad_2d_stagewise.py --worker`, real ViennaPS 4.6.2) and the final tkinter messagebox
functions are never called (they are trapped, not mocked around: `_notify_info`/`_notify_error` are NOT patched). After every
scenario the trap is checked immediately, so a regression names the scenario that raised the dialog.

WHAT CHANGED IN THIS MIGRATION (Batch 5). The old version chained a positive-time thermal oxidation -> etch -> deposition and
then used positive-time oxidation + an invalid grid for the failure path. Positive-time oxidation is UNSUPPORTED_BY_MODEL (the
capability gate returns `state_transition.kind == "unsupported"` with `OXIDATION_CAPABILITY_PROOF_MISSING`), so the first
assertion ("real oxidation must produce a real final mesh") could never hold; oxidation growth was never this test's subject.
The scenarios are now independent and each states what it actually is:

  A  withdrawn window and trap calibration
  B  FRESH zero-duration thermal request = MATERIALIZATION of a virgin Si wafer (no earlier wafer existed). NOT an identity.
  C  INHERITED zero-duration thermal request = IDENTITY (the existing wafer is preserved). Compared to B on loaded content.
  D  the GUI's default etch (Bosch DRIE) on C's wafer: a real supported physical step
  E  the GUI's default deposition (Isotropic, SiO2) on D's wafer: a real supported physical step; the SiO2 is a DEPOSITED film
  F  positive-time oxidation on a fresh wafer = UNSUPPORTED_BY_MODEL (unresolved state), not an error and not a success
  G  a worker-side wafer-state/recipe VALIDATION failure (fresh 0 h thermal + grid_delta_um = -1): a `ValueError` raised by
     tcad's own transition builder INSIDE the worker subprocess. It is not a ViennaPS solver exception and not a physical
     simulation failure; ViennaPS never ran.

Bosch DRIE is a ray-traced model and is not bit-reproducible between runs; the test neither seeds nor retries it and asserts
no exact mesh hash or depth -- only physical invariants larger than the exporter's representation offset (0.1 x grid, the
bound used by the Batch 4 tests; the measured exporter drift there was 0.005-0.0099 x grid).

Every measurement is taken from the real exported mesh (and, for B vs C, the loaded native domains). A set of false-green
guards at the end proves each contract check FAILS, for its own reason, when its subject is broken.
"""
import dataclasses
import hashlib
import json
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import meshio
import numpy as np
import tkinter
import tkinter.messagebox  # noqa: F401
import tcad_2d_stagewise as gui
from tcad.backends.viennaps import session as viennaps_session

assert viennaps_session.is_available(), "ViennaPS must be installed for this test"
MODULE = viennaps_session.require_viennaps()

GRID = 0.1                                # um; the level-set grid of every scenario
EXPORT_TOL = 0.1 * GRID                   # smallest geometric change distinguishable from the exporter's representation offset
BLOCKING = ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion", "askretrycancel", "askyesnocancel")
SUCCESS_PHRASES = ("simulation complete", "oxidation complete", "growth complete")     # matched case-insensitively
FILM_OXIDE_MARKER = 1                     # SESSION STATE index of "Film / oxide" (stage list in tcad_2d_stagewise.py)
VALIDATION_MESSAGE = "recipe bounds do not describe a valid virgin Si wafer"
VALIDATION_SOURCE = Path(__file__).resolve().parent.parent.parent / "tcad" / "physics" / "wafer_state_accumulation.py"


# ------------------------------------------------------------------------------------------------ trap and observer
class Trap:
    """Replaces every blocking tkinter messagebox function with a recorder. The set is checked against what this Python's
    messagebox module actually exposes, so a function the list forgot fails the test instead of staying live."""

    def __init__(self, module):
        exposed = sorted(n for n in dir(module) if n.startswith(("show", "ask")))
        assert exposed == sorted(BLOCKING), f"messagebox exposes {exposed}; the trap list is {sorted(BLOCKING)}"
        self.module, self.calls, self.originals = module, [], {}

    def install(self):
        for name in BLOCKING:
            self.originals[name] = getattr(self.module, name)

            def trap(*args, _name=name, **kwargs):
                self.calls.append((_name, args[:2]))
                return None

            setattr(self.module, name, trap)

    def restore(self):
        for name, fn in self.originals.items():
            setattr(self.module, name, fn)
        self.originals = {}

    def calibrate(self):
        """Call every trapped function directly once: each call must be recorded (a trap that records nothing proves nothing).
        The calibration records are cleared afterwards, so scenarios start from an empty log."""
        self.calls.clear()
        for name in BLOCKING:
            getattr(self.module, name)("calibration", "direct call")
        recorded = [c[0] for c in self.calls]
        assert recorded == list(BLOCKING), f"the trap did not record every direct call: {recorded}"
        self.calls.clear()

    def assert_none(self, where):
        if self.calls:
            raise AssertionError(f"{where}: {len(self.calls)} modal dialog call(s) reached tkinter.messagebox: {self.calls}")


class WorkerObserver:
    """Pass-through observer on `subprocess.run` (the real call still happens). It records each `--worker` launch, whether the
    result file already existed before the worker ran, its return code, and the JSON the worker wrote."""

    def __init__(self, module):
        self.module, self.runs, self.original = module, [], None

    def install(self):
        self.original = self.module.run

        def run(*args, **kwargs):
            argv = args[0] if args else kwargs.get("args")
            is_worker = "--worker" in argv
            result_path = Path(argv[-1]) if is_worker else None
            existed = result_path.exists() if is_worker else None
            completed = self.original(*args, **kwargs)
            if is_worker:
                result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
                self.runs.append({"returncode": completed.returncode, "result_existed_before": existed, "result": result})
            return completed

        self.module.run = run

    def restore(self):
        if self.original is not None:
            self.module.run = self.original


# ------------------------------------------------------------------------------------------------ measurement
@dataclasses.dataclass
class Geom:
    """The exported mesh, measured at the sample columns (same x column always compared with itself)."""
    materials: list
    area: dict
    ymin: dict
    ymax: dict
    bbox: list
    finite: bool
    triangles: dict
    sha256: str


def _column_extent(points, tris, x):
    ys = []
    for t in tris:
        v = points[t][:, :2]
        for a, b in ((0, 1), (1, 2), (2, 0)):
            (xa, ya), (xb, yb) = v[a], v[b]
            if xa == xb:
                if xa == x:
                    ys += [ya, yb]
            elif (xa - x) * (xb - x) <= 0:
                ys.append(ya + (x - xa) / (xb - xa) * (yb - ya))
    return (min(ys), max(ys)) if ys else (np.nan, np.nan)


def measure(mesh_path, xs) -> Geom:
    mesh = meshio.read(mesh_path)
    pts = mesh.points
    area, ymin, ymax, tri_count = {}, {}, {}, {}
    for block, data in zip(mesh.cells, mesh.cell_data["Material"]):
        if block.type != "triangle":
            continue
        for tag in np.unique(data):
            tri = block.data[np.asarray(data) == tag]
            name = str(MODULE.Material(int(tag))).split("'")[1]
            p = pts[tri][:, :, :2]
            area[name] = float(0.5 * np.abs((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
                                            - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1])).sum())
            ext = np.array([_column_extent(pts, tri, x) for x in xs])
            ymin[name], ymax[name], tri_count[name] = ext[:, 0], ext[:, 1], int(len(tri))
    return Geom(sorted(area), area, ymin, ymax,
                [float(pts[:, 0].min()), float(pts[:, 0].max()), float(pts[:, 1].min()), float(pts[:, 1].max())],
                bool(np.isfinite(pts).all() and all(np.isfinite(v).all() for v in list(ymin.values()) + list(ymax.values()))),
                tri_count, hashlib.sha256(Path(mesh_path).read_bytes()).hexdigest())


def native_fingerprint(vpsd_path):
    """Content of a saved domain: material order and the surface polyline of every level set. Two `.vpsd` files that differ
    byte-wise (metadata) but hold the same domain give the same fingerprint."""
    import viennals as vls

    domain = viennaps_session.load_domain_state(vpsd_path)
    material_map = domain.getMaterialMap()
    names, surfaces = [], []
    for i, level_set in enumerate(domain.getLevelSets()):
        mesh = vls.Mesh()
        vls.ToSurfaceMesh(level_set, mesh).apply()
        names.append(str(material_map.getMaterialAtIdx(i)).split("'")[1])
        surfaces.append((np.array(mesh.getNodes(), dtype=float), np.array(mesh.getLines(), dtype=np.int64)))
    return names, surfaces


def same_native(a, b):
    return a[0] == b[0] and len(a[1]) == len(b[1]) and all(
        np.array_equal(n1, n2) and np.array_equal(l1, l2) for (n1, l1), (n2, l2) in zip(a[1], b[1]))


@dataclasses.dataclass
class Outcome:
    label: str
    log: str                      # the log text added by THIS action (the notification text is part of it)
    runs: list                    # worker launches during this action
    result: object                # the worker's JSON (None if no worker ran / no file)
    mesh: object                  # last_final_mesh after the action
    domain_state: object
    geom: object                  # Geom of the mesh (None if no mesh)
    processed: bool
    etched: bool
    stage_before: str
    stage_after: str
    stages_before: frozenset
    stages_after: frozenset
    film_label_after: str         # the on-screen text of the "Film / oxide" SESSION STATE label ("● ..." lit / "○ ..." not lit)
    completed_steps: int
    physics: object
    modal_calls: int
    wafer_width: float
    wafer_depth: float

    @property
    def transition(self):
        return (self.result or {}).get("state_transition")


# ------------------------------------------------------------------------------------------------ GUI driving
def select_panel(app, key):
    app.panel_category.set(app._PANEL_LABELS[key])
    app._show_panel_category()


def fresh_wafer(app, grid, time_hours):
    """NEW WAFER, then the oxidation panel with a valid recipe; asserts the state really is a fresh one."""
    app.reset()
    app.grid_var.set(grid)
    select_panel(app, "oxidation")
    app.oxidation_method.set("Thermal oxidation")
    app.ox_temp_var.set(1000.0)
    app.ox_time_var.set(time_hours)
    assert app.last_final_mesh is None and app.last_domain_state is None and not app.completed_steps, "reset left a wafer behind"
    assert not app.wafer.processed and app.process_stage == "wafer", (app.wafer.processed, app.process_stage)


def act(app, trap, observer, xs, label, action) -> Outcome:
    """One real GUI click. The messagebox trap is checked IMMEDIATELY afterwards."""
    log_before = app.log.get("1.0", "end-1c")
    runs_before = len(observer.runs)
    stage_before, stages_before, calls_before = app.process_stage, frozenset(app._stages_done), len(trap.calls)
    action()
    trap.assert_none(label)
    runs = observer.runs[runs_before:]
    mesh = app.last_final_mesh
    return Outcome(
        label=label, log=app.log.get("1.0", "end-1c")[len(log_before):], runs=runs,
        result=(runs[-1]["result"] if runs else None), mesh=mesh, domain_state=app.last_domain_state,
        geom=(measure(mesh, xs) if mesh and Path(mesh).exists() else None),
        processed=bool(app.wafer.processed), etched=bool(app.wafer.etched),
        stage_before=stage_before, stage_after=app.process_stage,
        stages_before=stages_before, stages_after=frozenset(app._stages_done),
        film_label_after=app.stage_labels[FILM_OXIDE_MARKER].cget("text"),
        completed_steps=len(app.completed_steps), physics=app.last_physics_status,
        modal_calls=len(trap.calls) - calls_before, wafer_width=float(app.wafer.width_um), wafer_depth=float(app.wafer.silicon_depth_um))


# ------------------------------------------------------------------------------------------------ contract checks
def _lower(text):
    return text.lower()


def check_no_success_wording(o, where):
    for phrase in SUCCESS_PHRASES:
        if phrase in _lower(o.log):
            raise AssertionError(f"{where}: success wording {phrase!r} in the log of a request that did not oxidize:\n{o.log}")


def check_no_film_marker(o, where):
    if FILM_OXIDE_MARKER in o.stages_after or o.stages_after != o.stages_before or o.film_label_after.startswith("● "):
        raise AssertionError(f"{where}: the Film / oxide marker or another SESSION STATE marker changed: "
                             f"{sorted(o.stages_before)} -> {sorted(o.stages_after)}, on-screen label {o.film_label_after!r}")


def check_not_promoted(o, where):
    if o.processed or o.stage_after != o.stage_before or o.stage_after in ("oxidized", "flow_done"):
        raise AssertionError(f"{where}: promoted to a physical process state: processed={o.processed}, "
                             f"process_stage {o.stage_before!r} -> {o.stage_after!r}")


def _worker_ok(o, where):
    if len(o.runs) != 1:
        raise AssertionError(f"{where}: expected exactly one real worker subprocess, got {len(o.runs)}")
    if o.runs[0]["result_existed_before"]:
        raise AssertionError(f"{where}: the result file existed before the worker ran")
    if o.result is None:
        raise AssertionError(f"{where}: the worker wrote no result file")


def check_materialization(o, where="B"):
    """A FRESH 0 h thermal request: the recipe's own virgin Si wafer, nothing else. Not an identity."""
    _worker_ok(o, where)
    t = o.transition or {}
    assert o.result.get("success") is True, f"{where}: worker did not succeed: {o.result}"
    if not (t.get("kind") == "materialization" and t.get("inherited") is False and t.get("category") == "oxidation"
            and t.get("reason") == "zero_duration_oxidation"):
        raise AssertionError(f"{where}: not a fresh materialization transition: {t}")
    half = o.wafer_width / 2.0
    assert t["initial_geometry"]["material"] == "Si" and t["initial_geometry"]["bounds_um"] == [-half, half, -o.wafer_depth, 0.0], t
    g = o.geom
    assert g is not None and g.materials == ["Si"], f"{where}: unexpected materials {None if g is None else g.materials}"
    assert g.finite and np.all(np.abs(g.ymax["Si"]) <= EXPORT_TOL) and np.all(np.abs(g.ymin["Si"] + o.wafer_depth) <= EXPORT_TOL), (
        f"{where}: the virgin Si is not the requested wafer (top 0, floor -{o.wafer_depth}): {g.ymax['Si']} / {g.ymin['Si']}")
    check_not_promoted(o, where)
    check_no_film_marker(o, where)
    check_no_success_wording(o, where)
    low = _lower(o.log)
    for phrase in ("no oxidation was performed", "bare si wafer was materialized", "no sio2, no mask and no pad oxide were created",
                   "zero-duration oxidation: no oxidation performed", "no oxidation performed (0 h)", "materialized virgin si"):
        assert phrase in low, f"{where}: expected wording {phrase!r} missing from:\n{o.log}"
    assert "preserved" not in low, f"{where}: a fresh materialization must not claim anything was preserved:\n{o.log}"
    assert "growth" not in low and "oxide was grown" not in low, o.log


def check_identity_transition(o, where="C"):
    t = o.transition or {}
    if not (t.get("kind") == "identity" and t.get("inherited") is True and t.get("category") == "oxidation"
            and t.get("reason") == "zero_duration_oxidation"):
        raise AssertionError(f"{where}: not an inherited identity: {t}")


def assert_same_geometry(a: Geom, b: Geom, where):
    """Exact equality of the exported geometry (an identity returns the domain it was given): materials, triangle counts,
    areas and every sampled column extent."""
    same = (a.materials == b.materials and a.triangles == b.triangles and a.area == b.area and a.bbox == b.bbox
            and all(np.array_equal(a.ymin[m], b.ymin[m], equal_nan=True) and np.array_equal(a.ymax[m], b.ymax[m], equal_nan=True)
                    for m in a.materials))
    if not same:
        raise AssertionError(f"{where}: exported geometry differs: {a.materials} {a.area} vs {b.materials} {b.area}")


def check_identity(c, b, where="C"):
    _worker_ok(c, where)
    assert c.result.get("success") is True, f"{where}: worker did not succeed: {c.result}"
    check_identity_transition(c, where)
    assert c.geom.materials == ["Si"], f"{where}: unexpected materials {c.geom.materials}"
    assert_same_geometry(b.geom, c.geom, where)
    if not same_native(native_fingerprint(b.domain_state), native_fingerprint(c.domain_state)):
        raise AssertionError(f"{where}: the loaded native domains differ between the materialized wafer and the identity result")
    check_not_promoted(c, where)
    check_no_film_marker(c, where)
    check_no_success_wording(c, where)
    low = _lower(c.log)
    for phrase in ("no oxidation was performed", "existing wafer geometry and doping are preserved", "no oxidation performed (0 h)",
                   "preserved as an identity", "represents the preserved geometry"):
        assert phrase in low, f"{where}: expected wording {phrase!r} missing from:\n{c.log}"
    for phrase in ("materialized", "continuity not proven", "growth", "oxide was grown"):
        assert phrase not in low, f"{where}: unexpected wording {phrase!r}:\n{c.log}"


def check_real_step(o, stage, where, film_marker_lit):
    """A real supported step: one worker, success, no state_transition, promoted to the stage. The Film / oxide marker means a
    film step ran, so a real DEPOSITION lights it (`film_marker_lit=True`) and a real ETCH does not."""
    _worker_ok(o, where)
    assert o.result.get("success") is True and o.transition is None, f"{where}: not a plain successful step: {o.result}"
    if not (o.processed and o.stage_after == stage):
        raise AssertionError(f"{where}: wafer.processed is {o.processed} / process_stage {o.stage_after!r}; a real step must reach {stage!r}")
    assert (FILM_OXIDE_MARKER in o.stages_after) == film_marker_lit == o.film_label_after.startswith("● "), (
        f"{where}: Film / oxide marker lit={FILM_OXIDE_MARKER in o.stages_after} (on-screen label {o.film_label_after!r}), expected {film_marker_lit}")
    assert o.geom is not None and o.geom.finite, f"{where}: no finite exported mesh"


def check_bosch_lowered(before: Geom, after: Geom, where="D"):
    """Blanket, unmasked etch of virgin Si: only Si remains, and at EVERY sampled column the Si top is lower than before by more
    than the exporter's representation offset; the floor is unmoved and the mesh stays inside the domain. No exact depth."""
    if after.materials != ["Si"]:
        raise AssertionError(f"{where}: unexpected materials after the etch: {after.materials}")
    lowered = before.ymax["Si"] - after.ymax["Si"]
    if not np.all(lowered > EXPORT_TOL):
        raise AssertionError(f"{where}: the etch did not lower the Si top by at least {EXPORT_TOL:.4g} um (0.1 x grid) at every "
                             f"sampled column: {np.round(lowered, 5)}")
    assert np.all(np.abs(after.ymin["Si"] - before.ymin["Si"]) <= EXPORT_TOL), f"{where}: the Si floor moved"
    b, a = before.bbox, after.bbox
    assert a[0] >= b[0] - EXPORT_TOL and a[1] <= b[1] + EXPORT_TOL and a[2] >= b[2] - EXPORT_TOL and a[3] <= b[3] + EXPORT_TOL, (
        f"{where}: the etched mesh leaves the domain: {a} vs {b}")
    assert after.area["Si"] < before.area["Si"], f"{where}: Si area did not decrease"


def check_deposition_film(before: Geom, after: Geom, where="E"):
    """Default isotropic SiO2 deposition on the etched Si: a real film at every sampled column, thicker than the exporter's
    representation offset, lying on the Si, with the earlier Si neither lost nor resurrected, and no Mask."""
    if after.materials != ["Si", "SiO2"]:
        raise AssertionError(f"{where}: no SiO2 film was added: materials {after.materials}")
    thickness = after.ymax["SiO2"] - after.ymin["SiO2"]
    if not np.all(thickness > EXPORT_TOL):
        raise AssertionError(f"{where}: SiO2 film missing or thinner than {EXPORT_TOL:.4g} um (0.1 x grid) at a sampled column: "
                             f"{np.round(thickness, 5)}")
    assert np.all(np.abs(after.ymin["SiO2"] - after.ymax["Si"]) <= EXPORT_TOL), f"{where}: the film does not lie on the Si"
    assert np.all(np.abs(after.ymax["Si"] - before.ymax["Si"]) <= EXPORT_TOL), f"{where}: the Si top moved during the deposition"
    assert np.all(np.abs(after.ymin["Si"] - before.ymin["Si"]) <= EXPORT_TOL), f"{where}: the Si floor moved during the deposition"
    assert abs(after.area["Si"] - before.area["Si"]) <= EXPORT_TOL * (after.bbox[1] - after.bbox[0]), f"{where}: Si area changed"


def check_unsupported(o, where="F"):
    _worker_ok(o, where)
    t = o.transition or {}
    if not (t.get("kind") == "unsupported" and t.get("category") == "oxidation" and t.get("reason") == "OXIDATION_CAPABILITY_PROOF_MISSING"):
        raise AssertionError(f"{where}: not an unsupported result: transition {t}, success {o.result.get('success')}")
    assert o.result.get("success") is True, f"{where}: an unsupported result is a completed worker run, not an error: {o.result}"
    assert o.physics and o.physics.get("resolution") == "UNSUPPORTED_BY_MODEL" and o.physics.get("reason_code") == "OXIDATION_CAPABILITY_PROOF_MISSING", o.physics
    assert o.geom is not None and o.geom.materials == ["Si"], f"{where}: the last-known mesh must be the virgin Si"
    check_not_promoted(o, where)
    check_no_film_marker(o, where)
    check_no_success_wording(o, where)
    assert o.completed_steps == 0, f"{where}: an unsupported request was recorded as a completed step"
    assert "OXIDATION RESULT NOT COMPUTED (UNSUPPORTED_BY_MODEL)" in o.log, o.log
    for fact in ("1. No ViennaPS solver call was made for this request.", "2. The mesh shown is the LAST-KNOWN geometry",
                 "3. The physical state of this wafer after the requested oxidation is UNRESOLVED",
                 "4. Doping queries and DevSim solves remain blocked"):
        assert fact in o.log, f"{where}: fail-closed fact missing: {fact!r}"
    assert "ERROR —" not in o.log and "VIENNAPS FAILED" not in o.log, f"{where}: an unsupported result must not read as an ERROR:\n{o.log}"


def check_worker_validation_error(o, where="G"):
    _worker_ok(o, where)
    if o.result.get("success") is not False:
        raise AssertionError(f"{where}: the worker reported success {o.result.get('success')!r}, expected a failure")
    error = str(o.result.get("error", ""))
    assert "ValueError" in error and VALIDATION_MESSAGE in error, f"{where}: unexpected worker error: {error!r}"
    assert o.transition is None and "final_mesh" not in o.result, f"{where}: a failed worker must not return a state or mesh: {o.result}"
    assert o.mesh is None and o.domain_state is None and o.geom is None, f"{where}: a failure was adopted as a result"
    check_not_promoted(o, where)
    check_no_film_marker(o, where)
    assert o.completed_steps == 0, f"{where}: a failed step was recorded as completed"
    if "ERROR —" not in o.log or "VIENNAPS FAILED" not in o.log:
        raise AssertionError(f"{where}: no ERROR entry / failure notice in the log delta:\n{o.log}")
    assert "OXIDATION RESULT NOT COMPUTED" not in o.log and "UNSUPPORTED_BY_MODEL" not in o.log, f"{where}: read as unsupported:\n{o.log}"
    check_no_success_wording(o, where)
    assert VALIDATION_MESSAGE in VALIDATION_SOURCE.read_text(encoding="utf-8"), (
        f"{where}: the message does not originate in {VALIDATION_SOURCE.name}")


# ------------------------------------------------------------------------------------------------ false-green machinery
def expect_fail(check, label, expected):
    """A guard passes only if `check` raises AssertionError whose message matches `expected` (str, tuple of str -- all must
    appear -- or predicate). A passing check is FALSE GREEN; another reason is WRONG FAILURE REASON; other exceptions propagate."""
    ok = (callable(expected) or (isinstance(expected, str) and expected)
          or (isinstance(expected, tuple) and expected and all(isinstance(p, str) and p for p in expected)))
    if not ok:
        raise TypeError(f"expect_fail({label!r}): `expected` must be a non-empty str, tuple of str or a predicate")
    try:
        check()
    except AssertionError as exc:
        message = str(exc)
        parts = (expected,) if isinstance(expected, str) else expected
        matches = expected(message) if callable(expected) else all(p in message for p in parts)
        if not matches:
            raise AssertionError(f"WRONG FAILURE REASON for {label!r}:\n  expected: {expected!r}\n  actual:   {message[:300]}") from exc
        print(f"    [guard OK] {label}: fails for the expected reason  ({message.splitlines()[0][:100]})")
        return
    raise AssertionError(f"FALSE GREEN: the check did not fail when {label}")


def run_false_green_guards(trap, o):
    print("\n[S] false-green guards: every contract check fails, for its own reason, when its subject is broken")
    b, c, d, e, f, g = o["B"], o["C"], o["D"], o["E"], o["F"], o["G"]
    # 1. materialization judged as identity
    expect_fail(lambda: check_identity_transition(b, "B judged as identity"), "a materialization is judged as an identity",
                "B judged as identity: not an inherited identity")
    # 2. inherited identity that changes geometry (C's expectation applied to the etched wafer)
    expect_fail(lambda: assert_same_geometry(c.geom, d.geom, "identity vs etched"), "an inherited identity changes the geometry",
                "identity vs etched: exported geometry differs")
    # 3. zero-duration with success wording
    expect_fail(lambda: check_no_success_wording(dataclasses.replace(
        b, log=b.log + "\nViennaPS: ViennaPS thermal oxidation simulation complete.\n"), "B+wording"),
        "a zero-duration log says simulation complete", ("B+wording: success wording 'simulation complete'",))
    # 4. zero-duration lights the Film / oxide marker
    expect_fail(lambda: check_no_film_marker(dataclasses.replace(
        b, stages_after=b.stages_after | {FILM_OXIDE_MARKER}), "B+marker"),
        "a zero-duration step lights the Film / oxide marker", "B+marker: the Film / oxide marker")
    # 5. Bosch that changes nothing (before == after) and one that changes less than 0.1 x grid
    expect_fail(lambda: check_bosch_lowered(c.geom, c.geom, "unchanged etch"), "the etch does not change the geometry",
                "unchanged etch: the etch did not lower the Si top by at least")
    shallow = dataclasses.replace(d.geom, ymax={**d.geom.ymax, "Si": c.geom.ymax["Si"] - 0.5 * EXPORT_TOL})
    expect_fail(lambda: check_bosch_lowered(c.geom, shallow, "sub-bound etch"), "the etch lowers the Si by less than 0.1 x grid",
                "sub-bound etch: the etch did not lower the Si top by at least")
    # 6. deposition without a film
    expect_fail(lambda: check_deposition_film(d.geom, d.geom, "no film"), "the deposition adds no film",
                "no film: no SiO2 film was added")
    thin = dataclasses.replace(e.geom, ymax={**e.geom.ymax, "SiO2": e.geom.ymin["SiO2"] + 0.5 * EXPORT_TOL})
    expect_fail(lambda: check_deposition_film(d.geom, thin, "thin film"), "the film is thinner than 0.1 x grid",
                "thin film: SiO2 film missing or thinner than")
    # 7. unsupported judged as a success, a validation error judged as unsupported, unsupported judged as an error
    expect_fail(lambda: check_real_step(f, "etched", "F as a real step", film_marker_lit=False), "an unsupported request is judged as a successful step",
                lambda m: m.startswith("F as a real step:") and ("wafer.processed is False" in m or "not a plain successful step" in m))
    expect_fail(lambda: check_unsupported(g, "G as unsupported"), "a worker validation error is judged as unsupported",
                lambda m: m.startswith("G as unsupported:") and ("not an unsupported result" in m))
    expect_fail(lambda: check_worker_validation_error(f, "F as an error"), "an unsupported result is judged as a worker error",
                "F as an error: the worker reported success True")
    # 8. a worker error without an ERROR entry in the log
    expect_fail(lambda: check_worker_validation_error(dataclasses.replace(
        g, log=g.log.replace("ERROR —", "note").replace("VIENNAPS FAILED", "")), "G silent"),
        "a worker error leaves no ERROR entry in the log", "G silent: no ERROR entry / failure notice in the log delta")
    # 9. the messagebox trap: a recorded call is caught; a trap that records nothing fails calibration
    trap.calls.append(("showinfo", ("simulated", "call")))
    expect_fail(lambda: trap.assert_none("simulated modal call"), "a messagebox call is recorded during a scenario",
                "simulated modal call: 1 modal dialog call(s) reached tkinter.messagebox")
    trap.calls.clear()
    dead = types.SimpleNamespace(**{n: (lambda *a, **k: None) for n in BLOCKING})
    dead_trap = Trap(dead)
    dead_trap.install()
    for n, fn in dead_trap.originals.items():          # a trap that was never really installed
        setattr(dead, n, fn)
    expect_fail(dead_trap.calibrate, "the trap does not record direct calls", "the trap did not record every direct call")


# ------------------------------------------------------------------------------------------------ reporting
def scenario_row(name, request, o, solver, change):
    t = o.transition
    status = (f"{t.get('kind')}" + (f" (inherited={t.get('inherited')})" if "inherited" in t else "") + (f" {t.get('reason')}" if t.get("kind") == "unsupported" else "")
              if t else ("worker success=False (ValueError)" if o.result and o.result.get("success") is False else "real step, no transition"))
    mats = "-" if o.geom is None else "+".join(o.geom.materials)
    return (f"| {name} | {request} | {status} | {solver} | {mats} | {change} | processed={o.processed} / stage={o.stage_after!r} / "
            f"Film-oxide marker lit={FILM_OXIDE_MARKER in o.stages_after} | {o.modal_calls} |")


def main():
    app = gui.TCADApplication()
    assert gui.messagebox is tkinter.messagebox, "the GUI must use the tkinter.messagebox module the trap replaces"
    trap = Trap(tkinter.messagebox)
    observer = WorkerObserver(gui.subprocess)
    o = {}
    try:
        trap.install()
        observer.install()

        # --- A: withdrawn window, trap calibration ---------------------------------------------------------------
        print("[A] withdrawn window and trap calibration", flush=True)
        app.withdraw()
        app.update_idletasks()
        assert app.winfo_viewable() == 0, "withdraw() must make the root non-viewable -- log-only behaviour depends on it"
        trap.calibrate()
        trap.assert_none("A after calibration")
        print(f"    OK: winfo_viewable()=0; all {len(BLOCKING)} blocking messagebox functions trapped, each direct call recorded, log cleared")

        width = app.wafer.width_um
        xs = np.linspace(-(width / 2.0 - 0.5), width / 2.0 - 0.5, 9)      # interior sample columns, away from the side walls
        assert app.etch_model.get() == "Bosch DRIE" and app.deposition_model.get() == "Isotropic Deposition" \
            and app.dep_isotropic_material_var.get() == "SiO2", "the GUI's out-of-the-box etch/deposition defaults changed"

        # --- B: fresh zero-duration materialization --------------------------------------------------------------
        print("[B] FRESH 0 h thermal request = materialization of a virgin Si wafer (not an identity)", flush=True)
        fresh_wafer(app, GRID, 0.0)
        o["B"] = act(app, trap, observer, xs, "B", app.run_oxidation)
        check_materialization(o["B"])
        print(f"    OK: transition materialization/inherited=False, materials {o['B'].geom.materials}, Si {o['B'].geom.area['Si']:.3f} um^2, "
              f"not promoted, no marker, no success wording, modal calls {o['B'].modal_calls}")

        # --- C: inherited zero-duration identity -----------------------------------------------------------------
        print("[C] INHERITED 0 h thermal request = identity (existing wafer preserved)", flush=True)
        o["C"] = act(app, trap, observer, xs, "C", app.run_oxidation)
        check_identity(o["C"], o["B"])
        print(f"    OK: transition identity/inherited=True; exported geometry and loaded native domains equal B's; "
              f"mesh file sha B={o['B'].geom.sha256[:12]} C={o['C'].geom.sha256[:12]}; "
              f".vpsd bytes B={hashlib.sha256(Path(o['B'].domain_state).read_bytes()).hexdigest()[:12]} "
              f"C={hashlib.sha256(Path(o['C'].domain_state).read_bytes()).hexdigest()[:12]} (byte hashes may differ; content compared)")

        # --- D: the GUI's default etch (Bosch DRIE) --------------------------------------------------------------
        print("[D] default etch (Bosch DRIE) on the preserved wafer", flush=True)
        select_panel(app, "etch")
        o["D"] = act(app, trap, observer, xs, "D", app.run_etch)
        check_real_step(o["D"], "etched", "D", film_marker_lit=False)
        check_bosch_lowered(o["C"].geom, o["D"].geom)
        lowered = o["C"].geom.ymax["Si"] - o["D"].geom.ymax["Si"]
        print(f"    OK: Si only; Si top lowered by {lowered.min():.4f}..{lowered.max():.4f} um at the 9 sampled columns "
              f"(bound: > 0.1 x grid = {EXPORT_TOL:.3f}; observation only, no exact depth or hash is asserted); "
              f"Si area {o['C'].geom.area['Si']:.3f} -> {o['D'].geom.area['Si']:.3f}; processed/etched/stage='etched'")

        # --- E: the GUI's default deposition ---------------------------------------------------------------------
        print("[E] default deposition (Isotropic, SiO2) on the etched wafer", flush=True)
        select_panel(app, "deposition")
        o["E"] = act(app, trap, observer, xs, "E", app.run_deposition)
        check_real_step(o["E"], "deposited", "E", film_marker_lit=True)
        check_deposition_film(o["D"].geom, o["E"].geom)
        film = o["E"].geom.ymax["SiO2"] - o["E"].geom.ymin["SiO2"]
        print(f"    OK: materials {o['E'].geom.materials} (the SiO2 is a DEPOSITED film); film thickness {film.min():.4f}..{film.max():.4f} um at "
              f"9/9 columns (bound: > 0.1 x grid = {EXPORT_TOL:.3f}); Si top change <= {np.abs(o['E'].geom.ymax['Si'] - o['D'].geom.ymax['Si']).max():.4f} um; "
              f"no Mask; stage='deposited'")

        # --- F: positive-time oxidation ---------------------------------------------------------------------------
        print("[F] positive-time oxidation on a fresh wafer = UNSUPPORTED_BY_MODEL", flush=True)
        fresh_wafer(app, GRID, 0.4)
        o["F"] = act(app, trap, observer, xs, "F", app.run_oxidation)
        check_unsupported(o["F"])
        print(f"    OK: transition {o['F'].transition}; physics {o['F'].physics.get('resolution')}/{o['F'].physics.get('reason_code')}; "
              f"last-known mesh {o['F'].geom.materials}; not promoted, no marker, no success wording, 4 fail-closed facts, not an ERROR")

        # --- G: worker-side validation failure ---------------------------------------------------------------------
        print("[G] worker-side wafer-state/recipe validation failure (fresh 0 h thermal, grid_delta_um = -1)", flush=True)
        fresh_wafer(app, -1.0, 0.0)
        o["G"] = act(app, trap, observer, xs, "G", app.run_oxidation)
        check_worker_validation_error(o["G"])
        print(f"    OK: worker subprocess ran (return code {o['G'].runs[0]['returncode']}, result file created by it) and returned success=False, "
              f"error {str(o['G'].result['error'])[:90]}...; raised by tcad's validator in {VALIDATION_SOURCE.name} INSIDE the worker "
              f"(ViennaPS solver not involved); no mesh, no state, logged as ERROR, not unsupported; modal calls {o['G'].modal_calls}")

        run_false_green_guards(trap, o)

        trap.assert_none("end of run")
        total_modal = sum(x.modal_calls for x in o.values())
        assert total_modal == 0, total_modal
        print("\n| scenario | request | transition / status | solver meaning | materials | geometry change | processed / stage / marker | modal calls |")
        print("|---|---|---|---|---|---|---|---|")
        print(scenario_row("B fresh zero-time", "0 h, grid 0.1", o["B"], "no oxidation solver (production log + existing in-process traps)", "virgin Si created"))
        print(scenario_row("C inherited zero-time", "0 h, on B", o["C"], "no oxidation solver; identity", "none (equal to B)"))
        print(scenario_row("D default etch", "Bosch DRIE defaults, on C", o["D"], "real ViennaPS etch", f"Si top lowered {lowered.min():.3f}..{lowered.max():.3f} um"))
        print(scenario_row("E default deposition", "Isotropic SiO2 defaults, on D", o["E"], "real ViennaPS deposition", f"SiO2 film {film.min():.3f}..{film.max():.3f} um"))
        print(scenario_row("F positive-time", "0.4 h, fresh", o["F"], "no solver call (capability gate)", "none (last-known)"))
        print(scenario_row("G validation failure", "0 h, grid -1, fresh", o["G"], "no solver; tcad validator ValueError in the worker", "none, nothing adopted"))
    finally:
        observer.restore()
        trap.restore()
        app.destroy()

    print()
    print("HEADLESS NO MODAL HANG: fresh zero-duration materialization, inherited identity, real etch, real deposition,")
    print("positive-time UNSUPPORTED and a worker-side validation failure all ran through the real GUI dispatch with")
    print("no dialog wait -- every messagebox function was trapped and none fired.")


if __name__ == "__main__":
    main()
