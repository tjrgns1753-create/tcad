#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for the etch-result diagnostic (tcad/mesh/etch_diagnostics.py) and the GUI's
`_log_etch_material_summary()` that formats it. Pure geometry on hand-built triangle meshes --
no ViennaPS, no DevSim. Each numbered case answers one real failure mode of the earlier
node-`max(y)` diagnostic (docs/audits/2026-09-21-batch3-logger-shoulder/).

The expectations are exact geometry (the meshes are built from stated coordinates); nothing is
tuned to make a case pass, and the project's 0.001 um diagnostic comparison tolerance is never
widened.
"""
import ast
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from tcad.mesh import etch_diagnostics as ed

TOL = ed.DIAGNOSTIC_TOLERANCE_UM


# ----------------------------------------------------------------------------- mesh builders
def grid(a, b, step):
    n = int(round((b - a) / step))
    return [round(a + i * step, 9) for i in range(n)] + [b]


def layer(mat, xs, tops, bottom):
    """Material between `bottom` and a piecewise-linear top through (xs, tops). `bottom` is one number or one number
    per x (the latter for bodies with a sloped underside)."""
    bottoms = list(bottom) if hasattr(bottom, "__len__") else [bottom] * len(xs)
    out = []
    for i in range(len(xs) - 1):
        x0, x1, t0, t1 = xs[i], xs[i + 1], tops[i], tops[i + 1]
        b0, b1 = bottoms[i], bottoms[i + 1]
        out.append((mat, ((x0, b0), (x1, b1), (x1, t1))))
        out.append((mat, ((x0, b0), (x1, t1), (x0, t0))))
    return out


def flat(mat, xs, top, bottom):
    return layer(mat, xs, [top] * len(xs), bottom)


def band(mat, x0, x1, y0, y1):
    return [(mat, ((x0, y0), (x1, y0), (x1, y1))), (mat, ((x0, y0), (x1, y1), (x0, y1)))]


def mesh(parts, dtype=np.float64):
    """Triangles whose corners have EXACTLY the same nominal coordinates share one point index (as a conforming
    export does); nothing else is ever merged -- no tolerance -- so bodies that only touch at a vertex, along a
    T-junction, or across a hairline gap stay separate topologically."""
    index, pts, tri = {}, [], []
    for _, t in parts:
        ids = []
        for p in t:
            key = (float(p[0]), float(p[1]))
            if key not in index:
                index[key] = len(pts)
                pts.append(key)
            ids.append(index[key])
        tri.append(ids)
    return ed.TaggedMesh(np.array(pts, dtype=dtype), np.array(tri, dtype=np.int64), tuple(m for m, _ in parts))


def result(pre, post, window, material):
    got = {r.material: r for r in ed.analyze_window(pre, post, window)}
    assert material in got, f"{material} missing from results {sorted(got)}"
    return got[material]


FINE = grid(-3.0, 3.0, 0.25)


def si_pre(xs=None, top=0.0):
    return mesh(flat("Si", xs or FINE, top, -1.0))


def near(a, b, t=1e-9):
    return abs(a - b) <= t


# ----------------------------------------------------------------------------- analyzer cases
def case01_flat_known_vertical_displacement():
    r = result(si_pre(), mesh(flat("Si", FINE, -0.15, -1.0)), (-1.0, 1.0), "Si")
    assert r.status == ed.ETCHED and near(r.displacement_um, 0.15), r
    assert near(r.run_x_um[0], -1.0) and near(r.run_x_um[1], 1.0), r.run_x_um


def case02_shoulder_higher_than_centre_selects_centre():
    xs = [-3.0, -1.0, -0.8, 0.8, 1.0, 3.0]
    post = mesh(layer("Si", xs, [-0.1, -0.1, -0.15, -0.15, -0.1, -0.1], -1.0))
    r = result(si_pre(), post, (-1.0, 1.0), "Si")
    assert r.status == ed.ETCHED and near(r.displacement_um, 0.15), r     # a window max(y) says 0.10
    assert near(r.run_x_um[0], -0.8) and near(r.run_x_um[1], 0.8), r.run_x_um


def case03_remesh_all_vertices_outside_window_material_still_present():
    window = (0.1, 0.5)
    pre = si_pre(grid(-1.0, 1.0, 0.05))
    post = mesh(flat("Si", [-3.0, 3.0], -0.15, -1.0))          # no vertex inside the window
    r = result(pre, post, window, "Si")
    assert r.status != ed.FULLY_CLEARED_IN_WINDOW, r
    assert r.status == ed.ETCHED and near(r.displacement_um, 0.15), r


def case04_pre_post_columns_differ():
    post_xs = [round(-3.0 + 0.37 * k, 9) for k in range(17)] + [3.0]
    post_xs = sorted(set(x for x in post_xs if x <= 3.0))
    r = result(si_pre(grid(-3.0, 3.0, 0.5)), mesh(flat("Si", post_xs, -0.15, -1.0)), (-1.0, 1.0), "Si")
    assert r.status == ed.ETCHED and near(r.displacement_um, 0.15), r


def case05_feature_switch_counterexample():
    """Independent longest plateaus would pair the wide pre plateau (top 0) with the wide RIGHT post
    plateau (top -0.5) and report 0.5. The centre-connected pair is 0.2."""
    pre = si_pre()
    xs = [-3.0, -2.0, -0.7, -0.6, 0.2, 0.3, 3.0]
    post = mesh(layer("Si", xs, [-0.05, -0.05, -0.05, -0.2, -0.2, -0.5, -0.5], -1.0))
    r = result(pre, post, (-2.0, 2.0), "Si")
    assert r.status == ed.ETCHED and near(r.displacement_um, 0.2), r
    assert r.run_x_um[0] >= -0.6 - 1e-9 and r.run_x_um[1] <= 0.2 + 1e-9, r.run_x_um


def case06_two_vertical_components_on_one_scanline():
    post = mesh(band("Si", -3.0, 3.0, -1.0, -0.5) + band("Si", -3.0, 3.0, -0.2, 0.0))
    r = result(si_pre(), post, (-1.0, 1.0), "Si")
    assert r.status == ed.AMBIGUOUS and r.displacement_um is None, r


def case07_equal_height_runs_separated_in_x_are_not_merged():
    pre = si_pre()
    # left/right terraces at -0.1 (together wider than the centre well), centre well at -0.3 over x=-0.6..0.4
    xs = [-3.0, -0.7, -0.6, 0.4, 0.5, 3.0]
    tops = [-0.1, -0.1, -0.3, -0.3, -0.1, -0.1]
    r = result(pre, mesh(layer("Si", xs, tops, -1.0)), (-2.0, 2.0), "Si")
    assert r.status == ed.ETCHED and near(r.displacement_um, 0.3), r        # merged terraces would say 0.1
    assert r.run_x_um[0] >= -0.6 - 1e-9 and r.run_x_um[1] <= 0.4 + 1e-9, r.run_x_um
    # a hole (material absent) at the centre is never bridged into a displacement. Batch 3B contract change: it is
    # no longer a bare refusal -- the centre-clear span and the residual on both sides are both reported.
    holed = mesh(band("Si", -3.0, -0.3, -1.0, -0.1) + band("Si", 0.3, 3.0, -1.0, -0.1))
    r2 = result(pre, holed, (-2.0, 2.0), "Si")
    assert r2.status == ed.CENTER_CLEARED_RESIDUAL_REMAINS and r2.displacement_um is None, r2
    assert near(r2.center_clear_x_um[0], -0.3) and near(r2.center_clear_x_um[1], 0.3), r2.center_clear_x_um


def case08_multiple_windows_are_independent():
    pre = si_pre()
    xs = [-3.0, -0.05, 0.05, 3.0]
    post = mesh(layer("Si", xs, [-0.1, -0.1, -0.2, -0.2], -1.0))
    out = ed.analyze_etch_windows(pre, post, [[-2.5, -1.5], [1.5, 2.5]])
    (w0, r0), (w1, r1) = out
    assert w0 == (-2.5, -1.5) and w1 == (1.5, 2.5)
    a = {r.material: r for r in r0}["Si"]
    b = {r.material: r for r in r1}["Si"]
    assert near(a.displacement_um, 0.1) and near(b.displacement_um, 0.2), (a, b)


def case09_sloped_surface_refuses_a_number():
    pre = si_pre(grid(-3.0, 3.0, 0.05))
    post = mesh(layer("Si", [-3.0, -1.0, 1.0, 3.0], [-0.3, -0.3, 0.0, 0.0], -1.0))
    r = result(pre, post, (-1.0, 1.0), "Si")
    assert r.status == ed.AMBIGUOUS and r.displacement_um is None, r
    assert r.post_top_range_um is not None and r.post_top_range_um[0] < r.post_top_range_um[1]


def case10_ripple_flat_piece_not_exaggerated():
    pre = si_pre(grid(-3.0, 3.0, 0.05))
    xs = grid(-2.0, 2.0, 0.05)
    # ripple +-0.02 um everywhere, except one accidentally flat piece
    def profile(flat_lo, flat_hi):
        tops = []
        for k, x in enumerate(xs):
            base = -0.1 + (0.02 if k % 2 else -0.02)
            tops.append(-0.1 if flat_lo - 1e-9 <= x <= flat_hi + 1e-9 else base)
        return mesh(layer("Si", xs, tops, -1.0))
    # (a) the flat piece is NOT connected to the window centre -> no number
    off = result(pre, profile(0.5, 0.7), (-2.0, 2.0), "Si")
    assert off.status == ed.AMBIGUOUS and off.displacement_um is None, off
    # (b) the flat piece IS at the centre: a number, but its extent is 0.1 um of a 4 um window, on record
    on = result(pre, profile(-0.05, 0.05), (-2.0, 2.0), "Si")
    assert on.status == ed.ETCHED and near(on.displacement_um, 0.1, 1e-9), on
    assert on.n_intervals == 2 and near(on.run_x_um[1] - on.run_x_um[0], 0.1), on


def case11_float32_coordinates():
    pre = mesh(flat("Si", grid(-3.0, 3.0, 0.1), 0.0, -1.0), dtype=np.float32)
    post = mesh(flat("Si", grid(-3.0, 3.0, 0.1), -0.15, -1.0), dtype=np.float64)
    r = result(pre, post, (-1.0, 1.0), "Si")
    assert r.status == ed.ETCHED and near(r.displacement_um, 0.15, 1e-6), r
    assert r.n_intervals <= 20, f"float32/float64 vertex jitter created sliver intervals: {r.n_intervals}"
    both32 = result(pre, mesh(flat("Si", grid(-3.0, 3.0, 0.1), -0.15, -1.0), dtype=np.float32),
                    (-1.0, 1.0), "Si")
    assert both32.status == ed.ETCHED and near(both32.displacement_um, 0.15, 1e-6), both32


def case17_fewer_than_two_intervals_or_zero_width_refuses():
    coarse = mesh(flat("Si", [-3.0, 3.0], -0.15, -1.0))
    r = result(mesh(flat("Si", [-3.0, 3.0], 0.0, -1.0)), coarse, (-1.0, 1.0), "Si")
    assert r.status == ed.AMBIGUOUS, r                       # a single common interval
    xs = [-3.0, -1.0, -0.25, 0.25, 1.0, 3.0]
    post = mesh(layer("Si", xs, [-0.05, -0.05, -0.15, -0.15, -0.05, -0.05], -1.0))
    r2 = result(mesh(flat("Si", [-3.0, 3.0], 0.0, -1.0)), post, (-1.0, 1.0), "Si")
    assert r2.status == ed.AMBIGUOUS and "fewer than two" in r2.reason, r2


def case16_vertices_outside_window_is_not_fully_cleared():
    window = (0.1, 0.5)
    both = result(mesh(flat("Si", [-3.0, 3.0], 0.0, -1.0)), mesh(flat("Si", [-3.0, 3.0], -0.15, -1.0)),
                  window, "Si")
    assert both.status != ed.FULLY_CLEARED_IN_WINDOW, both
    # and a real removal IS reported as cleared
    gone = ed.analyze_window(mesh(flat("Si", FINE, 0.0, -1.0) + flat("SiO2", FINE, 0.2, 0.0)),
                             mesh(flat("Si", FINE, 0.0, -1.0)), (-1.0, 1.0))
    assert {r.material: r.status for r in gone}["SiO2"] == ed.FULLY_CLEARED_IN_WINDOW, gone


# ----------------------------------------------------------------------------- GUI wrapper cases
class _Material(int):
    pass


_Material.Si, _Material.SiO2, _Material.PHS, _Material.Mask = _Material(1), _Material(2), _Material(3), _Material(4)
_TAGS = {"Si": 1, "SiO2": 2, "PHS": 3, "Mask": 4}


class _FakeViennaps:
    Material = _Material


class _FakeSession:
    @staticmethod
    def require_viennaps():
        return _FakeViennaps


def _write(path, m):
    import meshio
    pts = np.column_stack([np.asarray(m.points, dtype=np.float64), np.zeros(len(m.points))])
    tags = np.array([_TAGS[x] for x in m.materials], dtype=np.int64)
    meshio.write(str(path), meshio.Mesh(pts, [("triangle", np.asarray(m.triangles))],
                                        cell_data={"Material": [tags]}))


def _gui():
    import tcad_2d_stagewise as gui
    gui.viennaps_session = _FakeSession
    return gui


def gui_log(pre, post, windows, tmp):
    gui = _gui()
    pp, qq = Path(tmp) / "pre.vtu", Path(tmp) / "post.vtu"
    _write(pp, pre)
    _write(qq, post)
    logged = []
    stub = SimpleNamespace(_log=logged.append)
    assert gui.TCADApplication._log_etch_material_summary(stub, str(pp), str(qq), windows) is None
    return "".join(logged)


def line_of(log, material):
    return next((l.strip() for l in log.splitlines() if l.strip().startswith(f"{material}:")), "")


def block_of(log, material):
    """The material's own line plus its indented detail lines (everything up to the next material / window line)."""
    out, on = [], False
    for l in log.splitlines():
        indent = len(l) - len(l.lstrip())
        if l.strip().startswith(f"{material}:") and indent == 4:
            on, out = True, [l.strip()]
        elif on and indent > 4:
            out.append(l.strip())
        elif on:
            break
    return "\n".join(out)


def case12_zero_rate_exposed_si(tmp):
    pre = mesh(flat("Si", FINE, 0.0, -1.0) + flat("SiO2", FINE, 0.2, 0.0))
    post = mesh(flat("Si", FINE, 0.0, -1.0) + band("SiO2", -3.0, -1.5, 0.0, 0.2) + band("SiO2", 1.5, 3.0, 0.0, 0.2))
    log = gui_log(pre, post, [[-1.0, 1.0]], tmp)
    assert "not yet reached" not in log, log
    assert "fully cleared" in line_of(log, "SiO2"), log
    assert "unchanged within diagnostic tolerance; surface is exposed" in line_of(log, "Si"), log


def case13_oxide_remains_si_unchanged(tmp):
    pre = mesh(flat("Si", FINE, 0.0, -1.0) + flat("SiO2", FINE, 0.2, 0.0))
    post = mesh(flat("Si", FINE, 0.0, -1.0) + flat("SiO2", FINE, 0.1, 0.0))
    log = gui_log(pre, post, [[-1.0, 1.0]], tmp)
    assert "overlying material remains" in line_of(log, "Si"), log
    assert "not demonstrated to have reached this material" in line_of(log, "Si"), log
    assert "not yet reached" not in log, log
    assert line_of(log, "SiO2") == "SiO2: etched 0.1000um", log
    assert "(vertical paired flat-interior displacement; not undercut/path length)" in block_of(log, "SiO2"), log
    assert "evidence source: exported volume mesh" in block_of(log, "SiO2"), log


def case14_negative_displacement(tmp):
    log = gui_log(si_pre(), mesh(flat("Si", FINE, 0.05, -1.0)), [[-1.0, 1.0]], tmp)
    assert "top rose or correspondence is indeterminate; etch displacement not reported" in line_of(log, "Si"), log
    assert "etched -" not in log, log


def case15_pre_absent_post_present_is_not_newly_exposed(tmp):
    pre = mesh(flat("Si", FINE, 0.0, -1.0))
    post = mesh(flat("Si", FINE, 0.0, -1.0) + flat("SiO2", FINE, 0.1, 0.0))
    log = gui_log(pre, post, [[-1.0, 1.0]], tmp)
    assert "newly exposed" not in log, log
    assert ("post-step exported-mesh residual detected; no comparable pre-step support"
            in line_of(log, "SiO2")), log                       # Batch 3B wording (was "...displacement unavailable")


def case18_no_open_window(tmp):
    gui = _gui()
    boom = []
    orig = ed.analyze_etch_windows
    ed.analyze_etch_windows = lambda *a, **k: boom.append(1) or (_ for _ in ()).throw(RuntimeError("must not run"))
    try:
        logged = []
        gui.TCADApplication._log_etch_material_summary(SimpleNamespace(_log=logged.append), "x.vtu", "y.vtu", [])
    finally:
        ed.analyze_etch_windows = orig
    log = "".join(logged)
    assert "No open window" in log and not boom and "Could not compute" not in log, log


def case19_analyzer_exception_is_diagnostic_only(tmp):
    gui = _gui()
    pp, qq = Path(tmp) / "a.vtu", Path(tmp) / "b.vtu"
    _write(pp, si_pre())
    _write(qq, si_pre())
    orig = ed.analyze_etch_windows
    ed.analyze_etch_windows = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("injected analyzer failure"))
    try:
        logged = []
        stub = SimpleNamespace(_log=logged.append)
        ret = gui.TCADApplication._log_etch_material_summary(stub, str(pp), str(qq), [[-1.0, 1.0]])
    finally:
        ed.analyze_etch_windows = orig
    log = "".join(logged)
    assert ret is None and "Could not compute the etch material summary" in log and "injected" in log, log
    assert vars(stub).keys() == {"_log"}, "the wrapper must not touch any other application state"
    logged2 = []                                          # an unreadable mesh is also swallowed
    assert gui.TCADApplication._log_etch_material_summary(
        SimpleNamespace(_log=logged2.append), str(Path(tmp) / "missing.vtu"), str(qq), [[-1.0, 1.0]]) is None
    assert "Could not compute the etch material summary" in "".join(logged2)


def case20_static_old_method_is_gone():
    """Scope: this proves only that the OLD code path is not present in the two files; it does not
    prove the new analyzer is correct (cases 1-19 do)."""
    src = (ROOT / "tcad_2d_stagewise.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_log_etch_material_summary")
    body = ast.get_source_segment(src, fn)
    called = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "max" not in called and "min" not in called, called
    assert not any(isinstance(n, ast.FunctionDef) and n.name == "top_in_window" for n in ast.walk(fn))
    for banned in ("top_in_window", "not yet reached", "newly exposed", "noise_floor_um", "node_idxs"):
        assert banned not in body, f"old logic still in _log_etch_material_summary: {banned!r}"
    mod = (ROOT / "tcad" / "mesh" / "etch_diagnostics.py").read_text(encoding="utf-8")
    for banned in ("np.median", "statistics", "node_idxs", "by_mat"):
        assert banned not in mod, banned


# ============================================================================ Batch 3B cases (21-42)
EPS3 = 4.0 * 2.0 ** -23 * 3.0            # the analyzer's geometry epsilon for meshes whose largest coordinate is 3
WIN = (-1.0, 1.0)


def _si_sio2_pre():
    return mesh(flat("Si", FINE, 0.0, -1.0) + flat("SiO2", FINE, 0.2, 0.0))


def _center_cleared_post():
    """SiO2 gone from the centre; a 0.1 um wide residual on each side, both attached to the outer oxide."""
    return mesh(flat("Si", FINE, 0.0, -1.0) + band("SiO2", -3.0, -0.9, 0.0, 0.2) + band("SiO2", 0.9, 3.0, 0.0, 0.2))


def case21_fully_cleared_in_window(tmp):
    post = mesh(flat("Si", FINE, 0.0, -1.0))
    r = result(_si_sio2_pre(), post, WIN, "SiO2")
    assert r.status == ed.FULLY_CLEARED_IN_WINDOW == r.contract_state and r.residual is None, r
    assert r.evidence_source == "exported_volume_mesh"
    log = gui_log(_si_sio2_pre(), post, [list(WIN)], tmp)
    assert line_of(log, "SiO2") == "SiO2: fully cleared in the exported-mesh window", log
    assert ("(no positive-area post-step intersection; evidence source: exported volume mesh)"
            in block_of(log, "SiO2")), log


def case22_center_cleared_residual_remains(tmp):
    r = result(_si_sio2_pre(), _center_cleared_post(), WIN, "SiO2")
    assert r.status == ed.CENTER_CLEARED_RESIDUAL_REMAINS == r.contract_state, r
    assert r.displacement_um is None and r.residual is not None and r.n_center_clear_intervals >= 2, r
    assert near(r.center_clear_x_um[0], -0.9) and near(r.center_clear_x_um[1], 0.9), r.center_clear_x_um
    log = gui_log(_si_sio2_pre(), _center_cleared_post(), [list(WIN)], tmp)
    assert line_of(log, "SiO2") == ("SiO2: cleared from the window center; residual exported-mesh material remains "
                                    "elsewhere in the window"), log
    assert "(center-clear x=[-0.90000, 0.90000]" in block_of(log, "SiO2"), log


def case23_center_clear_span_of_one_interval_is_ambiguous():
    pre = mesh(flat("Si", [-3.0, 3.0], 0.0, -1.0) + flat("SiO2", [-3.0, 3.0], 0.2, 0.0))
    post = mesh(flat("Si", [-3.0, 3.0], 0.0, -1.0) + band("SiO2", -3.0, -0.1, 0.0, 0.2) + band("SiO2", 0.1, 3.0, 0.0, 0.2))
    r = result(pre, post, WIN, "SiO2")
    assert r.status == ed.AMBIGUOUS and r.center_clear_x_um is None and "fewer than two" in r.reason, r


def case24_post_only_residual(tmp):
    pre = mesh(flat("Si", FINE, 0.0, -1.0))
    post = mesh(flat("Si", FINE, 0.0, -1.0) + band("SiO2", 0.9, 3.0, 0.0, 0.2))
    r = result(pre, post, WIN, "SiO2")
    assert r.status == ed.POST_ONLY_RESIDUAL == r.contract_state and r.displacement_um is None, r
    assert near(r.residual.total_clipped_area_um2, 0.02, 1e-12), r.residual
    log = gui_log(pre, post, [list(WIN)], tmp)
    assert line_of(log, "SiO2") == "SiO2: post-step exported-mesh residual detected; no comparable pre-step support", log
    assert "(physical creation or exposure is not inferred; evidence source: exported volume mesh)" in block_of(log, "SiO2")


def case25_residual_metadata_area_extent_edge_components():
    res = result(_si_sio2_pre(), _center_cleared_post(), WIN, "SiO2").residual
    assert near(res.total_clipped_area_um2, 0.04, 1e-12), res.total_clipped_area_um2
    assert near(res.x_extent_um[0], -1.0) and near(res.x_extent_um[1], 1.0), res.x_extent_um
    assert near(res.y_extent_um[0], 0.0) and near(res.y_extent_um[1], 0.2), res.y_extent_um
    assert res.touches_left_window_edge and res.touches_right_window_edge
    assert res.component_count == 2 == len(res.components) and res.evidence_source == "exported_volume_mesh"
    for c in res.components:
        assert c.whole_mesh_triangle_count == 2 and c.triangles_intersecting_window == 2
        assert near(c.clipped_area_um2, 0.02, 1e-12) and not c.isolated_island
        assert c.touches_left_window_edge != c.touches_right_window_edge


def case26_isolated_one_triangle_island():
    post = mesh(flat("Si", FINE, 0.0, -1.0) + [("SiO2", ((0.5, 0.0), (0.6, 0.0), (0.6, 0.05)))])
    r = result(_si_sio2_pre(), post, WIN, "SiO2")
    assert r.status == ed.CENTER_CLEARED_RESIDUAL_REMAINS and r.residual.component_count == 1, r
    c = r.residual.components[0]
    assert c.isolated_island and c.whole_mesh_triangle_count == 1 and c.triangles_intersecting_window == 1, c
    assert not c.touches_left_window_edge and not c.touches_right_window_edge, c
    assert near(c.clipped_area_um2, 0.5 * 0.1 * 0.05, 1e-12), c
    # the definition is "every triangle of the whole component lies inside or ON the window boundary", NOT "touches no
    # edge": an island with a vertex exactly on the window edge is still an island (nothing of it lies outside)
    on_edge = mesh(flat("Si", FINE, 0.0, -1.0) + [("SiO2", ((0.9, 0.0), (1.0, 0.0), (1.0, 0.05)))])
    c2 = result(_si_sio2_pre(), on_edge, WIN, "SiO2").residual.components[0]
    assert c2.isolated_island and c2.touches_right_window_edge and c2.whole_mesh_triangle_count == 1, c2


def case27_residual_connected_to_outside_bulk_by_shared_edge():
    post = mesh(flat("Si", FINE, 0.0, -1.0) + flat("SiO2", [-3.0, -2.0, -0.9], 0.2, 0.0))
    c = result(_si_sio2_pre(), post, WIN, "SiO2").residual.components[0]
    assert not c.isolated_island and c.whole_mesh_triangle_count == 4 and c.triangles_intersecting_window == 2, c
    assert c.touches_left_window_edge and not c.touches_right_window_edge, c


def _two_bodies(gap, bottom_b=-0.6, xa=0.3):
    """Two Si bodies with the SAME top (-0.15): A up to x = xa, B from xa + gap on (a different bottom)."""
    a = layer("Si", [-3.0, -0.5, xa], [-0.15] * 3, [-1.0] * 3)
    b = layer("Si", [xa + gap, 0.6, 3.0], [-0.15] * 3, [bottom_b] * 3)
    return mesh(a + b)


def case28_hairline_gap_between_two_bodies_is_ambiguous():
    pre = mesh(flat("Si", FINE, 0.0, -1.0))
    for gap in (0.5 * EPS3, 0.9 * EPS3):                  # far below the geometry epsilon: never merged into one body
        r = result(pre, _two_bodies(gap), WIN, "Si")
        assert r.status == ed.AMBIGUOUS and r.displacement_um is None and "component" in r.reason, (gap, r)


def case29_vertex_only_and_t_junction_contacts_are_separate_components():
    def n_comp(parts):
        m = mesh(parts)
        return len(set(int(c) for c in ed.triangle_components(m)))
    two_vertex = band("Si", 0.0, 1.0, 0.0, 1.0) + band("Si", 1.0, 2.0, 1.0, 2.0)        # share only the vertex (1, 1)
    assert n_comp(two_vertex) == 2
    t_junction = band("Si", 0.0, 1.0, 0.0, 1.0) + band("Si", 1.0, 2.0, 0.25, 0.75)     # B's edge lies inside A's edge
    assert n_comp(t_junction) == 2
    assert len(set(int(c) for c in ed.triangle_components(mesh(band("Si", 0.0, 1.0, 0.0, 1.0)
                                                                + band("SiO2", 1.0, 2.0, 0.0, 1.0))))) == 2   # other material


def case30_shared_edge_triangles_are_one_component():
    m = mesh(band("Si", 0.0, 1.0, 0.0, 1.0))                                               # two triangles, shared diagonal
    assert len(set(int(c) for c in ed.triangle_components(m))) == 1
    strip = mesh(layer("Si", [0.0, 1.0, 2.0, 3.0], [0.1] * 4, [0.0] * 4))
    assert len(set(int(c) for c in ed.triangle_components(strip))) == 1
    two_adjacent = mesh(band("Si", 0.0, 1.0, 0.0, 1.0) + band("Si", 1.0, 2.0, 0.0, 1.0))   # share the full vertical edge
    assert len(set(int(c) for c in ed.triangle_components(two_adjacent))) == 1


def case31_component_switch_mid_run_is_ambiguous():
    pre = mesh(flat("Si", FINE, 0.0, -1.0))
    r = result(pre, _two_bodies(0.0), WIN, "Si")                 # post: A|B touch only at a vertex, same top height
    assert r.status == ed.AMBIGUOUS and "component" in r.reason, r
    a = mesh(layer("Si", [-3.0, -0.5, 0.3], [0.0] * 3, [-1.0] * 3) + layer("Si", [0.3, 0.6, 3.0], [0.0] * 3, [-0.6] * 3))
    post = mesh(flat("Si", FINE, -0.15, -1.0))                    # pre switches component, post is one body
    r2 = result(a, post, WIN, "Si")
    assert r2.status == ed.AMBIGUOUS and "component" in r2.reason, r2


def _overlain_pair(overlayer):
    si = layer("Si", XS_R, [0.0] * 5, [-1.0] * 5)
    return mesh(si), mesh(si + overlayer)


XS_R = [-1.0, -0.5, 0.0, 0.5, 1.0]


def case32_reach_all_three_scanlines_covered():
    pre, post = _overlain_pair(layer("SiO2", XS_R, [0.2] * 5, [0.0] * 5))
    assert result(pre, post, WIN, "Si").reach == ed.REACH_OVERLAIN


def case33_reach_all_exposed():
    pre, post = _overlain_pair([])
    assert result(pre, post, WIN, "Si").reach == ed.REACH_EXPOSED


def case34_reach_covered_midpoint_but_exposed_end_is_unknown():
    """A wedge of SiO2 lying on the Si and thinning to zero at x = 0: the midpoint scanline of the first interval is
    covered, its start scanline is not. Midpoint-only inspection said `overlain`."""
    si = layer("Si", [-1.0, 0.0, 0.25, 0.5, 1.0], [0.0] * 5, [-1.0] * 5)
    wedge = [("SiO2", ((0.0, 0.0), (0.5, 0.0), (0.5, 0.1)))]
    r = result(mesh(si), mesh(si + wedge), (0.0, 0.5), "Si")
    assert r.status == ed.UNCHANGED and r.reach == ed.REACH_UNKNOWN, r


def _reach_one_interval(g0, g1):
    si = layer("Si", [0.0, 1.0], [0.0, 0.0], [-1.0, -1.0])
    post = mesh(si + layer("SiO2", [0.0, 1.0], [0.5, 0.5], [g0, g1]))
    e = ed._geometry_eps((post,), (0.0, 1.0))
    cpre, cpost = ed._Ctx(mesh(si), 0.0, 1.0, e), ed._Ctx(post, 0.0, 1.0, e)
    return ed._reach("Si", [(cpre.sections(0.0, 1.0), cpost.sections(0.0, 1.0))], 0, 0, e), e


def case35_reach_epsilon_scale_gap_mixed_is_unknown():
    _, e = _reach_one_interval(0.0, 0.0)
    assert _reach_one_interval(0.0, 1.5 * e)[0] == ed.REACH_UNKNOWN          # was `overlain` with midpoint-only inspection
    assert _reach_one_interval(0.0, 0.0)[0] == ed.REACH_OVERLAIN
    rng = np.random.default_rng(20260921)                                    # the Batch 3A sweep, same seed and law
    for _ in range(1500):
        g0, g1 = (0.0 if rng.random() < 0.2 else float(10 ** rng.uniform(-9, -1)) for _ in range(2))
        got, e = _reach_one_interval(g0, g1)
        assert got != ed.REACH_EXPOSED, (g0, g1, got)
        assert (got == ed.REACH_OVERLAIN) == (max(g0, g1) <= e), (g0, g1, e, got)


def case36_mask_post_only_text_makes_no_creation_or_motion_claim(tmp):
    pre = mesh(flat("Si", FINE, 0.0, -1.0))
    post = mesh(flat("Si", FINE, 0.0, -1.0) + band("Mask", 0.9, 3.0, 0.0, 0.2))
    log = gui_log(pre, post, [list(WIN)], tmp)
    low = block_of(log, "Mask").lower()
    for banned in ("created", "newly exposed", "mask moved"):
        assert banned not in low, (banned, log)
    assert "Mask-tagged residual" in block_of(log, "Mask") and "physical creation or exposure is not inferred" in block_of(log, "Mask"), log


def case37_every_state_prints_its_evidence_source(tmp):
    src = "evidence source: exported volume mesh"
    logs = {
        "fully": gui_log(_si_sio2_pre(), mesh(flat("Si", FINE, 0.0, -1.0)), [list(WIN)], tmp),
        "center": gui_log(_si_sio2_pre(), _center_cleared_post(), [list(WIN)], tmp),
        "post_only": gui_log(mesh(flat("Si", FINE, 0.0, -1.0)),
                             mesh(flat("Si", FINE, 0.0, -1.0) + band("SiO2", 0.9, 3.0, 0.0, 0.2)), [list(WIN)], tmp),
        "paired": gui_log(si_pre(), mesh(flat("Si", FINE, -0.15, -1.0)), [list(WIN)], tmp),
        "ambiguous": gui_log(si_pre(grid(-3.0, 3.0, 0.05)),
                             mesh(layer("Si", [-3.0, -1.0, 1.0, 3.0], [-0.3, -0.3, 0.0, 0.0], -1.0)), [list(WIN)], tmp),
    }
    mat = {"fully": "SiO2", "center": "SiO2", "post_only": "SiO2", "paired": "Si", "ambiguous": "Si"}
    for k, log in logs.items():
        assert src in block_of(log, mat[k]), (k, log)


def case38_residual_does_not_erase_the_center_clear_fact(tmp):
    r = result(_si_sio2_pre(), _center_cleared_post(), WIN, "SiO2")
    assert r.center_clear_x_um is not None and r.residual is not None and r.residual.component_count == 2
    blk = block_of(gui_log(_si_sio2_pre(), _center_cleared_post(), [list(WIN)], tmp), "SiO2")
    assert "center-clear x=" in blk and "SiO2-tagged residual: total clipped area" in blk, blk
    assert "no whole-window full-clear claim" in blk and "fully cleared in the exported-mesh window" not in blk, blk


def case39_residual_is_never_dropped_by_a_size_cutoff():
    tiny = band("SiO2", 1.0 - 2e-5, 3.0, 0.0, 1e-4)                 # 2e-5 um wide, 1e-4 um tall: area 2e-9 um^2
    big = band("SiO2", -3.0, -0.9, 0.0, 0.2)
    post = mesh(flat("Si", FINE, 0.0, -1.0) + big + tiny)
    r = result(_si_sio2_pre(), post, WIN, "SiO2")
    assert r.status == ed.CENTER_CLEARED_RESIDUAL_REMAINS and r.residual.component_count == 2, r
    areas = sorted(c.clipped_area_um2 for c in r.residual.components)
    assert areas[0] > 1e-10 and areas[0] < 1e-8 and near(areas[1], 0.02, 1e-12), areas
    only_tiny = mesh(flat("Si", FINE, 0.0, -1.0) + tiny)
    r2 = result(mesh(flat("Si", FINE, 0.0, -1.0)), only_tiny, WIN, "SiO2")
    assert r2.status == ed.POST_ONLY_RESIDUAL and r2.residual.total_clipped_area_um2 > 1e-10, r2


def case40_multiple_windows_keep_their_residual_metadata_separate():
    pre = mesh(flat("Si", FINE, 0.0, -1.0) + flat("SiO2", FINE, 0.2, 0.0))
    post = mesh(flat("Si", FINE, 0.0, -1.0) + band("SiO2", 2.4, 3.0, 0.0, 0.2))
    (w0, r0), (w1, r1) = ed.analyze_etch_windows(pre, post, [[-2.5, -1.5], [1.5, 2.5]])
    a = {r.material: r for r in r0}["SiO2"]
    b = {r.material: r for r in r1}["SiO2"]
    assert a.status == ed.FULLY_CLEARED_IN_WINDOW and a.residual is None, a
    assert b.status == ed.CENTER_CLEARED_RESIDUAL_REMAINS and b.window_um == (1.5, 2.5), b
    assert near(b.residual.total_clipped_area_um2, 0.02, 1e-12) and b.residual.touches_right_window_edge, b.residual
    assert b.residual.x_extent_um[0] >= 2.4 - 1e-9 and b.residual.x_extent_um[1] <= 2.5 + 1e-9, b.residual.x_extent_um


def case41_ripple_center_patch_reports_its_run_width_not_a_window_claim(tmp):
    pre = si_pre(grid(-3.0, 3.0, 0.05))
    xs = grid(-2.0, 2.0, 0.05)
    tops = [-0.1 if -0.05 - 1e-9 <= x <= 0.05 + 1e-9 else -0.1 + (0.02 if k % 2 else -0.02) for k, x in enumerate(xs)]
    post = mesh(layer("Si", xs, tops, -1.0))
    log = gui_log(pre, post, [[-2.0, 2.0]], tmp)
    blk = block_of(log, "Si")
    assert line_of(log, "Si") == "Si: etched 0.1000um", log
    assert "0.100 of 4.000 um of the window" in blk and "2 common intervals" in blk, blk
    assert "window-wide" not in blk and "whole window" not in blk, blk


def case42_static_no_cutoff_and_reach_inspects_three_scanlines():
    """Scope: proves only what this SOURCE contains -- no numeric literal that could be a size/area/width cutoff, and a
    `_reach` that loops over the three scanlines. Behaviour is proven by cases 21-41."""
    mod_src = (ROOT / "tcad" / "mesh" / "etch_diagnostics.py").read_text(encoding="utf-8")
    tree = ast.parse(mod_src)
    docstrings = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(getattr(n.body[0], "value", None), ast.Constant):
            docstrings.add(id(n.body[0].value))
    literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)
                and id(n) not in docstrings}
    allowed = {0, 1, 2, 3, 4, 23, 0.5, 0.001, 1e-30}          # indices/counts, 2**-23, 4 ulps, midpoint, the project's
    assert literals <= allowed, f"unexpected numeric literals (possible cutoff): {sorted(literals - allowed)}"   # 0.001 tolerance
    assert "DIAGNOSTIC_TOLERANCE_UM = 0.001" in mod_src
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_reach")
    seg = ast.get_source_segment(mod_src, fn)
    assert '("a", "m", "b")' in seg and "range(i0, i1 + 1)" in seg, "_reach must inspect start, middle and end of every interval"
    stage = (ROOT / "tcad_2d_stagewise.py").read_text(encoding="utf-8")
    body = ast.get_source_segment(stage, next(n for n in ast.walk(ast.parse(stage))
                                              if isinstance(n, ast.FunctionDef) and n.name == "_log_etch_material_summary"))
    assert not any(tok in body for tok in ("1e-", "0.001", "noise_floor")), "no size/tolerance literal in the GUI formatter"


CASES = [
    ("01 flat known vertical displacement", case01_flat_known_vertical_displacement, False),
    ("02 shoulder higher than centre -> centre selected", case02_shoulder_higher_than_centre_selects_centre, False),
    ("03 remesh, all vertices outside window, material still present", case03_remesh_all_vertices_outside_window_material_still_present, False),
    ("04 pre/post x-columns differ", case04_pre_post_columns_differ, False),
    ("05 feature-switch counterexample", case05_feature_switch_counterexample, False),
    ("06 two vertical components on one scanline", case06_two_vertical_components_on_one_scanline, False),
    ("07 equal-height runs separated in x not merged", case07_equal_height_runs_separated_in_x_are_not_merged, False),
    ("08 multiple windows independent", case08_multiple_windows_are_independent, False),
    ("09 sloped surface refuses a number", case09_sloped_surface_refuses_a_number, False),
    ("10 ripple: accidental flat piece not exaggerated", case10_ripple_flat_piece_not_exaggerated, False),
    ("11 float32 coordinates", case11_float32_coordinates, False),
    ("12 zero-rate exposed Si: no 'not yet reached'", case12_zero_rate_exposed_si, True),
    ("13 oxide remains, Si unchanged: evidence-based text", case13_oxide_remains_si_unchanged, True),
    ("14 negative displacement", case14_negative_displacement, True),
    ("15 pre absent/post present is not 'newly exposed'", case15_pre_absent_post_present_is_not_newly_exposed, True),
    ("16 vertices outside window: not 'fully cleared'", case16_vertices_outside_window_is_not_fully_cleared, False),
    ("17 <2 intervals / zero width refuses", case17_fewer_than_two_intervals_or_zero_width_refuses, False),
    ("18 open_windows=[]", case18_no_open_window, True),
    ("19 analyzer exception is diagnostic-only (GUI wrapper)", case19_analyzer_exception_is_diagnostic_only, True),
    ("20 static: old node/max method is gone", case20_static_old_method_is_gone, False),
    # ---- Batch 3B
    ("21 pre center present / post whole-window absent -> FULLY_CLEARED_IN_WINDOW", case21_fully_cleared_in_window, True),
    ("22 center absent + edge residual -> CENTER_CLEARED_RESIDUAL_REMAINS", case22_center_cleared_residual_remains, True),
    ("23 center-clear span of one interval -> AMBIGUOUS", case23_center_clear_span_of_one_interval_is_ambiguous, False),
    ("24 post-only edge residual -> POST_ONLY_RESIDUAL", case24_post_only_residual, True),
    ("25 residual metadata: area / extent / edges / components", case25_residual_metadata_area_extent_edge_components, False),
    ("26 isolated one-triangle island", case26_isolated_one_triangle_island, False),
    ("27 residual attached to outside bulk by a shared edge", case27_residual_connected_to_outside_bulk_by_shared_edge, False),
    ("28 hairline gap between same-height bodies in the centre run -> AMBIGUOUS", case28_hairline_gap_between_two_bodies_is_ambiguous, False),
    ("29 vertex-only / T-junction contact = separate components", case29_vertex_only_and_t_junction_contacts_are_separate_components, False),
    ("30 shared-edge triangles = one component", case30_shared_edge_triangles_are_one_component, False),
    ("31 component switch mid-run (post; pre) -> AMBIGUOUS", case31_component_switch_mid_run_is_ambiguous, False),
    ("32 reach: start/middle/end all covered -> OVERLAIN", case32_reach_all_three_scanlines_covered, False),
    ("33 reach: all exposed -> EXPOSED", case33_reach_all_exposed, False),
    ("34 reach: middle covered, end exposed -> UNKNOWN", case34_reach_covered_midpoint_but_exposed_end_is_unknown, False),
    ("35 reach: epsilon-scale gap mixed -> UNKNOWN (4000-case sweep law)", case35_reach_epsilon_scale_gap_mixed_is_unknown, False),
    ("36 Mask post-only text: no created / newly exposed / mask moved", case36_mask_post_only_text_makes_no_creation_or_motion_claim, True),
    ("37 every state prints 'evidence source: exported volume mesh'", case37_every_state_prints_its_evidence_source, True),
    ("38 residual does not erase the center-clear fact", case38_residual_does_not_erase_the_center_clear_fact, True),
    ("39 no size cutoff removes a residual", case39_residual_is_never_dropped_by_a_size_cutoff, False),
    ("40 several windows keep residual metadata separate", case40_multiple_windows_keep_their_residual_metadata_separate, False),
    ("41 ripple centre patch prints its run width, no window-wide claim", case41_ripple_center_patch_reports_its_run_width_not_a_window_claim, True),
    ("42 static: no cutoff literal; _reach inspects three scanlines", case42_static_no_cutoff_and_reach_inspects_three_scanlines, False),
]


def main():
    failed = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, fn, needs_tmp in CASES:
            try:
                fn(tmp) if needs_tmp else fn()
                print(f"PASS  {name}", flush=True)
            except Exception:
                failed.append(name)
                print(f"FAIL  {name}\n{traceback.format_exc()}", flush=True)
    print(f"\n{len(CASES) - len(failed)}/{len(CASES)} passed")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
