# Batch 7H-C pre-registration (fixed BEFORE any DEVSIM solve)

Hash of this file, `data/fixtures_7hc.json` and `scripts/meshes.py`/`build_fixtures.py` is recorded in
`data/draft_sha256_before_solve.txt` before the first `devsim.solve` of this batch. Nothing here may change
after results are seen; later findings go to `REPORT.md`.

## Official contract vs. prior experimental finding

Official DEVSIM 2.11.0 manual (devsim.net/models.html, copy in `data/manual/`):
* Control-volume assembly: the PDE form is dX/dt + div(Y) + Z = 0. Node models are integrated over the node
  volume; edge models "are integrated with the perpendicular bisectors along the edge onto the nodes on either
  end"; element edge models are integrated with `ElementEdgeCouple`.
* The integration models can be replaced with `set_parameter` names `node_volume_model`, `edge_couple_model`,
  `edge_node0_volume_model`, `edge_node1_volume_model`, `element_edge_couple_model`,
  `element_node0_volume_model`, `element_node1_volume_model`. The manual documents these ONLY in the
  "Cylindrical coordinate systems" section; it does not state that they apply to Cartesian 2D.
* `EdgeNodeVolume = 0.5*EdgeCouple*EdgeLength` in the manual is a user-defined example, not the definition of
  the built-in `EdgeNodeVolume`.
* `get_matrix_and_rhs(format)` returns the assembled matrix and right-hand side; `get_equation_numbers` maps nodes
  to rows.
* The manual cites Sanchez & Chen, "Element edge based discretization for TCAD device simulation", IEEE TED
  68(11):5414-5420 (2021), doi:10.1109/TED.2021.3094776, and Scharfetter & Gummel, IEEE TED ED-16(1):64-77 (1969),
  doi:10.1109/T-ED.1969.16566. Neither paper was read in full in this batch; they are cited only as the manual's
  references for the element-edge scheme and the edge current discretization.

Prior experimental finding (Batch 7H-B, NOT official): in DEVSIM 2.11.0, `ElementEdgeCouple = |(L/2)cot|`,
`EdgeNodeVolume = 0.25*EdgeCouple*EdgeLength`, `NodeVolume = sum of EdgeNodeVolume`.

## Fixtures (`data/fixtures_7hc.json`, built by `scripts/build_fixtures.py`)

Rectangle 2 x 1 um (M4_scale2: 4 x 2 um); left contact = boundary edges at x = x_min, right = x = x_max;
top/bottom insulating. Coordinates dyadic (1/64 um); geometry classified with exact integer arithmetic.

| mesh | points | triangles | acute/right/obtuse | angle range (deg) | Delaunay violations | edges with negative signed couple | predicted sum(NodeVolume)/area (7H-B rule) |
|---|---|---|---|---|---|---|---|
| M1 non-obtuse | 47 | 68 | 60/8/0 | 26.57-90.00 | 0 | 0/114 | 1.000000000000 |
| M2 right structured | 45 | 64 | 0/64/0 | 45.00-90.00 | 0 | 0/108 | 1.000000000000 |
| M3 Delaunay + obtuse | 45 | 64 | 53/4/7 | 21.37-114.44 | 0 | 0/108 | 1.041808146024 |
| M4 non-Delaunay (same points as M3) | 45 | 64 | 11/2/51 | 12.43-128.48 | 32 | 32/108 | 1.478070001897 |
| M4 mirror / rot180 / scale2 | 45 | 64 | 11/2/51 | 12.43-128.48 | 32 | 32/108 | 1.478070001897 |

All meshes: all triangles CCW, 0 exact positive overlaps, exact area 2 um^2 (scale2: 8 um^2), 5 left and 5
right contact nodes. M3 and M4 share the point set; only diagonals differ. The first M4 design (zipper with the
longer diagonal) produced inverted/overlapping triangles and was discarded before any solve.

## Experiments, analytic references, tolerances

As written in `fixtures_7hc.json` -> `spec`:
* A: phi = x/L V with left 0 V, right 1 V, no source. E1 = (V0-V1)*EdgeInverseLength; E2 = (V0-V1)*EdgeCouple.
* B: sigma = 1 S/cm, dV = 1 V, I = sigma*H/L*dV = 0.5 A/cm of depth for every mesh. Signs recorded as returned;
  check |I| and I_left + I_right = 0.
* C1: sum(NodeVolume) vs exact area. C3: phi = (x^2+y^2)/l^2, l = 1e-4 cm, Z = +4/l^2 V/cm^2, Dirichlet everywhere.
* Tolerances: EXACT_V = 1e-10 V, EXACT_I_REL = 1e-10, SIGNIFICANT_REL = 1e-6, WEIGHT_REL = 1e-12.

## A-priori predictions (analysis, to be confirmed or refuted)

P1-P5 as listed in `fixtures_7hc.json` -> `spec.a_priori_predictions`.
