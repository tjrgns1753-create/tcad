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

## 엔진 정보의 증거 범위

`engine_info`는 별도의 버전 조회 프로세스를 켜거나 끄는 옵션이며 profile 자식의
실제 엔진 사용을 관측하지 않는다. `summary.devsim.scope=ISOLATED_VERSION_PROBE`,
`profile_execution_observed=false`를 확인해야 한다. 조회를 끈 경우 `NOT_PROBED`이며,
이를 "자식이 엔진을 import하지 않았다 / solve 0회"로 읽으면 안 된다.
실제 solve·write·cleanup 기록은 profile별 원본 outputs에서 따로 검증한다.
이 변경 이전의 `NOT_IMPORTED / engine-free profile`도 전체 자식의 실행 증거가
아니다. 과거 원본 summary를 수정하지 않고 해당 보고서에서 범위를 설명한다.

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
