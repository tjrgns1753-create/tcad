"""Allowlist of runnable profiles for the remote runner.

A request (remote/request.json) may only NAME a profile defined here and supply
parameters validated against that profile's schema. No request field is ever
executed as a shell string: the runner builds an argv list from the profile.

To add an experiment: add a PROFILES entry (entry script inside the repo, fixed args,
optional validated params, timeout, declared inputs and output globs) and commit a new
remote/request.json that selects it. See remote/README.md.
"""

# Every profile runs as:  <venv python> <entry> <args...>   (no shell)
PROFILES = {
    "phase5_smoke": {
        "description": "Small real check: ViennaPS etch -> ProcessResult -> DevSim Laplace solve.",
        "entry": "tests/integration/test_phase5_devsim_real.py",
        "args": [],
        "params": {},                       # name -> {"choices": [...]} | {"int": [min, max]}
        "timeout_s": 600,
        "inputs": ["tests/integration/test_phase5_devsim_real.py"],
        "outputs": [],                      # [{"glob": "relative/glob", "max_mb": N}, ...] uploaded if within budget
        "regenerate": "Rerun this profile; the test writes only to a temp directory and produces no artifact.",
    },
}

# Global limits (bytes / counts). Anything over budget is omitted and reported, never silently dropped.
MAX_TOTAL_OUTPUT_MB = 200
MAX_LOG_MB = 20
REQUEST_ID_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"
