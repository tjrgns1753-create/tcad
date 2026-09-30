# Batch 7H-E6J criteria: user-facing unit contract of 2D DevSim drift-diffusion currents (fixed before the remote run)

**Base.** HEAD `a5d2b1672aea7ba7b721690303f8e33ab8cc2709`, branch `claude/remote-runner`, tracked dirty 0. Only the root CLAUDE.md exists. Serena session 14064f89.

## Defect (from reading, before any change)
- Raw meaning: `BiasPoint.currents` / `CharacterizationResult` (`tcad/characterization/interface.py`): per unit out-of-plane depth, stated only in the
  prose `CURRENT_CONVENTION_NOTE` (interface.py:39-46) and copied into `metadata["current_convention"]` by every sweep (pn_junction_iv_sweep.py:119, robust_iv_sweep.py:301,
  iv_sweep.py:76, cv_sweep.py:106, mosfet_sweep.py:212/318). E6I measured I = sigma (H/L) DeltaV with H, L in cm: A per cm of depth.
- The GUI receives the value in `TCADApplication.run_measurement` (tcad_2d_stagewise.py:5871-5901 -> `result.points[0].currents`, lines 5950-5952) and printed it as
  "I = ... A" (lines 5963-5966 log, 5971-5974 dialog): a per-unit-depth value labelled as a total current.
- Other consumers of the same `CharacterizationResult`: `tcad/characterization/io.py` (`save_csv` header `I_<contact>_A`), `plotting.py` (`ylabel "Current (A)"`), both used by the CLI
  (`tcad/cli/run_pipeline.py:363-379`).

## Contract (minimal, no raw-number change, no depth invented)
- `interface.current_unit_metadata(dimension)`: 2 -> `{"current_unit": "A/cm", "current_normalization": "per_out_of_plane_depth", "device_dimension": 2}`; any other dimension
  (and None) -> unit None (NOT verified, never assumed A). The dimension is `devsim.get_dimension(device=...)` of the solved device, read inside the two DD sweeps
  (`run_pn_junction_iv_sweep`, `run_robust_pn_junction_iv_sweep`) and merged into `CharacterizationResult.metadata`. Values, signs, solver, doping mapping unchanged.
- `format_current(value, metadata)` prints the unchanged value plus the metadata unit ("1.600000e-04 A/cm"); no unit -> "<value> (unit not established)", never plain A.
  `current_unit_note` adds one sentence that the value is per unit out-of-plane depth and not a total device current. No depth input is added and no default depth exists.
- GUI `run_measurement` log and dialog use these. `save_csv` header and `save_iv_plot` axis use the metadata unit when present; results without unit metadata keep their previous
  header / label unchanged (their unit is not established by this batch).
- Out of scope (recorded, not changed): the DC operating point / electrode result (`tcad_2d_stagewise.py:6331-6350`, prints `currents={...}` without a unit; exported via
  `save_csv` at 6038-6042 with no unit metadata, so the legacy `_A` header stays), `iv_sweep.py` (Ohmic), `cv_sweep.py`, `mosfet_sweep.py`, `vth_extraction.py` results (no unit metadata added).

## Tests and acceptance
Local (`tests/unit/test_current_unit_contract_mock.py`, pure): dimension 2 -> A/cm + normalisation; other dimensions -> None; printed number equals the raw number and the sign is kept;
unit-unknown / empty / None metadata never prints plain A; CSV header `I_<c>_A_per_cm`, JSON metadata, plot axis "Current (A/cm)"; legacy results keep `_A` / "Current (A)";
explicit-depth CONTROL of the conversion arithmetic (test depth 1 um): 1.6e-4 A/cm x 1e-4 cm = 1.6e-8 A (never a production default).
Remote (`tests/integration/test_gui_current_unit_contract_real.py`, one input: E6I one_sided n = 8, +1 mV, uniform ACTIVE 1e16 donors, production DD path):
1. direct path: 3 solves; raw I_max / I_min equal the committed E6I values (`resistor_dd.json` of run 36756889121) to 1e-12 relative and I_max equals theory to 1e-9; result metadata carries A/cm,
   per_out_of_plane_depth, dimension 2; explicit-depth control 1.6e-8 A.
2. GUI ACTIVE: source and ground lines parse with unit `A/cm`; no legacy plain-A current line; the per-unit-depth note is shown; printed numbers equal the direct raw numbers (1e-6, printed digits),
   the sign is kept (source > 0 > ground), source pin Si_xmax at +1 mV.
3. GUI CHEMICAL and UNKNOWN: 0 `devsim.solve`, 0 doping writes, no measurement block, no numeric current line, no leaked device; `physics_status.resolution == UNSUPPORTED_BY_MODEL`; the real entries are read
   (E6I read a non-existent top-level `reason_code` for this per-node block -- the structure is `entries[].parameter` = `dopant_activation_state`, `first_blocked_node.reason`, `blocked_nodes`/`total_nodes`;
   a top-level `reason_code` exists only for region-level capability blocks, `doping_mapping.py:383-416`); checked: an entry parameter `dopant_activation_state` and `blocked_nodes == total_nodes > 0`.
4. The E6I parser is updated to the new unit contract (the number is still parsed and compared, now against `A/cm`); no assertion is removed.
Not rerun: the E6I matrix, E6G/E6H, full regression. No PN solve.

## Next PN plan
`PN_PLAN.md` in this directory (a plan only: no PN solve, no gate change).
