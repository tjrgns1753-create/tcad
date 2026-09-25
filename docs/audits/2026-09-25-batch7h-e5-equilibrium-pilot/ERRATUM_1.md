# Batch 7H-E5 ERRATUM 1 (read-only re-analysis; no new ViennaPS/DEVSIM execution)

Written after Codex's partial approval of the 7H-E5 final report. `PLAN.md`, `PLAN.sha256`, both runs' raw JSON/log/
`summary.json`, and `REPORT.md` are **not modified**. No tolerance, threshold, or PLAN text was changed to fit this
analysis; every number below is either read verbatim from the existing artifacts or recomputed independently from them
with a stated formula. Serena MCP was checked again this session and is still unavailable
(`ToolSearch` -> "Skipping connection (recent failure cached...)"); `rg` and direct file reading were used throughout,
and DEVSIM's own installed source (`…/.venv/Lib/site-packages/devsim/python_packages/simple_physics.py`) was read
directly for part D rather than relied on from memory.

## A. Raw evidence, fixed

* HEAD at the start of this analysis: `e4cf33f9059767d9d5449e937affa51186cfbe73` (branch `claude/remote-runner`,
  working tree clean, matches `origin/claude/remote-runner`).
* E5 PLAN sha256 (unchanged): `924395fb86a72658853a9b8ffd7827cdb0ddf6c1473d55609af09764ce8802fa`.
* Two runs, kept separate everywhere below, never aggregated:
  * **First (failed) run**: `36149228558`, commit `3084a3dd99f4b18f982570ce077e53cb49dd164f`, `summary.json.status = FAIL`,
    `exit_code = 1`. All 7 outputs and `run.log` re-hashed against `summary.json` independently this session: all match
    (`ebeede48…`, `9457a71d…`, `edabf2d1…`, `2e40a4f5…`, `3e62afbf…`, `94f78030…`, `cc861186…`; log hash matches).
  * **Clean (rerun) run**: `36151109973`, commit `e3141f3f5d2489bdbf782746befc7570b05a317c`, `summary.json.status = PASS`,
    `exit_code = 0`. All 7 outputs and `run.log` re-hashed independently this session: all match (`16fbfd93…`,
    `f9b399a1…`, `c519721316…`, `3682791f…`, `9e75e117…`, `814ea919…`, `d470e8a7…`; log hash matches).
* This document is `ERRATUM_1.md`, a new file distinct from `REPORT.md`; `REPORT.md` is kept as the original,
  historical record and is not edited.

## B. 2D contact-name / coordinate correction

### B1. Where `Si_xmin` / `Si_xmax` are actually assigned (code, not assumed)
`tcad/device/devsim/mesh_import.py:1051` computes `axis_min, axis_max = region_coords.min(), region_coords.max()`;
`:1067-1068` finds the edges nearest each; `:1074`
`for edges, suffix in ((lo_edges, f"{region_axis}min"), (hi_edges, f"{region_axis}max")):` pairs the
**axis-minimum** edges with suffix `"xmin"` and the **axis-maximum** edges with suffix `"xmax"`; `:1082`
`contact_name = f"{region_name}_{suffix}"`. This is unambiguous and was not changed by this analysis:
**`Si_xmin` = the x = -5 um (left, acceptor/P-type) boundary; `Si_xmax` = the x = +5 um (right, donor/N-type)
boundary.**

### B2. What `sorted(imp.contacts)` actually produces
`stage_e5.py`'s own comment claimed "xmin first" for `contacts = sorted(imp.contacts)`. Checked directly, not assumed:

```
>>> sorted(['Si_xmin', 'Si_xmax'])
['Si_xmax', 'Si_xmin']
```

Python string sort compares `'Si_xma...'` vs `'Si_xmi...'` at the 5th character, `'a' < 'i'`, so **`Si_xmax` sorts
first**. `contacts[0] = 'Si_xmax'`, `contacts[1] = 'Si_xmin'` for D2D — the exact opposite of the comment.

### B3. Where this index assumption is baked into the measurement code
* `devices_e5.py:122-123` (`measure_poisson`): `psi[x == (x.min() if c == contacts[0] else x.max())]` for `c` in
  `contacts` — assigns `x.min()` to whichever name happens to be `contacts[0]`.
* `shadow_e1.py:91` (`measure`, reused verbatim): `out["psi_contact_V"] = {contacts[0]: psi[x==x.min()]..., contacts[1]: psi[x==x.max()]...}`;
  `shadow_e1.py:65-67` (`C1`): `for c, cset in ((contacts[0], x==x.min()), (contacts[1], x==x.max())): ...`.
  Both unconditionally pair `contacts[0]` with `x.min()` and `contacts[1]` with `x.max()`, with no check of what the
  name actually is.
* `shadow_e1.py:56-58` (`C0`): `for c in contacts: dv.get_contact_current(device=dev, contact=c, ...)` — queries
  DEVSIM **by the real contact name string**, not by index. **C0 is not affected** (confirmed, matches the review's
  own instruction not to flip it).
* `shadow_e1.py:91` `bias_readback`: also queried by real name (`f"{c}_bias"`), also not affected (both values are
  0.0 regardless, since no bias was ever applied).
* `devices_e5.py` `doping_integrals()`, `cut_profile()`, `analytic_reference()`: none index into `contacts[0]/[1]`;
  unaffected.

### B4. Is the 1D pair affected the same way?
No. `devices_e5.py` `build_1d()` returns the literal list `["left", "right"]` (not `sorted()`), and by construction
(`grid_1d_um` returns ascending x; `i==0` -> tag `"left"`, last index -> tag `"right"`) `"left"` really is the
x = -5 um node and `"right"` really is x = +5 um. `contacts[0]="left"=x.min()`, `contacts[1]="right"=x.max()` — this
happens to match what `measure_poisson`/`shadow_e1.measure()` assume. **D1D_J0 and D1D_J1 (both S0 and S12) are NOT
mislabelled.** Confirmed against the physics: `left` reads negative (P-side), `right` positive (N-side), correct in
every 1D JSON.

### B5. Correction table (D2D only; S0 and S12 separately; `psi_contact_V`)

| variant | JSON key | recorded value (V) | actually computed at | correct contact name |
|---|---|---|---|---|
| S0 | `Si_xmax` | -0.4768597199126636 | `x == x.min()` | **Si_xmin** |
| S0 | `Si_xmin` | +0.4768597199126636 | `x == x.max()` | **Si_xmax** |
| S12 | `Si_xmax` | -0.4768597199126636 | `x == x.min()` | **Si_xmin** |
| S12 | `Si_xmin` | +0.4768597199126636 | `x == x.max()` | **Si_xmax** |

Same table for `poisson_measure.psi_contact_V` (identical values, same swap, both variants).

### B6. Correction table (`C1`, D2D)

| variant | JSON key | recorded C1.total | actually computed at | correct contact name |
|---|---|---|---|---|
| S0 | `Si_xmax` | 0.0 | `x==x.min()` | Si_xmin |
| S0 | `Si_xmin` | 0.0 | `x==x.max()` | Si_xmax |
| S12 | `Si_xmax` | -3.398755430672983e-30 | `x==x.min()` | **Si_xmin** |
| S12 | `Si_xmin` | +7.236624536599885e-30 | `x==x.max()` | **Si_xmax** |

**Independent cross-check that this correction is right, not merely asserted**: `C0` is queried by real contact name
(unaffected, B3). For S12: `C0['Si_xmax'].total = 7.236624536599886e-30`; the CORRECTED C1 value for the real
`Si_xmax` (from the row above, the JSON-key-`Si_xmin` row) is `7.236624536599885e-30` — equal to 15 significant
figures. `C0['Si_xmin'].total = -3.398755430672983e-30`; the corrected C1 value for real `Si_xmin` is
`-3.398755430672983e-30` — equal to the last digit. This is strong, direct evidence the swap identified in B2-B3 is
exactly what happened, not a guess.

### B7. Does the label error change the solve itself, or only post-processing?
**Only post-processing.** `setup_semiconductor_potential_equation(device, region, contacts, 300.0)`
(`stage_e5.py:57`) is called with the real `contacts` list and iterates it by actual name inside
`CreateSiliconPotentialOnlyContact` (confirmed by reading DEVSIM's own source, part D1 below) — the boundary
condition at each contact is set from ITS OWN NetDoping-derived formula, never from an index or from `x.min()/x.max()`
assumed identity. `write_doping()` (`devices_e5.py`) sets Donors/Acceptors/NetDoping directly from each node's real
`x` coordinate, not from any contact name. So the assembled equations, the Newton solve, and the resulting `Potential`/
`Electrons`/`Holes` node arrays are **not affected** by this bug — the bug is entirely in how `measure_poisson()` and
`shadow_e1.measure()` label two already-correct numbers after the solve. No raw JSON is corrected in place; use the
tables above (B5, B6) to read the original artifacts correctly.

## C. Internal-current precision (the substance of this review)

### C1. Independent reproduction of Codex's cited max-\|C2 total\| figures
Recomputed directly from the clean run's 6 JSONs (`max(abs(v["total"]) for v in equilibrium_measure["C2"].values())`),
with the cut it came from:

| run | max \|C2.total\| (this analysis) | Codex's cited value | match | cut |
|---|---|---|---|---|
| D2D S0 | 5.026625835961377e-13 | 5.0266e-13 | yes | `+0.10` |
| D2D S12 | 7.243547018049181e-30 | 7.2435e-30 | yes | `+0.10` |
| D1D_J0 S0 | 2.6553536971694577e-09 | 2.6554e-9 | yes | `-0.10` |
| D1D_J0 S12 | 8.189144980286217e-26 | 8.1891e-26 | yes | `+0.25` |
| D1D_J1 S0 | 5.316907495910494e-09 | 5.3169e-9 | yes | `+0.10` |
| D1D_J1 S12 | 4.337706648307241e-26 | 4.3377e-26 | yes | `+0.25` |

All 6 reproduce exactly. Full per-cut C0/C1/C2/C3, corrected D2D contact labels per section B, are in
`data/c0_c1_c2_c3_full.json` (this analysis's own derived file, not a modification of the original JSONs).

### C2. Units — not simply "A" in either dimension
`shadow_e1.py:39-41`: `Fn, Fp = ev("ElectronCurrent")*cpl, ev("HoleCurrent")*cpl` with `cpl = ev("EdgeCouple")`.
DEVSIM's `ElectronCurrent`/`HoleCurrent` edge models are current **densities**, A/cm^2. `EdgeCouple`'s dimension is
fixed by this project's own already-registered convention
(`docs/audits/2026-09-23-batch7h-d2-current-precision/data/fixed_d2.json:25`: `"couple_used = OvEdgeCouple (D1) else
EdgeCouple; 1D couple 1"`; `:27`: `"units": "1D A/cm^2, 2D A/cm per unit depth"`):
* **2D**: `EdgeCouple` is a real dual-edge length (cm; 7H-B identified it as the circumcentric/absolute-couple length).
  `[A/cm^2] x [cm] = A/cm` — current **per unit device depth** (no real z-thickness is assumed; this project's whole
  2D formulation is implicitly per-unit-depth).
* **1D**: DEVSIM's 1D `EdgeCouple` is the dimensionless constant 1 (unit cross-section convention).
  `[A/cm^2] x [1] = A/cm^2` — a current **density**, not reduced by any length.
So **D2D's C2 values are in A/cm; D1D_J0/D1D_J1's are in A/cm^2.** They are not the same physical quantity and are not
directly comparable in magnitude without an assumed cross-section/depth — this report does not compare 2D and 1D C2
magnitudes to each other. Within 1D, D1D_J0 vs D1D_J1 (both A/cm^2, same h) IS a fair comparison; within 2D, S0 vs S12
(both A/cm) IS a fair comparison.

### C3. S0 vs S12 — corrected claim
`REPORT.md`'s "S12: agree to the digits shown" was written about `psi_contact_V`/`qf_dev_V`/`mass_action_dev`, all of
which genuinely do agree to the digits shown (re-verified: `psi_contact_V` differs only beyond the 13th significant
digit between S0/S12 in every device pair). It did **not** mean, and should not be read as meaning, that the internal
C2/C3 currents agree between S0 and S12 — they do not, by roughly 16.5-17 orders of magnitude in every one of the 3
device pairs (D2D: `5.03e-13 -> 7.24e-30`, ratio 6.9e16; D1D_J0: `2.66e-9 -> 8.19e-26`, ratio 3.2e16; D1D_J1:
`5.32e-9 -> 4.34e-26`, ratio 1.2e17). This is now stated explicitly, corrected from the earlier report's ambiguous
phrasing.

### C4. Cause of the S0-vs-S12 gap and of the residual C2 nonzero value — separated, not conflated
* **The C2/C1 measurement CODE is byte-identical between S0 and S12** (same `shadow_e1.measure()` call, same
  `EdgeCouple`/`ElectronCurrent`/`HoleCurrent` read, same arithmetic) — so neither the edge-cut integration method nor
  the contact/cross-section definition changes between S0 and S12. Since the value nonetheless changes by ~17 orders
  of magnitude between S0 and S12, **those two candidate causes are excluded as explanations for the S0-vs-S12 GAP
  specifically**, by elimination, not by new direct measurement of internal solver state (which this JSON does not
  contain).
* What DOES change between S0 and S12 is `extended_model`/`extended_equation` (confirmed set, section B/E5 below),
  which this project's own 7H-D4 ERRATUM already established (citing DEVSIM manual 9.3.2) concern model/equation
  assembly precision. The magnitude and consistency of the drop (~16.5-17 orders in all 3 independent device pairs) is
  consistent with a float64 cancellation mechanism of the same character this project's 7H-D1/D2 batches already
  characterized for contact currents near an ohmic contact. **This is the best-supported explanation available from
  existing evidence, not a newly, independently proven mechanism inside this batch** — no per-iteration or per-term
  trace was captured here that isolates drift-vs-diffusion cancellation directly.
* The REMAINING, still-nonzero S12-level residual (7e-30 to 8e-26 depending on device) and the reason C2 is nonzero at
  S0 in the FIRST place, are recorded as: **`NUMERICAL_OR_POSTPROCESSING_CAUSE_UNRESOLVED`** — this batch's JSON does
  not contain enough (no per-term drift/diffusion breakdown, no arbitrary-precision reference solve) to attribute the
  residual specifically to float64 cancellation inside DEVSIM's C-code assembly versus the plain-Python/numpy
  post-processing arithmetic in `measure()` itself (which is NOT run under `extended_model`/`extended_equation` at
  all — those flags affect DEVSIM's own internal assembly, not the numpy code that later multiplies
  `ElectronCurrent * EdgeCouple` and sums it). A further experiment (e.g. rerunning the post-processing arithmetic in
  higher precision on saved raw edge arrays) would be needed to separate these; not attempted here per this batch's
  read-only scope.

### C5. C0 near zero does not mean the internal current is uniformly near zero — stated explicitly
`C0` (real DEVSIM contact-current query) reads **exactly** `0.0` for every S0 run (D2D, D1D_J0, D1D_J1) and
~1e-30-1e-25 for S12 runs. Read on its own, this could be misread as "the whole device carries zero current
everywhere, to full precision." The internal `C2` cuts contradict that at S0: D2D's `+0.10` cut is `-5.03e-13 A/cm`
while its own `C0` at the adjacent contact is exactly `0.0` — a residual the contact query does not show AT ALL (the
contact-current computation is a different DEVSIM code path than the edge-based reconstruction, and evidently has
different, in this case better, cancellation behaviour at S0). This gap is recorded as a real, confirmed fact; its
cause is included in the `NUMERICAL_OR_POSTPROCESSING_CAUSE_UNRESOLVED` label above.

## D. Independence of the physical checks — reassessed

### D1. `V_bi/2` is largely fixed by the contact boundary condition itself, not solved for independently
Read directly from the installed DEVSIM source
(`…/site-packages/devsim/python_packages/simple_physics.py`):
* `:31-32`: `celec_model = "(1e-10 + 0.5*abs(NetDoping+(NetDoping^2+4*n_i^2)^0.5))"`,
  `chole_model` symmetric with `-NetDoping`.
* `:189-213` (`CreateSiliconPotentialOnlyContact`):
  `contact_model = "Potential - {bias} + ifelse(NetDoping>0, -V_t*log(celec/n_i), V_t*log(chole/n_i))"` — a
  **Dirichlet-type contact equation** that directly constrains `Potential` at the contact node to
  `bias + V_t*ln(celec_or_chole/n_i)`.
* At the boundary (far from the junction, `|NetDoping| = 1e18 >> n_i = 1e10`), `celec ~= NetDoping = 1e18` to 1 part
  in `4e-16` (from `sqrt(NetDoping^2 + 4n_i^2) ~= NetDoping*(1 + 2*(n_i/NetDoping)^2)`), so
  `Potential_contact ~= V_t * ln(1e18/1e10) = V_t * ln(1e8)`. Numerically:
  `0.025887193125 * 18.420680743952367 = 0.476859719912...` — **matches the recorded contact value to the digits
  shown, because it is essentially the SAME formula**, not an independent PDE result.
* **Correct scope of the claim**: contact-value agreement with the analytic `V_bi/2` verifies that DEVSIM's
  Dirichlet contact BC was set up correctly and is being read back correctly — a real but narrow check (was the right
  equation assembled at the right node). It is **not** an independent confirmation of the interior Poisson solve's
  correctness; the interior potential is what the PDE actually solves for, and its correctness is better judged from
  the `cut_profile` values away from the contacts and from the continuity-equation residuals (D2 below), not from the
  contact value repeating a boundary formula.

### D2. What the `Intrinsic*`-based DD initial guess trivially guarantees, and what the recorded residual adds
`CreateSiliconPotentialOnly` (`simple_physics.py:150-152`): `elec_i = "n_i*exp(Potential/V_t)"`,
`hole_i = "n_i^2/IntrinsicElectrons"`. `setup_drift_diffusion_equation`
(`tcad/device/devsim/semiconductor_equation.py:88-89`) initializes `Electrons`/`Holes` `init_from="IntrinsicElectrons"`
/`"IntrinsicHoles"`. Algebraically, at t=0 (before any DD Newton step): `n*p = n_i*exp(psi/V_t) * n_i*exp(-psi/V_t) = n_i^2`
**identically** (mass action exact by construction) and `phi_n = psi - V_t*ln(n/n_i) = psi - psi = 0`,
`phi_p = psi + V_t*ln(p/n_i) = psi - psi = 0` **identically** (quasi-Fermi flatness exact by construction, both
constant at exactly 0, trivially "flat"). **So `qf_dev_V` and `mass_action_dev` measured immediately after DD setup,
before any real Newton progress, are guaranteed near machine precision purely by this initialization — they do not by
themselves demonstrate anything the Newton solve discovered.**
What the recorded solve DOES add, genuinely: the per-equation residuals in `final_equations`
(e.g. D2D S0: `ElectronContinuityEquation: {abs: 5120.0, rel: 2.245e-14}`, `HoleContinuityEquation: {abs: 5120.0,
rel: 2.694e-14}`) are **continuity-equation** (flux-divergence) residuals, not mass-action or quasi-Fermi quantities —
these are not trivially forced to zero by the Boltzmann initial guess (a pointwise-correct `n,p` given `psi` does not
automatically zero the divergence of drift+diffusion flux at every node). Their smallness (relative ~1e-14 to 1e-16,
well under the 1e-6 threshold) at only 1 Newton iteration is real evidence the true equilibrium state is close to
this initial guess and that the assembled flux-balance residual is small there — genuinely informative, though
expected (not surprising) given how good the starting point already is.

### D3. 0 V flux-cancellation condition — stated, and its proven scope limited
Physical condition: at true equilibrium (0 net current, uniform quasi-Fermi levels), for each carrier species
`J_n(x,y) = q*mu_n*n*E + q*D_n*grad(n) = 0` and `J_p(x,y) = 0` **pointwise, everywhere** in the device (drift and
diffusion cancel locally, not just in aggregate). What the existing JSON proves: `C0` (exact 0 or ~1e-30 to 1e-25) at
the 2 contacts; `C2` (1e-13 to 1e-9 A/cm [2D] or A/cm^2 [1D] depending on precision variant) at exactly 5 specific
x-cuts (section C). **This proves near-cancellation only at those 7 sampled locations (2 contacts + 5 cuts), to the
precision shown there, not pointwise everywhere in the device** — no claim is made here about flux balance at any
other node, nor about the SPATIAL distribution of any residual imbalance between the sampled cuts.

### D4. J1's higher peak field — evidence, possible explanations, and what is NOT decided
Observed (both S0, matches to 5 digits at S12): D2D `max|E| = 358113.011 V/cm`; D1D_J0 `358113.010 V/cm` (agrees with
D2D to 8 significant figures); D1D_J1 `382716.987 V/cm` (**6.87% higher**). One structural fact, not an
interpretation: J0 has a node exactly at x=0 with two adjacent edges of length h=3.125e-7 cm each
(`[-h,0]` and `[0,+h]`); J1 has no such node — its single junction-crossing edge spans `[-h/2,+h/2]`, also length h.
DEVSIM's `ElectricField` edge model (`simple_physics.py`: `"(Potential@n0-Potential@n1)*EdgeInverseLength"`) is
evaluated per edge, so J0's peak (if it occurs at the central pair) and J1's peak (on its one central edge) are
different discrete objects even at identical h. **Possible explanations, not adjudicated here**: (a) J1's single
central edge captures a genuinely steeper local slice of a curved psi(x) profile that J0 spreads over two edges;
(b) a genuine difference in how each representation resolves the field peak at this h; (c) something requiring mesh
refinement to distinguish from (a)/(b). **This batch's data is one h, one snapshot, on 2 representations — it does
not include a mesh-convergence sweep, so it cannot decide between these.** The earlier `REPORT.md` line calling this
"a real J0-vs-J1 mesh-representation difference ... not a defect" is corrected to: an observed fact at one h, with a
plausible but unverified explanation; not confirmed to be free of a real underlying issue.

### D5. Analytic `W` recorded, not measured from the solved profile
`analytic_reference()` computes `W_0V_um = 0.048396...` from the Sze & Ng depletion formula using DEVSIM's own
`eps`/`V_t`/`n_i` — this is recorded as a reference number only. **No location was extracted from the actual solved
charge or field profile in this batch to identify where the real depletion edge falls**, at either 0 V point. The
5 fixed x-cuts (±0.25, ±0.10, 0 um) do span this width but were never used to fit or locate an edge. The claim
"the solution converges to width W" was never made in `REPORT.md` and is explicitly disclaimed here too: the analytic
number and the actual solved profile's own width are different questions, and only the former was computed.

## E. PLAN vs. actual implementation vs. raw evidence vs. verdict impact

| # | PLAN requirement | Actual implementation | Raw evidence | Verdict impact |
|---|---|---|---|---|
| 1 | D2D input identity: BOTH `candidate_e4.vtu` AND `candidate_e4.npz` sha256 checked before any solve (`PLAN.md`, D2D paragraph: "Mismatch on either sha256: MESH_INPUT_IDENTITY_FAIL") | `devices_e5.py:22-23` defines `E4_NPZ_SHA`, but `import_e4_candidate()` (`:83-91`) only computes/compares `vtu_sha`; `E4_NPZ_SHA` is never referenced in any comparison | `e5_D2D_S0.json`'s `mesh_identity` has only `{vtu_sha256, expected, equal}` — no npz field anywhere in any of the 6 JSONs | The VTU (the actual mesh geometry that matters for the solve) WAS checked and matched (`equal: true`, independently re-verified: `85ebcbae...` == E4's recorded artifact hash). The NPZ (E4's own separate geometry-check array, not consumed by this batch's solve path at all) was never checked. Does not invalidate the solve itself, but the PLAN's own stated stop condition ("either sha256") was not fully implemented |
| 2 | "Artifact: ... potential/field/doping state npz" (PLAN section 7) | No `.savez`/`.npz` call anywhere in `stage_e5.py`/`devices_e5.py`; profile `outputs` glob is `["e5_out/**/*.json"]` only (`remote/profiles.py`) | 6 JSON files + `e5_result.json`, no `.npz` in either run's `outputs/` directory | Raw per-node Potential/Electrons/Holes/ElectricField arrays were never saved; only the scalar/cut summaries in the JSON exist. Any further check of the full solved field (e.g. re-plotting the whole profile, not just 5 cuts) is not possible from the existing artifacts |
| 3 | "cut_profile()... Potential/ElectricField/NetDoping at specific x positions" (PLAN section 4) | `devices_e5.py` `cut_profile()`'s own docstring promises ElectricField; its actual return dict (`:143-162`) has only `x_actual_um, n_nodes, Potential_V, NetDoping_cm-3` — **no ElectricField field** | Every `cut_profile`/`cut_profile_poisson_only` entry in all 6 JSONs lacks an ElectricField key; the only ElectricField value anywhere is the single device-wide `max_abs_ElectricField_V_per_cm` scalar | No per-cut field value exists; D4's "field at the junction center" question can only be answered by the single global max, not a profile. A genuine implementation gap versus both the docstring and the PLAN text |
| 4 | 1D `geometric_continuum_reference` should be `N x X_HALF_UM x UM` (PLAN section 4: "N x domain half-length, here N x 5 um") | `doping_integrals()` (`devices_e5.py`) multiplies by a `depth` read from the device's own `y` node model; DEVSIM's 1D devices report `y` uniformly 0, so `depth=0`, giving `N*0*5*UM*UM = 0` | Both `e5_D1D_J0_*.json` and `e5_D1D_J1_*.json` record `geometric_continuum_reference: 0` exactly | The recorded `0` is not usable as the comparison reference the PLAN intended. Corrected value, computed here from the same already-recorded inputs (N=1e18, X_HALF=5.0 um), not from a new run: `1e18 * 5.0 * 1e-4 = 5e14 cm^-2`. Against that: D1D_J0's `5.0015625e14` is +0.03125% high (matches the J0 junction-line formula `N*h/2` exactly, `1.5625e11` excess); D1D_J1's `5.0e14` matches exactly. The 2D `2.500780905e11 cm^-1` integral was never mixed with the 1D `cm^-2` figures anywhere in this analysis (section C2's unit separation applies here too) |
| 5 | "S0 and S12... each its own complete run... reported separately" (PLAN section 3.4); implicit assumption of 6 independent runs | All 6 runs execute sequentially inside **one** `stage_e5.py` Python process / one DEVSIM session, sharing DEVSIM's global parameter table. `stage_e5.py`'s `finally` block resets `extended_model`/`extended_equation` to `False` (not to "unset") after every S12 run | `flags` field per JSON: `D2D_S0` (the very first run) reads `'UNSET: Cannot find parameter...'` for both flags; `D1D_J0_S0` and `D1D_J1_S0` (which run AFTER `D2D_S12`) read `False` (a defined boolean), not "UNSET" | Devices/meshes ARE independent (fresh objects each run, `devices_left: []` throughout, no cross-run leak in solved data — verified). Global DEVSIM **parameter state** is not independent: only the very first S0 run in the sequence is genuinely untouched; the other two S0 runs already carry an explicit `False` from a prior run's cleanup. "6 independent runs" should be read as independent devices/solves, not independent processes or fully pristine global state |

## F. Submission split

**1. Confirmed facts.** All 12 `devsim.solve()` calls across the 6 registered device/precision pairs report
`converged: true` from DEVSIM's own `info=True` result (independently re-verified this session against both runs'
raw JSON, kept separate per run). The 0 V Potential/carrier arrays on the 7H-E4 candidate mesh are close to the
model's internal equilibrium relations at the sampled locations checked (contacts, 5 x-cuts): mass-action and
quasi-Fermi deviations at or below ~1e-14 in every run; continuity-equation relative residuals ~1e-14 to 1e-16 at the
single DD Newton step taken. Contact potentials equal the DEVSIM contact boundary condition's own analytic value to
13+ digits (section D1: expected, not an independent PDE check).

**2. Corrected facts.** D2D's `psi_contact_V`/`C1` keys were swapped between `Si_xmin`/`Si_xmax` in post-processing
only (section B; corrected mapping in B5-B6, cross-validated against the name-correct `C0` to 15 digits); this did
NOT affect the solve, boundary conditions, or the underlying Potential/carrier arrays. The 1D `geometric_continuum_
reference` recorded `0` because of a units bug (section E, item 4); the corrected reference is `5e14 cm^-2`. Internal
C2/C3 currents differ between S0 and S12 by ~16.5-17 orders of magnitude (section C3) — `REPORT.md`'s "agree to the
digits shown" applied only to potential/qf/mass-action, not to internal currents, and is restated here explicitly so
it is not misread. Two PLAN-promised artifacts were not produced: the state npz (item 2) and per-cut ElectricField
(item 3).

**3. Unresolved / not determined.** The cause of the REMAINING (post-S12) internal-current residual and of why C0
reads exact 0 while C2 does not at S0 — `NUMERICAL_OR_POSTPROCESSING_CAUSE_UNRESOLVED` (section C4-C5; the
S0-vs-S12 GAP itself has elimination-based evidence pointing to assembly precision, but the residual's exact
magnitude is not independently isolated). The cause of J1's 6.87%-higher peak field (section D4) — observed at one h
only, no mesh-convergence data. 2D mesh convergence at any resolution — not attempted. Any biased (non-0V) diode
characteristic — never attempted, explicitly out of this batch's scope from the start.

**4. Gates that remain unchanged.** `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` — untouched, never called, never
bypassed. 7H-E4's `GEOMETRY_CANDIDATE_ONLY` — unchanged, not merged with this batch's electrical result in either
direction. This ERRATUM does not upgrade, and does not downgrade, either gate; no production support is claimed for
anything in this batch.

## No-change confirmation
`PLAN.md`/`PLAN.sha256` (E5), both runs' raw JSON/`run.log`/`summary.json`, and `REPORT.md` are byte-identical to
before this analysis (this analysis wrote only new files: this document and `data/c0_c1_c2_c3_full.json`). No
`tcad/`/`tests/` file touched. No new `devsim.solve` call was made — every number in this ERRATUM is read or
recomputed from the two existing runs' artifacts. Stopping here for Codex review; no further solve or next-batch
implementation is started.
