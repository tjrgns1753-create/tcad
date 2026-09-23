"""Zero oxidation time: real geometry plus canonical state transport regression.

Contract (real ViennaPS 4.6.2):
  * inherited domain + time 0 -> IDENTITY: the input domain object is returned
    untouched (`kind="identity"`, `inherited=True`); WaferState keeps the prior
    state object, its attachments and its queries;
  * NO domain + time 0 -> MATERIALIZATION: the recipe's own virgin Si wafer and
    NOTHING else (exactly ["Si"]: no SiO2, no Mask, no pad oxide, no
    grid-floored seed). `kind="materialization"`, `inherited=False`, with the
    exact bounds it built (from `x_extent_um` / `silicon_depth_um`, never from
    a mesh). It is NOT an identity: no prior domain was handed over, so no
    earlier WaferState is known to describe it. No prior state -> a MODELLED
    initial state from those bounds; a prior state -> fail-closed;
  * in both cases: `Oxidation()` is never constructed (so
    `setInitialOxideThickness()` is unreachable), `Process` is never
    constructed, and `LocosOxidation._build_locos_geometry()` is never called.
    Each is trapped independently: a regression names which boundary it crossed.
"""
import sys
import tempfile
import json
import subprocess
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import meshio
import numpy as np
import viennaps as vps
from tcad.backends.viennaps import session
from tcad.backends.viennaps.io import save_volume_mesh
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.physics.wafer_state_accumulation import advance_wafer_state
from tcad.physics.wafer_state_v2 import (
    attach_dopant, initialize_wafer_state, uniform_inventory_integral,
)
from tcad.process.oxidation.thermal import ThermalOxidation
from tcad.process.oxidation.locos import LocosOxidation
from tcad.process.flow import run_flow, FlowStep
from tcad_2d_stagewise import TCADApplication

INHERITED_IDENTITY = {"kind": "identity", "reason": "zero_duration_oxidation",
                      "category": "oxidation", "inherited": True}


def FRESH_MATERIALIZATION(grid, x_extent=2.0, depth=0.5):
    """The exact transition a fresh zero-duration step must report (literal, not
    built by the production builder)."""
    return {"kind": "materialization", "reason": "zero_duration_oxidation",
            "category": "oxidation", "inherited": False,
            "initial_geometry": {"material": "Si",
                                 "bounds_um": [-x_extent / 2.0, x_extent / 2.0, -depth, 0.0],
                                 "material_instance_id": "si#substrate",
                                 "grid_delta_um": grid}}


class _TrapOxidationModel:
    """vps.Oxidation replacement: construction raises (so the seed setter is
    unreachable), and the setter also raises on its own."""

    def __init__(self, *a, **k):
        raise AssertionError("vps.Oxidation() constructed on a zero-duration request")

    def setInitialOxideThickness(self, *a, **k):
        raise AssertionError("setInitialOxideThickness() called on a zero-duration request")


def _traps():
    stack = ExitStack()
    stack.enter_context(patch.object(vps, "Process", side_effect=AssertionError("vps.Process() called")))
    stack.enter_context(patch.object(vps, "Oxidation", _TrapOxidationModel))
    stack.enter_context(patch.object(
        LocosOxidation, "_build_locos_geometry",
        side_effect=AssertionError("LocosOxidation._build_locos_geometry() called")))
    return stack


def same_mesh(a, b):
    a, b = meshio.read(a), meshio.read(b)
    np.testing.assert_array_equal(a.points, b.points)
    assert len(a.cells) == len(b.cells)
    for x, y in zip(a.cells, b.cells):
        assert x.type == y.type
        np.testing.assert_array_equal(x.data, y.data)
    for x, y in zip(a.cell_data['Material'], b.cell_data['Material']):
        np.testing.assert_array_equal(x, y)


def mesh_materials(path):
    """Exact set of material names present as triangles in an exported mesh."""
    mesh = meshio.read(path)
    tags = set()
    for block, data in zip(mesh.cells, mesh.cell_data['Material']):
        if block.type == 'triangle':
            tags |= {int(t) for t in np.asarray(data)}
    return sorted(str(vps.Material(t)).split("'")[1] for t in tags)


def doped_prior(bounds=(-1.0, 1.0, -0.5, 0.0), grid=0.02):
    s = initialize_wafer_state(cells=[('Si', bounds, 'si#substrate')], grid_delta_um=grid)
    return attach_dopant(
        s, species='P', polarity='donor', concentration_at=lambda x, y: 1e17,
        support_instance_id='si#substrate', support_region_um=bounds, model='uniform_v1',
        inventory_integral=uniform_inventory_integral(1e17), chemical_state="ACTIVE")


def assert_fail_closed(prior, out):
    assert out is not prior
    assert out.attachments == ()
    assert len(out.unresolved_inventory) >= 1
    q = out.net_doping_at(0.0, -0.25)
    assert q.net_doping is None and (q.physics_status or {}).get('resolution') == 'UNSUPPORTED_BY_MODEL', q


def assert_initial_state(out, grid, bounds=(-1.0, 1.0, -0.5, 0.0)):
    assert len(out.cells) == 1
    cell = out.cells[0]
    assert cell.material == 'Si' and cell.lifecycle == 'ACTIVE' and cell.is_modelled
    assert tuple(cell.bounds_um) == bounds and cell.material_instance_id == 'si#substrate'
    assert out.attachments == () and out.unresolved_inventory == ()
    assert out.grid_delta_um == grid
    q = out.net_doping_at(0.0, -0.25)
    assert q.net_doping == 0.0 and q.physics_status is None, q


def main():
    for grid in (0.02, 0.05, 0.1):
        recipe = dict(time_hours=0, grid_delta_um=grid, x_extent_um=2,
                      y_extent_um=1, temperature_c=1000, oxidant='Dry',
                      silicon_depth_um=0.5, mask_material='Mask',
                      mask_left_um=0.5, mask_right_um=1.5, pr_thickness_um=0.1)
        prior = doped_prior(grid=grid)
        # ---- inherited + time 0: IDENTITY ---------------------------------
        for cls in (ThermalOxidation, LocosOxidation):
            with tempfile.TemporaryDirectory() as tmp:
                domain = session.create_domain(grid, 2, 1)
                vps.MakePlane(domain, 0, vps.Material.Si).apply()
                before = save_volume_mesh(domain, Path(tmp)/'before', floor_depth_um=0.5)
                step = cls(inherited_domain=domain)
                # Even a remask instruction must not mutate a zero-time oxidation.
                with _traps():
                    result = step.run(dict(recipe, remask_spans_um=[[-1, 0]]), tmp)
                assert step.last_domain is domain
                assert list(domain.getMaterialsInDomain()) == [vps.Material.Si]
                same_mesh(before, result['final_mesh'])
                assert result['state_transition'] == INHERITED_IDENTITY
                assert mesh_materials(result['final_mesh']) == ['Si']
                canonical = build_process_result(result)
                out = advance_wafer_state(prior, canonical, 'oxidation')
                assert out is prior and len(out.attachments) == 1
                assert out.net_doping_at(0.0, -0.25).net_doping == 1e17
                gui = SimpleNamespace(wafer_state=prior)
                TCADApplication._sync_wafer_state_geometry(
                    gui, {'_process_category': 'oxidation'}, result)
                assert gui.wafer_state is prior
                print(f'PASS {cls.__name__} inherited bare Si grid={grid}: '
                      f'0 model/seed/Process/_build_locos_geometry, mesh identity, prior state object + 1e17 kept')

        # ---- fresh + time 0: MATERIALIZATION of virgin Si only -------------
        variants = {
            'recipe with mask keys': dict(recipe),
            'recipe with explicit mask_spans_um': dict(recipe, mask_spans_um=[[0.5, 1.5]]),
            'recipe with no mask key': {k: v for k, v in recipe.items()
                                        if k not in ('mask_material', 'mask_left_um',
                                                     'mask_right_um', 'pr_thickness_um')},
        }
        for cls in (ThermalOxidation, LocosOxidation):
            pads = (None, 0.1, 0.2) if cls is LocosOxidation else (None,)
            for pad in pads:
                for label, base in variants.items():
                    r = dict(base)
                    if pad is not None:
                        r['pad_oxide_thickness_um'] = pad
                    with tempfile.TemporaryDirectory() as tmp:
                        # the reference: the same neutral virgin Si wafer, built directly
                        ref = session.make_mask_spans(grid, 2, 1, [], 0.1, substrate_depth_um=0.5 + 1.0)
                        ref_mesh = save_volume_mesh(ref, Path(tmp)/'ref', floor_depth_um=0.5)
                        step = cls()
                        with _traps():
                            result = step.run(r, tmp)
                        assert result['state_transition'] == FRESH_MATERIALIZATION(grid), result['state_transition']
                        assert result['state_transition'] != INHERITED_IDENTITY
                        assert list(step.last_domain.getMaterialsInDomain()) == [vps.Material.Si]
                        assert mesh_materials(result['final_mesh']) == ['Si'], mesh_materials(result['final_mesh'])
                        same_mesh(ref_mesh, result['final_mesh'])
                        pr = build_process_result(result)
                        # no prior state -> the exact initial state from the transition's bounds
                        assert_initial_state(advance_wafer_state(None, pr, 'oxidation'), grid)
                        # a prior state -> NEVER preserved: not even for the same bounds
                        for prior_state in (prior, doped_prior((-2.0, 2.0, -2.0, 0.0), grid)):
                            out = advance_wafer_state(prior_state, pr, 'oxidation')
                            assert_fail_closed(prior_state, out)
                        gui = SimpleNamespace(wafer_state=None)
                        TCADApplication._sync_wafer_state_geometry(
                            gui, {'_process_category': 'oxidation'}, result)
                        assert_initial_state(gui.wafer_state, grid)
                        gui = SimpleNamespace(wafer_state=prior)
                        TCADApplication._sync_wafer_state_geometry(
                            gui, {'_process_category': 'oxidation'}, result)
                        assert_fail_closed(prior, gui.wafer_state)
            print(f'PASS {cls.__name__} fresh t=0 grid={grid} (pads {pads}, 3 recipe variants): '
                  f'materials exactly [Si], virgin wafer mesh, exact materialization transition, '
                  f'no prior -> initial state, prior -> fail-closed, 0 model/seed/Process/_build_locos_geometry')

        # ---- registered flow, both entry shapes ---------------------------
        with tempfile.TemporaryDirectory() as tmp:
            with _traps():
                fresh = LocosOxidation()
                fresh.run(recipe, tmp)
                before = save_volume_mesh(fresh.last_domain, Path(tmp)/'locos_before', floor_depth_um=0.5)
                results = run_flow([FlowStep('oxidation', 'locos', recipe)],
                                   str(Path(tmp)/'flow'), initial_domain=fresh.last_domain)
                same_mesh(before, results[0].volume_mesh_path)
                assert results[0].metadata['state_transition'] == INHERITED_IDENTITY
                assert advance_wafer_state(prior, results[0], 'oxidation') is prior
                # a flow with NO initial domain: step 0 is the fresh case
                fresh_flow = run_flow([FlowStep('oxidation', 'thermal', recipe)], str(Path(tmp)/'flow_fresh'))
                assert fresh_flow[0].metadata['state_transition'] == FRESH_MATERIALIZATION(grid)
                assert mesh_materials(fresh_flow[0].volume_mesh_path) == ['Si']
                assert_initial_state(advance_wafer_state(None, fresh_flow[0], 'oxidation'), grid)
                assert_fail_closed(prior, advance_wafer_state(prior, fresh_flow[0], 'oxidation'))
        print(f'PASS registered flow (initial_domain -> identity; no initial_domain -> materialization) grid={grid}')

    # A fresh step whose recipe cannot state its bounds refuses, instead of guessing a substrate.
    for cls in (ThermalOxidation, LocosOxidation):
        for missing in ('x_extent_um', 'silicon_depth_um', 'grid_delta_um'):
            r = {k: v for k, v in recipe.items() if k != missing}
            with tempfile.TemporaryDirectory() as tmp, _traps():
                try:
                    cls().run(r, tmp)
                except ValueError as exc:
                    assert missing in str(exc), exc
                else:
                    raise AssertionError(f'{cls.__name__}: fresh t=0 without {missing} was accepted')
    print('PASS fresh t=0 without an explicit bound (x_extent_um / silicon_depth_um / grid_delta_um) raises ValueError')

    for cls in (ThermalOxidation, LocosOxidation):
        for bad in (-1, float('nan'), float('inf')):
            try:
                cls().run({'time_hours': bad}, 'unused')
            except ValueError:
                pass
            else:
                raise AssertionError('invalid duration accepted')

    # Exercise the actual GUI worker JSON / persisted-domain boundary.
    code = 'from tcad_2d_stagewise import worker_main; import sys; worker_main(sys.argv[1], sys.argv[2])'
    worker_recipe = dict(recipe)          # grid 0.1
    worker_prior = doped_prior(grid=0.1)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        domain = session.create_domain(0.02, 2, 1)
        vps.MakePlane(domain, 0, vps.Material.Si).apply()
        state_path = str(root/'input.vpsd')
        session.save_domain_state(domain, state_path)
        cases = [
            ('inherited thermal', {'_resume_state': state_path}, 'thermal', INHERITED_IDENTITY),
            ('inherited locos', {'_resume_state': state_path}, 'locos', INHERITED_IDENTITY),
            ('fresh thermal', {}, 'thermal', FRESH_MATERIALIZATION(0.1)),
            ('fresh locos', {}, 'locos', FRESH_MATERIALIZATION(0.1)),
        ]
        for name, extra, key, expected in cases:
            out_dir = root/name.replace(' ', '_')
            out_dir.mkdir()
            config = dict(extra, output_dir=str(out_dir),
                          _flow_steps=[dict(worker_recipe, _process_category='oxidation',
                                            _process_model_key=key)])
            cfg, output = root/f'{name}.config.json', root/f'{name}.result.json'
            cfg.write_text(json.dumps(config), encoding='utf-8')
            child = subprocess.run([sys.executable, '-c', code, str(cfg), str(output)],
                                   cwd=Path(__file__).resolve().parents[2],
                                   capture_output=True, text=True, timeout=120)
            assert child.returncode == 0, child.stderr
            payload = json.loads(output.read_text(encoding='utf-8'))
            assert payload['success'], payload
            assert payload['state_transition'] == expected, (name, payload['state_transition'])
            assert mesh_materials(payload['final_mesh']) == ['Si'], (name, mesh_materials(payload['final_mesh']))
            if expected == INHERITED_IDENTITY:
                gui = SimpleNamespace(wafer_state=worker_prior)
                TCADApplication._sync_wafer_state_geometry(gui, {'_process_category': 'oxidation'}, payload)
                assert gui.wafer_state is worker_prior
            else:
                gui = SimpleNamespace(wafer_state=None)
                TCADApplication._sync_wafer_state_geometry(gui, {'_process_category': 'oxidation'}, payload)
                assert_initial_state(gui.wafer_state, 0.1)
                gui = SimpleNamespace(wafer_state=worker_prior)
                TCADApplication._sync_wafer_state_geometry(gui, {'_process_category': 'oxidation'}, payload)
                assert_fail_closed(worker_prior, gui.wafer_state)
            print(f'PASS real worker subprocess ({name}) / JSON round trip / materials [Si] / GUI state '
                  f'({"prior object kept" if expected == INHERITED_IDENTITY else "initial state or fail-closed"})')

    # A generic oxidation result must still invalidate an unmodelled transition.
    canonical.metadata['state_transition'] = None
    assert advance_wafer_state(prior, canonical, 'oxidation') is not prior
    print('PASS invalid durations and ordinary oxidation still fail closed')


if __name__ == '__main__':
    main()
