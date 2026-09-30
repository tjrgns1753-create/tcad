# Batch 7H-E6J REPORT: 2D DD current unit contract (A/cm) + next PN plan

Scope of this result: the DISPLAY/metadata contract of 2D DevSim drift-diffusion terminal currents. Raw numbers, signs, solver, doping mapping, PN gates: unchanged. `PN_PLAN.md` is a plan; no PN solve ran.

## Defect and fix
Before: the GUI measurement printed "Voltage source pin: Si_xmax = +0.0010 V -> I = 1.600000e-04 A" (and the same in the info dialog), although the number is per cm of out-of-plane depth (E6I).
After (run 36759423132, real GUI log): `I = 1.600000e-04 A/cm`, `I = -1.600000e-04 A/cm`, plus "Current per unit out-of-plane depth (A/cm) -- not the total current of a device; multiply by the real device depth in cm for a total current."
Machine-readable: `CharacterizationResult.metadata` of `run_pn_junction_iv_sweep` / `run_robust_pn_junction_iv_sweep` now carries `current_unit: "A/cm"`, `current_normalization: "per_out_of_plane_depth"`, `device_dimension: 2`,
from `devsim.get_dimension(device)`. Other dimensions get unit None and are displayed "(unit not established)", never as A. No depth input, no default depth. `save_csv` header (`I_<c>_A_per_cm`) and `save_iv_plot` axis ("Current (A/cm)")
follow the metadata; results without unit metadata keep their legacy `_A` / "Current (A)" (their unit is not established here).

## Evidence
- Mock (`tests/unit/test_current_unit_contract_mock.py`, local and remote rc 0): A/cm for dimension 2, None otherwise; printed number equals raw, sign kept; unknown unit never plain A; CSV / JSON / plot; legacy unchanged;
  explicit-depth CONTROL 1.6e-4 A/cm x 1e-4 cm = 1.6e-8 A (test depth only).
- Remote GUI (`test_gui_current_unit_contract_real.py`, one_sided n = 8, +1 mV, uniform ACTIVE): 16 of 16 checks pass. Direct production DD path: 3 solves, raw I_max = +1.600000000000222e-4, I_min = -1.600000000000222e-4 A/cm,
  equal to the committed E6I values (1e-12 relative) and to theory (1e-9); GUI printed numbers equal the direct raw numbers, sign kept; unit printed `A/cm`; no legacy plain-A line.
- CHEMICAL and UNKNOWN through the same GUI call: 0 solves, 0 doping writes, no measurement block, no numeric current line, no leaked device; `physics_status`: `resolution = UNSUPPORTED_BY_MODEL`,
  `reason_code = null` (for this per-node block there is no top-level reason code; it exists only for region-level capability blocks), `entries[0].parameter = dopant_activation_state`, note "attachment 'att:doping:1:2' covering this point has
  chemical_state 'CHEMICAL'; only ACTIVE dopant is electrically usable (no activation model is available)", `blocked_nodes = total_nodes = 73`. The E6I probe read the non-existent top-level `reason_code`; the real fields are now read.
- E6I test updated: the GUI parser now expects `A/cm` (number still parsed and compared; verified on the real E6J log string with the new regex); E6I is not rerun. Existing tests with `I = <number> A` regexes still match the new text
  (`A` is followed by `/cm`), so their positive and negative ("no current reported") checks keep their meaning.

## Consumers of the same value (file:line)
Changed: GUI log + dialog (`tcad_2d_stagewise.py` run_measurement, 5958-5975), `io.save_csv` header, `plotting.save_iv_plot` ylabel.
Out of scope, unchanged: DC operating point / electrode result (`tcad_2d_stagewise.py:6331-6350` prints `currents={...}` with no unit; `_on_export_result_clicked` 6038-6042 exports it with the legacy `_A` header), `iv_sweep.py`, `cv_sweep.py`, `mosfet_sweep.py`,
`vth_extraction.py`, and every result not produced by the two PN/DD sweeps.
Not verified at runtime: the robust sweep's metadata line (same code as the pn sweep, not executed in E6J; covered by reading only).

## Files
Production: `tcad/characterization/interface.py` (+`current_unit_metadata`, `format_current`, `current_unit_note`), `pn_junction_iv_sweep.py`, `robust_iv_sweep.py`, `io.py`, `plotting.py`, `tcad_2d_stagewise.py`. Tests: `tests/unit/test_current_unit_contract_mock.py`,
`tests/integration/test_gui_current_unit_contract_real.py`, `test_uniform_resistor_dd_current_real.py` (parser + metadata capture). Remote: profile `e6j_current_unit_contract`, request `e6j-current-unit-001`.
