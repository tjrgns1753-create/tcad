# Remote runner (GitHub-hosted Windows)

Runs long ViennaPS/DevSim computations off the laptop. Branch: `claude/remote-runner`.
Trigger: a push to that branch that touches `remote/request.json` (or the runner files).

## How to run something

1. Make sure a **profile** for it exists in `remote/profiles.py` (see below).
2. Edit `remote/request.json`:
   ```json
   {"schema": 1, "request_id": "my-run-001", "profile": "phase5_smoke", "params": {}}
   ```
   `request_id` must be unique per run (`[A-Za-z0-9._-]`, max 64). Only `schema`, `request_id`,
   `profile`, `params`, `note` are accepted; any other field, or any command string, is rejected.
3. Commit and push to `claude/remote-runner`. The Actions run appears at
   `https://github.com/tjrgns1753-create/tcad/actions`.
4. Download the artifact `remote-run-<run_number>` (or `gh run download <run-id>`):
   `summary.json`, `run.log`, `outputs/...`.

## Adding a new experiment (new profile)

Add an entry to `PROFILES` in `remote/profiles.py`: `entry` (a script inside the repo), fixed `args`,
`params` (each with `choices` or an `int` range; substituted into `args` as `{name}`), `timeout_s`,
`inputs` (hashed into the summary), `outputs` (globs with `max_mb`), and `regenerate` (how to
recreate anything omitted for size). Commit it together with the request that uses it.
Validate locally without running anything: `python remote/run_profile.py --validate-only --out <dir>`.

## Guarantees

- Refuses to execute outside a GitHub-hosted runner (`GITHUB_ACTIONS=true`, `RUNNER_ENVIRONMENT=github-hosted`).
- `summary.json` records source commit, request/profile, input hashes, package versions, DevSim info,
  runner facts, start/end time, duration, exit code, output hashes, omitted files, redaction counts,
  and whether `tcad/`, `tests/`, `tcad_2d_stagewise.py`, `examples/` equal the review SHA in `remote/config.json`.
- Failure, timeout and validation errors stay `FAIL` / `TIMEOUT` / `ERROR` with a non-zero exit code.
- The repository is public: logs and summary pass through a sanitizer (absolute paths, token patterns);
  if sensitive-looking text remains in `summary.json` it is withheld and the run is marked `ERROR`.
- Limits: one job <= 350 min (GitHub cap 360), 4 vCPU. Output budget 200 MB total; larger files are omitted
  and listed with hash and the profile's regeneration note.
