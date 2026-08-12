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

## Supported Process models (18)

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
| Oxidation | `thermal` | `Oxidation` (fin-style and LOCOS-style, via `mask_material`) |

```python
from tcad.process import registry
import tcad.process.etching, tcad.process.deposition, tcad.process.oxidation

registry.list_categories()        # ["deposition", "etching", "oxidation"]
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
    "kind": "uniform | step_junction | gaussian_implant",
    // uniform:
    "doping_by_region_cm3": {"Si": -1e17},
    // step_junction:
    "region": "Si", "junction_axis": "x", "junction_position_um": 0.0,
    "donor_conc_cm3": 1e18, "acceptor_conc_cm3": 1e18,
    // gaussian_implant:
    "region": "Si", "junction_axis": "x",
    "peak_position_um": 0.0, "straggle_um": 0.1, "peak_conc_cm3": 1e18
  },
  "device": {
    "mesh_name": "cli_mesh", "device_name": "cli_device",
    "contact_regions": ["Si"], "contact_axis": "x",
    "contact_sides": {"Si": "min"},           // optional
    "interface_region_pairs": [["Si", "SiO2"]], // optional
    "length_scale_to_cm": 1.0                  // 1e-4 for real semiconductor physics
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
├── process/         ProcessStep + registry; etching/ deposition/ oxidation/
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
└── ohmic_iv_config.json  runnable CLI example
tcad_2d_stagewise.py  legacy tkinter GUI; etch panel now dispatches
                       Bosch DRIE, Directional RIE, Isotropic etch, and
                       SF6/O2 through the same registry as the CLI
```
