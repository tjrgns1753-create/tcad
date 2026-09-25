# Batch 7H-E5 PLAN: 0 V equilibrium electrical pilot on the 7H-E4 candidate (audit-only)
(fixed BEFORE any ViennaPS / DEVSIM execution of this batch; never edited after results)

Corresponds to "Checkpoint B" of this turn's instructions; run only because Checkpoint A ("Checkpoint A" =
`docs/audits/2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate/data/checkpointA_*.txt`) returned
`RAW_EVIDENCE_PORTABLE` (commit `668da8f9a093dae9784a7fa98355129852794963`).

Execution location: DEVSIM import and every `devsim.solve` call run on a GitHub-hosted Windows runner
(`claude/remote-runner`, profile `e5_equilibrium_pilot`). Locally: code reading and writing, static checks, read-only
analysis of existing arrays, synthetic tests.

## 0. Question, scope, hard limits
Is the 0 V equilibrium Poisson / semiconductor state on the 7H-E4 candidate mesh physically and numerically sane? This is
the FIRST electrical experiment on any 7H-E mesh. Out of scope, explicitly: I-V curves, forward or reverse bias, MOS,
any process geometry other than 7H-E1's single-Si planar wafer with one step junction at x = 0. No change to `tcad/`,
`tests/`, `tcad_2d_stagewise.py`, the GUI path, DEVSIM internals, or the gate `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`
— that gate is not called, not bypassed, not reasoned around; this batch builds its OWN device in an audit script, the
same AUDIT-ONLY-SHADOW method 7H-E1 already used and labelled (`shadow_e1.py`), never presented as a production result.
**Maximum verdict, even if every solve converges cleanly: `EQUILIBRIUM_PILOT_ONLY`.** One mesh, one bias point (0 V), no
claim about 2D mesh convergence, current accuracy, or general PN behaviour. 7H-E4's own `GEOMETRY_CANDIDATE_ONLY` verdict
is UNCHANGED by anything this batch finds; an electrical failure here does not get folded back into a geometric verdict,
and a geometric pass here is not claimed as an electrical one.

## 1. Path correspondence (file:line, checked directly — Serena MCP unavailable this session too, same as 7H-E1-E4)
* Doping equation (the real, gated production rule, reused verbatim as the PRIMARY condition — never substituted):
  `tcad/device/devsim/doping_mapping.py:864,868` — `Donors = donor_conc_cm3*step(x-x_j)`,
  `Acceptors = acceptor_conc_cm3*step(x_j-x)`; DEVSIM `step(0) = 1`, so the x = 0 node carries BOTH species at full
  strength (J0). Independently documented at `tcad/physics/wafer_state_v2.py:743-744` and, for the SAME formula in the
  audit fixture line, `docs/audits/2026-09-23-batch7h-d1-pn-convergence/scripts/common_d1.py:47-53` (`set_doping`,
  `rule="J1"` builds the staggered comparison; a `rule="J0"` variant is added here, not editing that file).
* Node-array write mechanism (public API, no gate call): `node_model` + `set_node_values`, exactly as
  `docs/audits/2026-09-24-batch7h-e1-production-step-junction-equivalence/scripts/shadow_e1.py:144-145` already does and
  labels `"AUDIT-ONLY SHADOW - not a production-supported result"`.
* Equilibrium equations (production, unmodified, called directly — not through the gated `apply_doping`):
  `tcad/device/devsim/semiconductor_equation.py:50-91` — `setup_semiconductor_potential_equation()` (Poisson-only) and
  `setup_drift_diffusion_equation()` (adds Electrons/Holes, `IntrinsicElectrons`/`IntrinsicHoles` initial values, taun =
  taup = 1e-8 s).
* Solver tolerances (production default, the PRIMARY condition): `tcad/characterization/pn_junction_iv_sweep.py:88-93` —
  Poisson `absolute_error=1.0, relative_error=1e-6, maximum_iterations=100`; drift-diffusion
  `absolute_error=1e10, relative_error=1e-6, maximum_iterations=100`. Only the first two of that function's three solve
  calls are reproduced (Poisson, then DD at 0 V); its third call (the bias ramp) is never made — 0 V only.
* Reference tolerance (D1/D2, cited for comparison, NOT run as an alternate "enhanced" attempt to reach a different
  verdict): `docs/audits/2026-09-23-batch7h-d1-pn-convergence/data/fixed_d1.json` — Poisson
  `absolute_error=1e-10, relative_error=1e-10, maximum_iterations=50`. D1's own 1D J0 Poisson-only solve at THIS
  tolerance never converged at any of 5 mesh sizes (`REPORT.md`: "J0 1D: Poisson not accepted at any h" — absolute
  update stuck at 3.5e-17 V, relative error oscillating 5.8e-9 / 6.2e-9 for the full 50 iterations) — at N = 1e17,
  domain +-0.5 um. 7H-E5 uses N = 1e18 (production's real value) and domain +-5 um; whether D1's stall recurs at
  production's own tolerance (1e-6, not 1e-10) and doping level is exactly this batch's PRIMARY, non-hypothetical
  question, not assumed either way.
* Precision variants (reused exactly as 7H-E1's already-reviewed S0/S12 pair, not a new axis): S0 = no flag set; S12 =
  `extended_model = extended_equation = True`, `extended_solver` left at its default False. Reported as two SEPARATE
  verdicts per device, never merged into one "pass".

## 2. Devices (all built by a NEW audit script; none calls `apply_doping` or any GUI/CLI entry point)
All Si, T = 300 K, `donor_conc_cm3 = acceptor_conc_cm3 = 1e18` (7H-E1's `common_e1.GUI["doping"]`, i.e. production's own
GUI default — not D1's 1e17), junction at x = 0.

**D2D — the real 7H-E4 candidate, J0 (the primary target).** Input:
`docs/audits/2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate/data/remote_run_36143535737/outputs/e4_out/candidate_e4.vtu`
sha256 `85ebcbaed085b07c1dc96e407faf3252a6dbbb9d9a428660ab979d1d1c421297` and `candidate_e4.npz` sha256
`740a643ed6c965b11ea179993eff2701d87b3c0a9a5990ace71fb2e5df482329` (both re-verified `RAW_EVIDENCE_PORTABLE` this
session). Imported exactly as 7H-E4's own `stage_e4.py` did (`import_process_result`, `contact_regions=["Si"]`,
`contact_axis="x"`, `length_scale_to_cm=1e-4`, no internal refinement — the mesh is already final). Mismatch on either
sha256: `MESH_INPUT_IDENTITY_FAIL`, stop before any solve.

**D1D_J0 — a 1D companion with the SAME domain half-width (5 um) and the SAME doping rule (J0, node exactly at x = 0),
built with `create_1d_mesh`/`add_1d_contact`/`add_1d_region` exactly as
`docs/audits/2026-09-23-batch7h-d1-pn-convergence/scripts/common_d1.py:30-39` (`build_1d`), scaled from that file's
X_HALF = 0.5 to 5.0 um. Node spacing h = 0.003125 um uniformly across the whole domain (the finest local spacing 7H-E4's
candidate actually achieves at the junction, measured in `docs/audits/2026-09-25-batch7h-e4-nonobtuse-quadtree-candidate/data/remote_run_36143535737/outputs/e4_out/e4_result.json`'s `resolution.candidate.x0_line`) — 3201 nodes, node positions
k h for k = -1600..1600 (includes x = 0), contacts at the domain edges. This is a deliberately UNIFORM reference, not a
copy of 7H-E4's graded structure; the point is a cheap, direct, same-doping-same-domain-same-h-at-the-junction check on
whether the 2D result's own convergence behaviour is visible in 1D too.

**D1D_J1 — a SEPARATE, clearly labelled comparison group.** Same domain, doping level and h; nodes at +-(2k+1) h/2 (no
node at x = 0), the exact formula in `meshes_d1.py:33-45` (`cols_right`, `grid_1d` kind `"J1"`), scaled to X_HALF = 5.0.
This is reported as its own device with its own verdict, never substituted for D1D_J0 or D2D, and never described as "the
J0 result."

Contacts on the 1D devices are named `left` / `right` (matching `common_d1.py`'s own convention) to keep them visibly a
separate companion device, not the real 2D device's own contact objects.

## 3. Solve sequence (identical structure for every device x precision variant; 6 total: {D2D, D1D_J0, D1D_J1} x {S0, S12})
1. Write `NetDoping` via the J0 or J1 rule above (Donors/Acceptors written too, for the doping-integral checks).
2. `setup_semiconductor_potential_equation` + `solve(type="dc", absolute_error=1.0, relative_error=1e-6,
   maximum_iterations=100, info=True)` — call 1 (Poisson). Record DEVSIM's own `converged`, the final device
   `relative_error` / `absolute_error` from the `info=True` result (same fields D1's `common_d1.py:59-77` `solve()`
   reads — reused pattern, not a new metric).
3. **If and only if call 1's `converged` is True**: `setup_drift_diffusion_equation` + `solve(absolute_error=1e10,
   relative_error=1e-6, maximum_iterations=100, info=True)` — call 2 (DD at 0 V). If call 1 did not converge, call 2 is
   NOT made, and the device is reported failed at the Poisson stage — never silently proceeding as if equilibrium were
   reached.
4. No retry with unchanged settings. S0 and S12 are the only two registered attempts per device; each is its own
   complete run (a fresh device, mesh re-imported or 1D mesh rebuilt), reported separately, never merged.
5. Every `devsim.solve` call is counted (a module-level wrapper, as 7H-E1's shadow already does); the total per device
   and the grand total across all 6 runs is reported. `devsim.solve` is never trapped in this batch (unlike 7H-E2/E3/E4,
   which forbade it) — that is the entire point of this batch.

## 4. Pre-registered observations (recorded for whichever calls actually ran; a call that did not run reports `null`, not
an invented value)
* Raw solver state: `converged`, final device `relative_error`, `absolute_error`, iteration count, per-equation
  residuals, for calls 1 and 2 separately.
* **y-direction symmetry (2D only, D2D)**: Potential at several fixed x (0, +-0.05, +-0.15 um) sampled at every distinct
  y; max - min at each x reported. 1D physics has no y-dependence, so a real asymmetry here — not attributable to mesh
  y-spacing alone, since the y-grid is uniform (7H-E4's build kept the base row spacing) — is a physical/numerical defect,
  not merely a display artifact.
* Potential, ElectricField (magnitude), and NetDoping along a straight line through the junction centre: for D2D, the
  row at the mesh's own middle y (the closest actual node row to y = -2.5 um); for the 1D devices, the whole line. Values
  at the 5 x positions -0.25, -0.10, 0(if present), +0.10, +0.25 um (matching 7H-D2's own cut convention).
* Mass-action deviation `max|n p / n_i^2 - 1|` and quasi-Fermi flatness `max|phi_n - phi_n(median)|`,
  `max|phi_p - phi_p(median)|` at 0 V — same formulas 7H-E1's `shadow_e1.py measure()` already computes, reused, not
  redefined.
* Both contact potentials (`psi_contact_V`), and the bias-parameter readback (`{contact}_bias`, must read 0.0).
* Donor / acceptor / net doping integrals: the DEVSIM NodeVolume integral (real device quantity) and, for D2D only, the
  same-mesh signed-F2 integral (7H-B rule, already computed for D2D's own mesh in 7H-E4); for the 1D devices, only the
  NodeVolume integral is meaningful (no 2D dual to compute). The geometric continuum reference (N x domain half-length,
  here N x 5 um in appropriate units) is reported alongside, never called the physical truth.
* Analytic references (Sze & Ng depletion approximation, ch. 2, formulas already used in 7H-E1's and 7H-E4's own PLANs;
  assumptions restated, not re-derived): at N_A = N_D = 1e18 cm^-3, T = 300 K — V_bi = V_T ln(N_A N_D / n_i^2), W(0 V) =
  sqrt(2 eps V_bi / q x (N_A+N_D)/(N_A N_D)), L_D = sqrt(eps V_T / (q N)). Computed once, using DEVSIM's own parameters
  (eps, V_T, n_i, read back from the device, not textbook constants), reported as `analytic_reference`, explicitly
  labelled "not the PDE solution, an idealized zero-width-junction estimate."

## 5. Failure recording (no tuning to force PASS)
A device whose Poisson call does not converge is recorded as `POISSON_NOT_CONVERGED` for that precision variant, with
the raw final residual/update and iteration count — never re-attempted with a hand-adjusted initial guess. A device whose
solve reports `converged = True` but whose y-symmetry spread exceeds 1e-6 V (the same absolute tolerance 7H-E1 used for
quasi-Fermi flatness), or whose donor/acceptor NodeVolume integral is non-finite, or whose contact potentials are equal
(no built-in potential resolved) is recorded as `CONVERGED_BUT_PHYSICALLY_INVALID` — a numerically-reported success is not
by itself accepted as a pass. Whether a 2D J0 Poisson failure (if it occurs) matches D1's own 1D J0 stall (oscillating
residual, not diverging) or is a distinct failure mode is decided from the actual recorded residual TRACE (per-iteration,
if DEVSIM's `info=True` result exposes it; otherwise from the final value only, and the comparison is marked
`INCONCLUSIVE_NO_TRACE` rather than guessed).

## 6. Stop conditions (fail-closed)
Section 2's mesh-identity check; DEVSIM import error; any non-finite value in section 4's outputs; artifact hash mismatch
after download. No PN/DD ramp beyond 0 V is ever attempted regardless of how cleanly 0 V converges.

## 7. Artifacts, strictness, cost
Strict JSON (`allow_nan=False`; non-finite -> null + explicit status; re-read with a strict parser). Expected wall time:
under 2500 s for all 6 runs (D2D's 128067-node import is the only large one, ~3 s per 7H-E4's own measurement; each
solve call capped at 100 iterations). Hard subprocess timeout 8000 s. Artifact: summary, sanitized log, per-device-per-
variant JSON, potential/field/doping state npz. No solver tolerance, device definition, or observation list in this PLAN
is changed after a result is seen. Exactly one remote run for this batch (no duplicate dispatch).
