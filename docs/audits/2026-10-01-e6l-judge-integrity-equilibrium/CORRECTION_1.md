# E6L CORRECTION 1 (additive; `REPORT.md`, the E6K judge, the stored W_E values, the tolerances and the E6K D FAIL are unchanged)

No solve, no engine import. Recomputed from the committed `states.npz` (E6K run 36815925901); pinned by `tests/unit/test_e6l_correction_mock.py`.

## A. Two different W_E computations were conflated in REPORT.md section 6
1. **E6K judge / stored `metrics.WE`** (`pn_reference.width_from_field`, called with the edge MID-POINTS): trapezoid of |E| between consecutive edge mid-points,
   `T = sum_i 0.5 (|E_i| + |E_{i+1}|) (xm_{i+1} - xm_i)` [V], and `W_E = 2 T / E_max` [cm]. The first and last half-edges are not covered and |E| is interpolated linearly between mid-points.
2. **E6L `W_E_bookkeeping`** (`pb_equilibrium.py`): edge sum `S = sum_i |E_i| (x_{i+1} - x_i)` [V], and `2 S / E_max` [cm].
They are not the same number. From the stored equilibrium snapshots (`L{k}_rev__2__bias+0.000`):
| level | midpoint trapezoid T [V] | edge sum S [V] | T/S - 1 | stored E6K W_E = 2T/E_max [cm] | 2S/E_max [cm] |
|---|---|---|---|---|---|
| L0 | 0.8348742913514126 | 0.8345045098471620 | 4.431e-4 | 1.5211785e-5 | 1.5205048e-5 |
| L1 | 0.8345993964579969 | 0.8345045098471621 | 1.137e-4 | 1.4991478e-5 | 1.4989774e-5 |
| L2 | 0.8345293145189819 | 0.8345045098471620 | 2.972e-5 | 1.4884188e-5 | 1.4883746e-5 |
At -1 V (`__6__bias-1.000`): T/S - 1 = 3.115e-4 / 7.893e-5 / 2.029e-5.
- **Identity (edge sum only).** Each stored `ElectricField_i` equals (V_i - V_{i+1})/(x_{i+1} - x_i) (checked in E6L), so the SIGNED sum `sum_i E_i (x_{i+1} - x_i)` telescopes to V_first - V_last = -0.834504509847162 V at equilibrium.
  The sum of |E_i| equals |V_last - V_first| only if the field never changes sign along the path. In the stored equilibrium data it does not: positive / negative / exactly-zero edges are 0 / 139 / 205 (L0), 0 / 272 / 412 (L1), 0 / 539 / 831 (L2); at -1 V 0 / 344 / 0, 0 / 684 / 0, 0 / 1370 / 0.
  So for these data S = |V_last - V_first| = V_bi (to round-off), and `2S/E_max = 2 V_bi / E_max`, hence `(2S/E_max) / W_dep = E_dep / E_max` -- this is the relation REPORT.md printed (1.062112 / 1.047075 / 1.039668).
- **Approximation (the E6K W_E).** The stored E6K W_E uses T, not S; `W_E = 2 V_bi / E_max` holds for it only approximately, with relative error T/S - 1 above (4.4e-4 -> 3.0e-5 at equilibrium), which decreases by about a factor 4 per refinement level.
- **Corrected statement.** REPORT.md section 6's "W_E = 2 V_bi / E_max and W_E / W_dep = E_dep / E_max exactly" is true for the edge-sum quantity and only approximately true (<= 4.4e-4 relative here) for the W_E that the E6K judge actually used.
  The practical conclusion stands in weakened form: the E6K W_E item is almost entirely determined by E_max and the boundary-fixed potential drop, so it is not independent evidence; it is not an exact algebraic duplicate.

## B. The 37.50 V/cm at L2 is a residual, not an independently established discretisation error
REPORT.md section 5 labelled row 3 "discretisation" and the conclusions called it a discretisation term. What the number is: (mean field of the chosen continuum PB reference over that edge) - (the DEVSIM value of that edge) = 112173.8554 - 112136.3558 = 37.50 V/cm.
- Established: the PB quadrature is converged (difference between 32 and 64 Gauss points ~3e-11 V/cm); the DEVSIM edge value is the stored potential difference over the edge.
- Not separated quantitatively: the effect of the finite 20 um domain and the contact boundary condition on the PB reference (argued negligible, not computed); the cause of the non-zero junction-node potential (-2.7e-4 V at L2);
  the role of the unequal left/right edge lengths (the explanation given in REPORT.md contains a hypothesis).
- The algebraic split gap = model + measurement + remainder shows how the numbers add up; it does not by itself prove that each part has the cause its label suggests.
**Corrected wording:** "residual between the continuum PB reference and the discrete result; discretisation and the representation near the junction are suspected, but the individual causes have not been separated quantitatively."
The numbers in REPORT.md are kept. Classification: facts = the three numbers and their sum, the quadrature convergence, the edge-field definition; hypotheses = zero-charge junction node with unequal neighbouring edges, mesher asymmetry as the source of psi(0) != 0; not measured = finite-domain / boundary-condition contribution.
No production solver change follows from this.
