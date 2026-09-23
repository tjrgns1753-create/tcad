# PLAN errata (written before any D3 computation; PLAN.md itself is unchanged)

PLAN.md section 4 says "a run whose 11 solve steps are not all accepted". The D3 worker records **12** solve steps
per run (A, B0, four forward biases, Arev, B0rev, four reverse biases): 7H-D2 also solved the reverse-branch 0 V state
but did not record it, which is where "11" came from. The criterion is unchanged and unambiguous: **every** recorded
solve step must be accepted (converged and final relative update < 1e-10); `analyze_d3.py` checks all 12 named steps.
