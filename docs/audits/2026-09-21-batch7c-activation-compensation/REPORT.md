# Batch 7C -- dopant activation state + compensation truthfulness

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` (unchanged, nothing staged, nothing committed).
The earlier Tier 1 `run_doping()` change (a refused doping is never reported as applied) is kept.

Five defects fixed: (1) donor/acceptor collapsed to a net, (2) `chemical_state` gated nothing, (3) a CHEMICAL attachment reached DevSim as
active, (4) reattach succeeded on any attachment, (5) a partly attached request left active attachments behind.

* `patches/PROD_*.patch` -- this batch's production diff, per file (snapshot-before vs now; pre-existing dirty diffs are not included).
* `patches/TESTS_*.patch` -- the test-side edits (explicit `chemical_state="ACTIVE"` on direct fixtures, one exact field-set update, the
  canonical-gate real test migrated for the GUI CHEMICAL contract).
* `scripts/mutation_runner.py`, `raw/MUTATION_production.out.txt` -- 11 production mutations, each caught by the stated assertion; the mutations
  are applied to scratch copies only.
* `raw/FINAL_*`, `raw/AFTER_*` -- targeted runs; `raw/IMPACT_*`, `raw/BASELINE_before7c_*` -- impact survey and pre-change baselines.
