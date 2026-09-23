# Tier 1-2 first implementation: zero-duration identity

## Contract

On an inherited wafer, zero-hour thermal or LOCOS oxidation performs no
solver call, remasking, LOCOS reconstruction, or material creation. The
backend retains the same domain object; the process result explicitly
declares a zero-duration inherited identity. That declaration survives the
adapter, process-flow result, GUI worker JSON and WaferState update. The
canonical state, including existing dopants and unresolved states, is kept
unchanged. Negative/nonfinite durations are rejected before domain preparation.

Fresh construction has no inherited wafer: it builds the existing fixture,
skips the solver at zero duration, and does not declare inherited identity.
In particular fresh LOCOS still includes its configured pad oxide and mask.

## Verification

`test_oxidation_zero_duration_identity_real.py` uses installed ViennaPS and
checks exact mesh points, connectivity and material tags at 20/50/100 nm
grid spacing. It traps `vps.Process` so any accidental zero-time solver call
fails. It also exercises a fresh LOCOS fixture followed by zero-time
inherited LOCOS through `run_flow`, the adapter/WaferState path, and a real
GUI worker subprocess with saved `.vpsd` and JSON output. GUI state sync is
called directly without constructing Tk; this is not a canvas-render test.
Ordinary oxidation without an identity declaration still invalidates
unsupported state transitions. Invalid-duration checks also pass.

Additional executed tests:

- `test_phase4_oxidation_real.py`: PASS for positive-time thermal and LOCOS
  execution. This smoke test verifies execution, not physical accuracy; its
  positive-time seed inflation is a known unresolved issue.
- `test_measurement_canonical_state_gate_mock.py`: PASS, 30 checks.
- `test_wafer_state_v2_oxidation_unsupported_mock.py`: PASS.

The mock measurement test emitted a DevSim BLAS loading warning in this
Python environment. It uses mock writes/solves; no claim of a real DevSim
electrical solve is made by this verification.

## Remaining Tier 1-2 work

Positive-time grid-dependent native seed and fresh LOCOS pad floors have
not been changed in this first isolated fix. Removing them requires a
separate preflight contract for inherited oxide thickness and geometry.
Presence of an SiO2 material alone does not prove that every oxidizable Si
surface has a resolved oxide band. The Rev.3.1 10/20/50 nm matrix only
establishes behavior for its particular planar fixture; it is not a
universal geometry/mesh capability guarantee.

Full regression and commit are pending; existing user working-tree changes
are retained. This document records the first bounded implementation, not
completion of all oxidation physics fixes.
