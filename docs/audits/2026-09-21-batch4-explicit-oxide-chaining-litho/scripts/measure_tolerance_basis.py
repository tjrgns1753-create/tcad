"""Reproduces the measurements the Batch 4 tolerances are derived from (read-only; repo root from this file's location).

For two grids (0.10 and 0.05 um) it builds the explicit Si/SiO2 stack, runs a later deposition / etch / re-mask step on an
independent copy, and reports, in um and in units of the grid:
  * native-vs-requested   : native level-set position minus the REQUESTED input value       -> native_request_tolerance
  * native drift          : |native after - native initial| of the preserved Si and SiO2     -> native_eps (float64 ulps)
  * exported drift        : |exported after - exported initial| of the same interfaces       -> exported_tolerance (0.1 * grid)
Nothing here is compared to a threshold; the tolerances in the helper are derived from the mechanisms these numbers show, and
the headroom of each tolerance over the measured value is printed so a reviewer can judge it.
"""
import os
import sys
import tempfile
import warnings
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "integration"))

import numpy as np

import _explicit_chain_fixture as fx
from tcad.backends.viennaps import session
import tcad.process.deposition  # noqa: F401
import tcad.process.etching  # noqa: F401
from tcad.process.flow import FlowStep

warnings.simplefilter("ignore")
MODULE = session.require_viennaps()


def scenario(grid, xe, oxide_top, depth, steps_for):
    with tempfile.TemporaryDirectory() as tmp:
        st = fx.build_explicit_chain_state(tmp, x_extent_um=xe, y_extent_um=5.0 if xe < 9 else 8.0, silicon_depth_um=depth,
                                           oxide_top_um=oxide_top, grid_delta_um=grid)
        req = st.requested["sio2"]["top_y_um"]
        n_req = {"SiO2 top": float(np.max(np.abs(st.native_tops["SiO2"] - req))), "Si top": float(np.max(np.abs(st.native_tops["Si"])))}
        print(f"\n=== grid {grid} um (x extent {xe}, requested oxide top {req}) ===")
        print(f"  native - requested   : SiO2 {n_req['SiO2 top']:.3g}  Si {n_req['Si top']:.3g}   (= {max(n_req.values()) / grid:.3g} x grid; "
              f"tolerance native_request_tolerance = {fx.native_request_tolerance(grid):.3g})")
        worst_native, worst_exported = 0.0, 0.0
        for tag, steps in steps_for(grid, xe, depth):
            _, _, stages = fx.run_steps_from_state(st, tmp, tag, steps)
            for k, stage in enumerate(stages):
                for mat in ("Si", "SiO2"):
                    dn = float(np.nanmax(np.abs(stage.native[mat] - st.native_tops[mat])))
                    de = max(float(np.nanmax(np.abs(stage.exported[mat][key] - st.exported_columns[mat][key]))) for key in ("ymin", "ymax"))
                    worst_native, worst_exported = max(worst_native, dn), max(worst_exported, de)
                    print(f"  {tag:>10} step {k} {mat:4s}: native drift {dn:.3g}   exported drift {de:.3g} ({de / grid:.4f} x grid)")
        print(f"  WORST native drift {worst_native:.3g} (native_eps bound {fx.native_eps(st.requested['y_extent_um']):.3g}); "
              f"WORST exported drift {worst_exported:.4g} = {worst_exported / grid:.4f} x grid "
              f"(exported_tolerance {fx.exported_tolerance(grid):.4g}; headroom x{fx.exported_tolerance(grid) / max(worst_exported, 1e-30):.1f})")
        print(f"  exporter offset of the initial stack (exported Si top - native): {float(np.nanmean(st.exported_columns['Si']['ymax'] - st.native_tops['Si'])):.4g} um "
              f"= {float(np.nanmean(st.exported_columns['Si']['ymax'] - st.native_tops['Si'])) / grid:.4f} x grid")
        assert st.pristine()


def chain_steps(grid, xe, depth):
    dep = {"silicon_depth_um": depth, "deposition_time_s": 1.0, "rate": 0.15, "material": "Metal"}
    etch = {"silicon_depth_um": depth, "material_rates": {"Metal": -1.0, "SiO2": 0.0, "Si": 0.0}, "default_rate": 0.0, "etch_time_s": 0.6}
    return [("dep+etch", [FlowStep("deposition", "isotropic", dep), FlowStep("etching", "isotropic", etch)])]


def litho_steps(grid, xe, depth):
    half = xe / 2.0
    base = {"pr_thickness_um": 1.0, "silicon_depth_um": depth, "grid_delta_um": grid, "x_extent_um": xe}
    out = []
    for tag, spans in (("blanket", [[-half, half]]), ("developed", [[-half, -1.5], [1.5, half]])):
        out.append((tag, [FlowStep("deposition", "isotropic", {**base, "remask_spans_um": spans, "rate": 0.05, "deposition_time_s": 0.5,
                                                            "mask_material": "Mask", "deposit_exclude_material": "Mask", "material": "Si3N4"})]))
    return out


scenario(0.1, 8.0, 0.4, 4.0, chain_steps)
scenario(0.05, 10.0, 0.2, 5.0, litho_steps)
scenario(0.1, 10.0, 0.4, 5.0, litho_steps)
