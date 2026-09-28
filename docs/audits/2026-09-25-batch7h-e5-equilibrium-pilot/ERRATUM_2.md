# Batch 7H-E5 ERRATUM 2 (read-only re-analysis of ERRATUM 1's D2/D3 and C4/C5; no new ViennaPS/DEVSIM execution)

Written after Codex's partial approval of `ERRATUM_1.md` (hashes, contact-label swap, 1D unit fix, S0/S12 internal-current
numbers all passed). This document corrects `ERRATUM_1.md`'s own D2/D3 independence claims and C4/C5 causal-elimination
claims. `PLAN.md`, `PLAN.sha256`, both runs' raw JSON/log/`summary.json`, `REPORT.md`, and `ERRATUM_1.md` are **not
modified** — confirmed below (No-change confirmation). No tolerance/threshold was changed. Serena MCP was checked again
this session and is still unavailable (`ToolSearch "serena mcp find_symbol"` returned no Serena tools; the cached
`plugin:serena:serena: "Skipping connection (recent failure cached...)"` failure notice is still in effect); `rg`/direct
`Read` of the installed DEVSIM source and the project source were used throughout, file:line cited for every claim.
No new `devsim.solve()` call was made anywhere in this batch — the only code executed was a standalone, pure-Python/
NumPy synthetic arithmetic script with no `import devsim`, described in section 1.

## 1. DD initial-condition identity, derived directly from the real DEVSIM/project source

Sources read directly (not from memory):

* `…/.venv/Lib/site-packages/devsim/python_packages/simple_physics.py:151-152` (`CreateSiliconPotentialOnly`):
  `elec_i = "n_i*exp(Potential/V_t)"` (this is `IntrinsicElectrons`), `hole_i = "n_i^2/IntrinsicElectrons"` (this is
  `IntrinsicHoles`).
* `tcad/device/devsim/semiconductor_equation.py:131-132` (`setup_drift_diffusion_equation`):
  `module.set_node_values(device=device, region=region, name="Electrons", init_from="IntrinsicElectrons")` and the
  same for `"Holes"`/`"IntrinsicHoles"` — confirmed these two calls are the only place `Electrons`/`Holes` are
  initialized before the DD solve.
* `…/simple_dd.py:19` (`CreateBernoulli`): `vdiffstr = "(Potential@n0 - Potential@n1)/V_t"` — this is `vdiff`, i.e. `v`.
  `Bern01 = "B(vdiff)"` (`:23`) is DEVSIM's built-in Scharfetter-Gummel Bernoulli function, `B(v) = v/(exp(v)-1)`
  (standard SG discretization; DEVSIM does not expose `B()`'s Python source, so this is the documented closed form,
  not re-derived from bytecode).
* `…/simple_dd.py:48` (`CreateElectronCurrent`):
  `Jn = "ElectronCharge*mu_n*EdgeInverseLength*V_t*kahan3(Electrons@n1*Bern01, Electrons@n1*vdiff, -Electrons@n0*Bern01)"`
  — the bracket is `n1*B(v) + n1*v - n0*B(v)`.
* `…/simple_dd.py:69` (`CreateHoleCurrent`):
  `Jp = "-ElectronCharge*mu_p*EdgeInverseLength*V_t*kahan3(Holes@n1*Bern01, -Holes@n0*Bern01, -Holes@n0*vdiff)"`
  — the bracket is `p1*B(v) - p0*B(v) - p0*v`.
* `…/simple_physics.py:257` (`CreateSRH`): `USRH = "(Electrons*Holes - n_i^2)/(taup*(Electrons+n1) + taun*(Holes+p1))"`.

**Algebraic derivation, at t=0 (immediately after `init_from`, before any Newton update), for an edge `(n0,n1)` with
ANY Potential array `psi0, psi1` (not assumed to be the correct equilibrium solution):**

```
n0 = n_i*exp(psi0/V_t),  n1 = n_i*exp(psi1/V_t)   =>  n0/n1 = exp((psi0-psi1)/V_t) = exp(v)   =>  n0 = n1*exp(v)
p0 = n_i^2/n0 = n_i*exp(-psi0/V_t),  p1 = n_i^2/n1 = n_i*exp(-psi1/V_t)  =>  p1/p0 = exp(-v)*... => p1 = p0*exp(v)

electron bracket = n1*B(v) + n1*v - n0*B(v)
                  = n1*B(v) + n1*v - n1*exp(v)*B(v)
                  = n1*[ B(v)*(1-exp(v)) + v ]
                  = n1*[ v/(exp(v)-1) * (1-exp(v)) + v ]      (B(v) = v/(exp(v)-1))
                  = n1*[ -v + v ] = 0                         identically, for ANY v

hole bracket     = p1*B(v) - p0*B(v) - p0*v
                  = p0*exp(v)*B(v) - p0*B(v) - p0*v
                  = p0*[ B(v)*(exp(v)-1) - v ]
                  = p0*[ v - v ] = 0                          identically, for ANY v
```

So `ElectronCurrent = HoleCurrent = 0` on **every edge**, for **any** Potential array — this is a property of the
`init_from` substitution combined with the SG discretization identity `B(v)*(exp(v)-1) = v`, not a property of the
specific equilibrium `psi` this batch solved for. Since every edge current is individually zero, the node-level
continuity residual (`div(J)`, a weighted sum of incident edge currents) is also identically zero at **every node**,
before summing in any generation/recombination term. Additionally `n*p = n_i*exp(psi/V_t) * n_i^2/(n_i*exp(psi/V_t)) =
n_i^2` **identically at every node**, so `USRH = (n*p - n_i^2)/(...) = 0/(...) = 0` identically too — there is no
recombination source term to offset. **The entire discretized continuity-equation residual is algebraically zero at
t=0, for an arbitrary Potential array, purely as a consequence of the `init_from="Intrinsic*"` substitution.**

**Numerical confirmation (synthetic, no DEVSIM call)**: a standalone NumPy script (not committed — pure verification,
run and discarded per this batch's read-only scope) evaluated the two brackets above on 200,000 random edge pairs with
`psi0, psi1` drawn uniformly from -5..+5 V (deliberately NOT any solved profile — the point is the identity does not
depend on `psi` being correct): `max|electron bracket| relative to the bracket's own natural scale (n1*v)` =
`4.87e-12`, consistent with float64 cancellation noise in a sum of terms reaching magnitude ~1e79-1e80 at these
extreme potentials, not a violation of the exact-arithmetic identity. At smaller, device-realistic potentials
(0V equilibrium contact value ~±0.477 V — see `ERRATUM_1.md` B5), the same test's absolute bracket values are far
below the extreme-`psi` case, consistent with — not independently proving, since it is the same identity — the real
JSON's own recorded residuals cited below.

**Retraction of `ERRATUM_1.md` D2 (lines 208-225).** D2 states: *"these are not trivially forced to zero by the
Boltzmann initial guess (a pointwise-correct n,p given psi does not automatically zero the divergence of drift+
diffusion flux at every node)... Their smallness... is real evidence the true equilibrium state is close to this
initial guess... genuinely informative, though expected."* **This is retracted.** The derivation above shows the
opposite of the parenthetical claim: the `init_from="Intrinsic*"` substitution DOES automatically zero the flux
divergence at every node, exactly, for any Potential array — not just a pointwise-correct one relative to some
external truth. Corrected statement: **DD's small continuity-equation relative residual (`ElectronContinuityEquation
rel=2.245e-14`, `HoleContinuityEquation rel=2.694e-14`, D2D S0, re-read this session from
`data/remote_run_36151109973/outputs/e5_out/e5_D2D_S0.json`'s `solve_calls[1].final_equations`) and its convergence in
exactly `n_iterations: 1` (same file, `solve_calls[1].n_iterations`) are the expected, algebraically-guaranteed
consequence of this initialization for ANY Potential array — including a wrong one — and therefore do **not**
constitute independent physical verification that the specific solved `Potential` is the correct equilibrium Poisson
solution. They may be reported as **numerical self-consistency of this discretized implementation** (the residual is
small and 1-iteration convergence occurred, exactly as the algebra predicts), never as evidence that the Poisson
solve's `psi` is physically correct — that question is answered only by the Poisson equation's own residual and by
independent checks of the interior profile, not by DD's 1-iteration behavior.

The float64, non-exact character of the real residual (`2.245e-14`, not exactly `0`) is exactly the Bernoulli-
evaluation / exponential / current-assembly rounding the Codex prompt anticipated — reported here as implementation
numerical consistency, not re-used as new evidence for Poisson accuracy.

## 2. Verification-scope correction (widen `qf_dev_V`/`mass_action_dev`, narrow `C0`/`C2`)

**`qf_dev_V`/`mass_action_dev` are whole-node-array checks, not 7-location checks — `ERRATUM_1.md` F1 mis-scoped
them.** Read directly, `shadow_e1.py:79-82` (`measure()`, reused verbatim by `stage_e5.py`):
```python
phin, phip = psi - vt*np.log(n/ni), psi + vt*np.log(p/ni)
out["qf_dev_V"] = float(max(np.max(np.abs(phin - np.median(phin))), np.max(np.abs(phip - np.median(phip)))))
out["mass_action_dev"] = float(np.max(np.abs(n*p/ni**2 - 1)))
```
Both `np.max(...)` calls run over the **entire node array** (`psi, n, p = nv("Potential"), nv("Electrons"),
nv("Holes")`, `shadow_e1.py:45`, all nodes in region `Si`) — not a subset restricted to the 2 contacts or 5 cuts.
`ERRATUM_1.md` F1 (line 274-275: *"close to the model's internal equilibrium relations at the sampled locations
checked (contacts, 5 x-cuts): mass-action and quasi-Fermi deviations at or below ~1e-14"*) is **corrected**: the
`~1e-14` mass-action/quasi-Fermi figures (re-read this session for D2D S0: `qf_dev_V = 7.06e-16`,
`mass_action_dev = 2.53e-14`) are **global** maxima over every node in the mesh, a wider (not narrower) claim than
F1 stated. This widened scope does **not** make them independent physical verification, per section 1 above — they
are the same trivial algebraic identity evaluated globally instead of at a subset, so they are simultaneously
WIDER in spatial scope and NO STRONGER in evidentiary weight than F1 implied.

**`C0`/`C2` do not demonstrate pointwise (per-edge) flux cancellation — `ERRATUM_1.md` D3's framing is corrected.**
`C0` (`shadow_e1.py:53-56`) is a single DEVSIM-computed **aggregate contact current** (`get_contact_current`,
summed internally over every edge terminating at that contact — DEVSIM does not expose the per-edge decomposition of
this call). `C2` (`shadow_e1.py:62-67`) is this project's own **sum over every edge crossing a given x-cut**
(`float(np.sum(s * Fn))` etc.) — again a scalar aggregate, not a per-edge value. Neither one demonstrates that any
INDIVIDUAL edge's `J_n`/`J_p` is near zero at that location: a near-zero sum is consistent with many large,
oppositely-signed per-edge currents cancelling in the aggregate, which this project's own C2 raw data already shows is
plausible in character (C2 is exactly this kind of signed sum, `np.where(a & ~b, 1.0, np.where(b & ~a, -1.0, 0.0))`
applied per edge). `ERRATUM_1.md` D3 (line 232: *"This proves near-cancellation only at those 7 sampled locations...
to the precision shown there"*) is corrected: it proves near-cancellation of the **aggregate** flux at those 7
locations, not pointwise cancellation at the individual edges that make up each aggregate — including at those same 7
locations. No raw per-edge `ElectronCurrent`/`HoleCurrent` array was saved to any of the 6 JSONs (confirmed by
`jq`-equivalent key inspection of all 6 files: only the aggregated `C0`/`C1`/`C2`/`C3` scalars and `n_edges` counts
exist, never a per-edge array). **Device-wide, per-edge (pointwise) local-current accuracy is therefore
`NOT_MEASURED`** by this batch's artifacts, kept as an explicit status rather than inferred from the aggregates.

The 2D (A/cm) vs 1D (A/cm^2) unit separation from `ERRATUM_1.md` C2 (already Codex-approved) is unchanged by this
correction and still applies wherever C2/C0 values are quoted.

## 3. S0/S12 causal reasoning, restricted to what elimination actually supports

**`ERRATUM_1.md` C4's elimination argument is logically incomplete — corrected.** C4 (lines 152-158) argued: *"The
C2/C1 measurement CODE is byte-identical between S0 and S12... so neither the edge-cut integration method nor the
contact/cross-section definition changes... those two candidate causes are excluded as explanations for the
S0-vs-S12 GAP specifically, by elimination."* This conflates two different things: (a) the measurement **algorithm**
not changing, and (b) the measurement algorithm **being a possible amplification/cancellation site**. Both can be
true simultaneously — a fixed, unchanged formula (a plain NumPy `np.sum` over a list of signed per-edge terms, no
Kahan summation used in `shadow_e1.py`'s own `C1`/`C2` code, unlike DEVSIM's internal `kahan3` calls in
`simple_dd.py:48,69`) can still produce a 16-17-order-of-magnitude different OUTPUT when its per-edge INPUT values
themselves differ by many orders of magnitude between S0 and S12 (which is exactly what `extended_model`/
`extended_equation` changing DEVSIM's own internal assembly precision would cause). **"Same code" proves only that
the algorithm is unchanged; it does not exclude the algorithm's own summation from being where the S0-vs-S12
difference is amplified or cancelled**, because catastrophic cancellation in a fixed-formula sum is caused by input
differences, not by formula differences. Corrected statement: the fact that `extended_model`/`extended_equation`
correlates with the ~16.5-17 order-of-magnitude change (all 3 device pairs, consistent direction) remains
well-supported CORRELATIONAL evidence, restated from `ERRATUM_1.md` C4's second bullet, which is not retracted. But
**which stage of the computation** — DEVSIM's internal C-code edge-model assembly under the two precision flags, vs.
this project's own unsummed/non-Kahan `np.sum` over `Fn`/`Fp` in `measure()` — is where the difference is actually
amplified or cancelled is **not determined** by this evidence (no per-term/per-edge trace exists in the saved JSONs
to distinguish the two, and by the argument above, "same measurement code" cannot be used to rule either one out).
This is downgraded from "excluded by elimination" to `NUMERICAL_OR_POSTPROCESSING_CAUSE_UNRESOLVED`, matching the
label C4's own third bullet and C5 already used for the residual magnitude — the exact SITE of the S0-vs-S12 GAP
mechanism now carries the same unresolved label, not a narrower "excluded except for X" claim.

**`ERRATUM_1.md` C5's "better cancellation behaviour" claim is downgraded.** C5 (line 181-182) stated the contact
query path "evidently has different, in this case better, cancellation behaviour at S0" than the edge-based C2
reconstruction. This asserts a CAUSE (favorable cancellation) for an observed correlation (C0 reads exact `0.0`,
adjacent C2 reads `-5.03e-13`). Corrected: the fact that `C0` and `C2` are genuinely different DEVSIM/NumPy code
paths (confirmed, `simple_physics.py`'s `get_contact_current` vs. this project's own `Fn = ev("ElectronCurrent")*cpl`
followed by `np.sum`) is kept as a confirmed structural fact. Whether that difference in code path is WHY C0 reads
more favorably is **not established** by this evidence and is relabeled `NUMERICAL_OR_POSTPROCESSING_CAUSE_UNRESOLVED`,
not asserted as "better cancellation behaviour."

## 4. Final verdict, re-bounded

**Claims that remain supportable, restated precisely:**
* *(Corrected 2026-09-28; the original bullet read "All 12 `devsim.solve()` calls (both runs) report
  `converged: true`", which was wrong — the two runs have different counts and must not be pooled.)* Recounted
  directly from each run's six per-run `e5_*.json` `solve_calls` arrays (`e5_result.json` excluded, it is an aggregate
  of the same calls):

  | run | per-run files | recorded solve calls | `converged: true` |
  |---|---|---|---|
  | `remote_run_36149228558` (first, FAILED) | 6 | 6 (D2D_S0: 2, D2D_S12: 0, each 1D: 1) | 2 (both D2D_S0) |
  | `remote_run_36151109973` (clean rerun) | 6 | 12 (2 per file) | 12 |

  Only the clean rerun's 12 calls all report `converged: true` from DEVSIM's own `info=True` result. `ERRATUM_1.md`
  F1's "All 12" (line 271, not edited) likewise refers to the clean rerun only.
* The Poisson equation's own residual (`PotentialEquation`, e.g. D2D S0: `rel=2.412e-07` after 10 iterations,
  `data/remote_run_36151109973/.../e5_D2D_S0.json` `solve_calls[0]`) is a real, non-trivial convergence result — this
  equation is not subject to section 1's initialization-identity argument (that argument applies only to the DD
  continuity equations, whose initial state is fixed by `init_from`; the Poisson equation solves for `Potential`
  itself, starting from whatever prior state the node model had, and its own residual genuinely reflects Newton
  progress on that equation).
* The recorded interior potential profile (`cut_profile`, away from the contacts) and the y-direction symmetry
  (`y_symmetry_max_spread_V`) remain real, un-retracted observations from `ERRATUM_1.md` — unaffected by this
  document, which only concerns D2/D3/C4/C5.

**Claims that are NOT supportable and must not be asserted:**
* Boundary contact-value agreement with the analytic `V_bi/2` (`ERRATUM_1.md` D1, unaffected/unretracted by this
  document, already correctly scoped there), DD's 1-iteration continuity-residual smallness (section 1, this
  document), and mass-action/quasi-Fermi flatness (section 1/2, this document) are **not four independent physical
  verifications** — the second and third are one and the same algebraic consequence of `init_from`, evaluated two
  different ways, and neither adds evidence beyond confirming the implementation initializes and assembles as coded.
* Near-zero `C0` alone does not establish that internal/local current is accurate anywhere else in the device
  (`ERRATUM_1.md` C5, already correctly cautioned there, reaffirmed here).
* The exact stage where the S0-vs-S12 internal-current gap is created or cancelled (section 3, this document) and
  the cause of J1's 6.87%-higher peak E-field (`ERRATUM_1.md` D4, unaffected/unretracted) remain undetermined.
* This one mesh, 0 V result does not approve 2D mesh convergence, any biased I-V characteristic, or production
  support of any kind (`ERRATUM_1.md` F3/F4, unaffected/unretracted).

`EQUILIBRIUM_PILOT_ONLY`, `GEOMETRY_CANDIDATE_ONLY` (7H-E4), and `STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`
remain exactly as they were — untouched, not upgraded, not downgraded by this document. `stage_e5.py`'s internal
`"CONVERGED_OK"` string (`stage_e5.py:95`) is confirmed, by reading the source, to be a program-internal status label
assigned from `phys_ok` (a boolean combining `positive_finite`, `y_symmetry`, `doping_integrals["all_finite"]`, and
the contact-label inequality check) — it is an internal pass/fail marker for this script's own control flow, not an
external physical-approval phrase, and must not be quoted as one.

## 5. Correction table

| # | ERRATUM 1 original claim | Real source / algebraic evidence | Corrected wording | Verdict impact |
|---|---|---|---|---|
| 1 | D2: DD's small continuity residual + 1-iteration convergence is "real evidence... genuinely informative" independent of the trivial initial guess | `simple_physics.py:151-152`, `semiconductor_equation.py:131-132`, `simple_dd.py:19,48,69` — algebraic derivation (section 1) proves electron/hole current brackets are exactly 0 on every edge for ANY Potential array at `init_from` time; confirmed `n_iterations:1` in the real JSON | DD's small residual/1-iteration convergence is the expected, algebraically-guaranteed consequence of `init_from="Intrinsic*"` for any Potential array; report as implementation numerical consistency only, never as independent Poisson-accuracy evidence | No gate change. Narrows what "confirmed facts" (F1) may claim about DD as independent verification |
| 2 | F1: mass-action/qf deviations "at the sampled locations checked (contacts, 5 x-cuts)" | `shadow_e1.py:79-82`: `np.max` over the FULL node array, not a 7-location subset | qf_dev_V/mass_action_dev are global (whole-mesh) maxima; still the same trivial algebraic identity, so wider in scope but not stronger as independent evidence | No gate change. Corrects F1's stated scope |
| 3 | D3: C0/C2 prove "near-cancellation... at those 7 sampled locations" | `shadow_e1.py:53-56` (C0, DEVSIM-internal aggregate), `:62-67` (C2, this project's own signed `np.sum` over crossing edges) — both are aggregates, no per-edge array saved in any of the 6 JSONs | C0/C2 show near-zero AGGREGATE flux at those locations; pointwise (per-edge) cancellation is NOT_MEASURED anywhere, including at those same 7 locations | No gate change. Narrows what D3 may claim |
| 4 | C4: "same measurement code" excludes edge-cut integration/contact definition as GAP causes, "by elimination" | Same code with different-precision inputs can still amplify/cancel differently (catastrophic cancellation is an input-dependent, not formula-dependent, phenomenon); no per-edge trace exists to localize the effect | S0-vs-S12 correlates with `extended_model`/`extended_equation` (kept); the exact computational stage (DEVSIM assembly vs. this project's own `np.sum`) where the gap forms is `NUMERICAL_OR_POSTPROCESSING_CAUSE_UNRESOLVED`, not excluded | No gate change. Downgrades an over-strong elimination claim |
| 5 | C5: contact path "evidently has... better cancellation behaviour" at S0 | Confirmed only that C0 and C2 are different code paths (`get_contact_current` vs. `Fn=ev(...)*cpl; np.sum`); no evidence isolates WHY they differ | Different code paths confirmed; the favorable-cancellation explanation is `NUMERICAL_OR_POSTPROCESSING_CAUSE_UNRESOLVED`, not asserted | No gate change. Removes an unsupported causal claim |

## No-change confirmation

`git diff --stat` against `PLAN.md`/`PLAN.sha256`/`REPORT.md`/`ERRATUM_1.md`/both runs' raw `data/remote_run_*`
directories/`tcad`/`tests`/`tcad_2d_stagewise.py`/`examples`, run immediately before writing this document, is empty
(no output, exit code 0) — none of those paths have any working-tree change. `PLAN.sha256` still reads
`924395fb86a72658853a9b8ffd7827cdb0ddf6c1473d55609af09764ce8802fa  PLAN.md`, unchanged. No `devsim.solve()` (or any
`import devsim`) call was made anywhere in this batch; the only code executed was the standalone synthetic NumPy
arithmetic check in section 1 (no DEVSIM import, no mesh, no device). This document is the only new file
(`ERRATUM_2.md`); nothing else was written or modified. Stopping here for Codex review; no further experiment's PLAN
or implementation is started in this batch.
