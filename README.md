# tcad

Open-source TCAD pipeline:

```
Process (ViennaPS: Etching / Deposition / Oxidation)
  -> Mesh/Structure (ProcessResult)
    -> Doping (tcad.physics)
      -> DevSim device (regions / contacts / interfaces)
        -> Characterization (I-V, PN-junction I-V, MOS C-V)
```

Every physics result in this repo — process geometry, doping,
equilibrium potentials, currents, capacitances — comes from an actual
ViennaPS/DevSim solve, not a synthetic placeholder. See
`tests/integration/` for the real-backend verification each phase was
built against.

## Installation

```bash
python3 -m pip install -e .            # core package only (meshio, matplotlib)
python3 -m pip install -e ".[full]"    # + ViennaPS and DevSim (real backends)
```

`ViennaPS` and `devsim` are optional extras, not hard requirements:
`import tcad` and every module under it import cleanly with neither
installed. Each backend exposes an `is_available()` check instead of
failing at import time:

```python
from tcad.backends.viennaps import session as viennaps_session
from tcad.device.devsim import backend as devsim_backend

viennaps_session.is_available()  # True only if ViennaPS is installed
devsim_backend.is_available()    # True only if devsim is installed
```

The GUI (`tcad_2d_stagewise.py`) additionally needs `tkinter`, which
ships with the Python interpreter itself on most platforms (on
Debian/Ubuntu: `apt install python3-tk` if it's missing).

If `import tkinter` still fails after that — confirmed on at least one
environment where a non-stock Python build (installed via the
deadsnakes PPA) had no working `tkinter` package reachable at all,
while the same distro's stock `/usr/bin/python3` did — install and use
a stock-distro Python interpreter (e.g. `/usr/bin/python3` on
Debian/Ubuntu, already carrying `apt install python3-tk`) in a
separate venv instead of fighting the non-stock interpreter's package
source:

```bash
python3 -m venv .venv-gui        # the distro's own /usr/bin/python3, not a PPA build
.venv-gui/bin/pip install -e ".[full]"
.venv-gui/bin/python tcad_2d_stagewise.py
```

Both ViennaPS and devsim ship version-agnostic or broadly-tagged PyPI
wheels, so this second venv is not a downgrade — verify with
`.venv-gui/bin/python -c "import tkinter, viennaps, devsim"` after
install.

## Quick start: run the tests

```bash
python3 tests/run_regression.py
```

`tests/unit/` (mock-based, no real backend) always runs.
`tests/integration/` (real ViennaPS + real DevSim solves) runs only if
both are installed — otherwise it's skipped with a clear message, so
this always works regardless of which extras you installed.

## Minimal example: CLI pipeline from a JSON config

```bash
python3 -m tcad.cli.run_pipeline examples/ohmic_iv_config.json
```

This runs an isotropic etch, imports the result into DevSim, sweeps a
0-0.4V bias, and writes `iv.csv` / `iv.json` / `iv.png` under
`examples/tcad_run/characterization_output/`. See
`examples/ohmic_iv_config.json` for the full config, and the "CLI
config schema" section below for every field.

`examples/gaussian_implant_iv_config.json` is the same pipeline with a
`gaussian_implant` doping profile added (`python3 -m
tcad.cli.run_pipeline examples/gaussian_implant_iv_config.json`) —
confirmed end-to-end via the actual CLI entry point, not just direct
function calls.

`examples/implant_windows_iv_config.json` uses `implant_windows`
instead: a background (channel/body) doping with two laterally
-windowed implants (source/drain) superposed on top, in the same
region — the doping primitive a MOSFET-shaped profile needs that no
other `doping.kind` can express. Also confirmed end-to-end via the CLI.

## Minimal example: Python API

```python
import tcad.process.etching
from tcad.process import registry
from tcad.mesh.viennaps_adapter import build_process_result
from tcad.device.devsim.mesh_import import import_process_result
from tcad.characterization.iv_sweep import run_iv_sweep
from tcad.characterization.io import save_csv

recipe = {
    "grid_delta_um": 0.2, "x_extent_um": 4.0, "y_extent_um": 3.0,
    "mask_left_um": 1.5, "mask_right_um": 2.5, "pr_thickness_um": 0.5,
    "etch_time_s": 0.5, "rate": -0.05, "mask_material": "Mask",
    # Optional: replace the single centred mask_left/mask_right window
    # with an arbitrary list of OPAQUE spans (domain x spans
    # [-x_extent/2, +x_extent/2]). Accepted by every process model, since
    # it lives in the shared ProcessStep.prepare_domain(). Needed for any
    # pattern the default cannot express -- e.g. a MOSFET source/drain
    # implant mask is one CENTRAL opaque span (open on both sides), the
    # complement of what a single window gives:
    #   "mask_spans_um": [[-0.8, 0.8]],
}
step_result = registry.get("etching", "isotropic")().run(recipe, "/tmp/out")
process_result = build_process_result(step_result)

imported = import_process_result(
    process_result, mesh_name="m", device_name="d",
    contact_regions=["Si"], contact_axis="x",
)
result = run_iv_sweep(
    device=imported.device, region="Si", all_contacts=imported.contacts,
    sweep_contact="Si_xmin", sweep_voltages=[0.0, 0.1, 0.2],
    fixed_contacts={"Si_xmax": 0.0},
)
save_csv(result, "/tmp/out/iv.csv")
```

## Supported Process models (20)

| Category | Model (`registry` name) | ViennaPS class |
|---|---|---|
| Etching | `bosch_drie` | `SingleParticleProcess` + `MultiParticleProcess` |
| Etching | `sf6o2` | `SF6O2Etching` |
| Etching | `hbr_o2` | `HBrO2Etching` |
| Etching | `sf6_c4f8` | `SF6C4F8Etching` |
| Etching | `cf4_o2` | `CF4O2Etching` |
| Etching | `fluorocarbon` | `FluorocarbonEtching` |
| Etching | `ibe` | `IonBeamEtching` |
| Etching | `faraday_cage` | `FaradayCageEtching` |
| Etching | `wet_etching` | `WetEtching` |
| Etching | `isotropic` | `IsotropicProcess` |
| Etching | `directional` | `DirectionalProcess` |
| Deposition | `teos` | `TEOSDeposition` |
| Deposition | `teos_pecvd` | `TEOSPECVD` |
| Deposition | `selective_epitaxy` | `SelectiveEpitaxy` |
| Deposition | `single_particle_cvd` | `SingleParticleProcess` |
| Deposition | `directional` | `DirectionalProcess` |
| Deposition | `isotropic` | `IsotropicProcess` |
| Deposition | `geometric_trench` | `GeometricTrenchDeposition` (one-shot geometric stamp, not a rate×time simulation — see `tcad/process/deposition/geometric_trench.py`'s module docstring) |
| Oxidation | `thermal` | `Oxidation` (fin-style and LOCOS-style, via `mask_material`) |
| Geometry | `gate_stack` | none (plain ViennaLS box construction, no `Process()` call — see `tcad/process/geometry/gate_stack.py`'s module docstring). Builds a MOSFET-shaped 5-material stack: Si body, a gate oxide + electrode confined to a channel window, and separate source/drain pads. **Terminal geometry only** — do not chain a further process step onto it (verified to silently corrupt the export; see the module docstring). |

```python
from tcad.process import registry
import tcad.process.etching, tcad.process.deposition, tcad.process.oxidation, tcad.process.geometry

registry.list_categories()        # ["deposition", "etching", "geometry", "oxidation"]
registry.list_models("etching")   # 11 names, matching the table above
step_cls = registry.get("etching", "sf6o2")
result = step_cls().run(recipe_dict, output_dir)  # {"final_mesh": ..., "snapshots": [...]}
```

## DevSim examples

Three characterization paths, each a real DevSim solve:

```python
# Doping-free Ohmic resistor I-V (Phase 6)
from tcad.characterization.iv_sweep import run_iv_sweep

# Real n/p-doped PN junction: equilibrium + drift-diffusion I-V (Phase 7-8)
from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep

# MOS capacitor: Oxide/Si + interface, gate voltage sweep, real C-V (Phase 9)
from tcad.characterization.cv_sweep import run_mos_cv_sweep
```

See `tests/integration/test_phase6_characterization_real.py`,
`test_phase8_pn_junction_real.py`, and `test_phase9_mos_cv_real.py` for
complete, runnable end-to-end examples of each, including the physical
sanity checks (built-in potential vs. the analytic V_bi, forward
current increasing with bias, positive C-V capacitance, etc.).

## Output file structure

Every `ProcessStep.run(recipe, output_dir)` writes to `output_dir`:

```
output_dir/
├── 000_initial.vtp          # surface mesh snapshots (one per process step)
├── 001_<step_name>.vtp
├── ...
└── <model>_final_volume.vtu  # final volume mesh (DevSim import input)
```

Every `tcad.characterization.io` / `plotting` call writes:

```
characterization_output/
├── result.csv     # save_csv() / save_cv_csv()
├── result.json    # save_json() — full CharacterizationResult
└── result.png     # save_iv_plot() / save_cv_plot()
```

The CLI (`tcad.cli.run_pipeline`) writes both under `<workdir>/`:

```
<workdir>/
├── process_output/             # ProcessStep.run()'s output_dir
└── characterization_output/    # save_csv/save_json/save_*_plot's output_dir
```

## CLI config schema

```jsonc
{
  "process": {
    "category": "etching | deposition | oxidation",
    "model": "<registry name, e.g. \"isotropic\">",
    "recipe": { /* model-specific — see the model's module docstring */ }
  },
  "doping": {                          // optional
    "kind": "uniform | step_junction | gaussian_implant | implant_windows",
    // uniform:
    "doping_by_region_cm3": {"Si": -1e17},
    // step_junction:
    "region": "Si", "junction_axis": "x", "junction_position_um": 0.0,
    "donor_conc_cm3": 1e18, "acceptor_conc_cm3": 1e18,
    // gaussian_implant:
    "region": "Si", "junction_axis": "x",
    "peak_position_um": 0.0, "straggle_um": 0.1, "peak_conc_cm3": 1e18,
    // implant_windows: a background doping plus zero or more laterally
    // -windowed implants SUPERPOSED on top, along "axis" -- e.g. source
    // and drain implants over a channel/body background, all in one
    // region (this is the piece a MOSFET-shaped doping profile needs
    // that no other kind above can express: two separate lateral
    // windows in the same region).
    // To keep the windows tied to the real mask geometry rather than
    // hand-typed, derive them from the recipe's own mask_spans_um with
    // tcad.physics.doping.implant_windows_from_mask_spans() -- dopant
    // lands where the mask is NOT.
    "region": "Si", "axis": "x", "background_doping_cm3": -1e17,
    "windows": [
      {"min_um": -1.6, "max_um": -0.6, "conc_cm3": 1e20},
      {"min_um": 0.6, "max_um": 1.6, "conc_cm3": 1e20}
    ]
  },
  "device": {
    "mesh_name": "cli_mesh", "device_name": "cli_device",
    "contact_regions": ["Si"], "contact_axis": "x",
    "contact_sides": {"Si": "min"},           // optional
    "interface_region_pairs": [["Si", "SiO2"]], // optional
    "length_scale_to_cm": 1.0,                 // 1e-4 for real semiconductor physics
    "refine_near_um": 0.0,                     // optional: local mesh refinement near this
                                                // position (see tcad/device/devsim/mesh_refine.py) --
                                                // needed for real drift-diffusion PN-junction
                                                // sweeps at typical doping levels (~1e18 cm^-3),
                                                // whose Debye length is far finer than ViennaPS's
                                                // uniform process mesh; omit for doping-free/Poisson-only
                                                // characterization, which does not need it
    "refine_axis": "x",                        // optional, default "x"
    "refine_half_width_um": 0.1,               // optional, default 0.1
    "refine_levels": 4                         // optional, default 4
  },
  "characterization": {
    "type": "iv | pn_junction_iv | mos_cv",
    // iv / pn_junction_iv:
    "region": "Si", "sweep_contact": "Si_xmin",
    "sweep_voltages": [0.0, 0.1, 0.2], "fixed_contacts": {"Si_xmax": 0.0},
    // mos_cv:
    "si_region": "Si", "oxide_region": "SiO2",
    "gate_contact": "SiO2_ymax", "substrate_contact": "Si_ymin",
    "interface_name": "Si_SiO2_interface", "gate_voltages": [-1.0, 0.0, 1.0]
  },
  "outputs": {
    "csv_filename": "result.csv", "json_filename": "result.json",
    "plot_filename": "result.png"
  }
}
```

## Project layout

```
tcad/
├── core/            Wafer/BoschRecipe (legacy GUI models)
├── backends/viennaps/  ViennaPS session/domain/I-O plumbing
├── process/         ProcessStep + registry; etching/ deposition/ oxidation/ geometry/
├── mesh/            ProcessResult (Process<->Device boundary) + ViennaPS adapter
├── physics/         Doping (separate from process models)
├── device/devsim/   DevSim mesh import, doping mapping, equation setup
├── characterization/  CharacterizationResult, I-V/C-V sweeps, CSV/JSON/plot I-O
└── cli/             JSON-config pipeline runner (pure orchestration, no new physics)
tests/
├── unit/            mock-based, no real backend required
├── integration/     real ViennaPS + real DevSim, one file per phase
└── run_regression.py  runs both in one command
examples/
├── ohmic_iv_config.json             runnable CLI example
├── gaussian_implant_iv_config.json  same, with gaussian_implant doping
└── implant_windows_iv_config.json   same, with implant_windows doping
                                      (S/D-over-channel doping shape)
tcad_2d_stagewise.py  legacy tkinter GUI; etch panel now dispatches
                       Bosch DRIE, Directional RIE, Isotropic etch, and
                       SF6/O2 through the same registry as the CLI
```
