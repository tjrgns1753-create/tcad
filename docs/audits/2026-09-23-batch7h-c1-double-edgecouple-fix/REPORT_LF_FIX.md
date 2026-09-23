# Batch 7H-C1 최종 보완: LF 정리와 fixture node 분류 정확화

`REPORT.md`(원본 Batch 7H-C1 보고)는 그대로 두고, 이번 보완만 여기 별도로 기록합니다. 새 기능이나 추가 조사는 하지
않았고, 아래 두 결함만 고쳤습니다.

## 1. 두 파일의 수정 전/후 줄바꿈 수

| 파일 | 수정 전 | 수정 후 |
|---|---|---|
| `tcad/device/devsim/solve.py` | CR bytes 134(전체 CRLF), sha `2027a7ba…` | **CR bytes 0**, 134 lines, 파일 끝 LF, BOM 없음, sha `67857f5f…` |
| `tests/integration/test_basic_potential_linear_precision_real.py` | CR bytes 199(전체 CRLF), sha `aa289cae…` | **CR bytes 0**, 208 lines, 파일 끝 LF, BOM 없음, sha `6669858e…` |

두 파일 모두 표준 라이브러리 binary I/O(`CRLF→LF` 치환, 남는 bare CR도 LF로 치환, 마지막에 LF 보장)로 정규화했고,
UTF-8 인코딩과 BOM 없음을 그대로 유지했습니다.

## 2. interior/free-bulk 분류 before/after

**before** (`n_interior = sum(1 for x, y in points if 0.0 < x < L_UM)`): top/bottom boundary node까지 포함하는
"free bulk-equation node" 수였는데 이름이 `n_interior`였습니다 — geometric interior가 아니었습니다.

**after**: 두 개로 명확히 분리했습니다.
```python
n_strict_interior = sum(1 for x, y in points if 0.0 < x < L_UM and 0.0 < y < H_UM)
n_free_bulk = sum(1 for x, y in points if 0.0 < x < L_UM)
assert n_strict_interior >= 1, "fixture must have at least one strict geometric interior node"
```
실측: **n_strict_interior = 2** ((0.6,0.4), (1.5,0.4) um — docstring의 "2 interior nodes"와 정확히 일치),
**n_free_bulk = 6**. matrix 검사 loop(§7의 `x[i] in (0.0, L_UM)` 제외 로직)는 원래부터 free-bulk 기준으로 동작하고
있었으므로 그대로 유지했습니다(수치 tolerance/geometry/matrix assertion 무변경).

사용되지 않던 `row_of_eqn = {int(e): i for i, e in enumerate(eqn)}` 줄도 삭제했습니다.

## 3. 실제 semantic diff

`solve.py`의 clean-env semantic diff(§6)는 이전 Batch 7H-C1의 diff와 **완전히 동일**합니다(flux 식 2곳 +
docstring 정정, LF 정규화는 diff에 전혀 나타나지 않음 — 정규화 전부터 CRLF였기 때문에 git이 이미 CRLF 상태를
"현재 워킹트리"로 비교 기준 삼고 있었고, 순수 줄바꿈 문자만 바뀌는 git diff는 라인 전체가 동일 문자열이면 diff로
나타나지 않습니다. 실제로 아래 §6에서 확인하듯 diff 내용은 0글자 변화입니다).

`test_basic_potential_linear_precision_real.py`의 diff(신규 미추적 파일이라 `git diff`엔 안 잡히지만, 직접 비교):
- `n_interior` → `n_strict_interior`/`n_free_bulk` 분리 및 관련 주석 추가
- print 문에 두 숫자 이름 명시
- `row_of_eqn` 삭제
- (파일 전체가 LF로 재기록됐지만 텍스트 내용 변경은 위 항목뿐)

## 4. 두 테스트 결과 (direct script 실행)

**`test_basic_potential_linear_precision_real.py`** — RC=0:
```
[fixture] 12 nodes, 2 strict interior, 6 free bulk-equation -- {'num_nodes': 12, 'potential_min': 0.0, 'potential_max': 1.0}
[A] Linf=0.000000e+00 V  L2=0.000000e+00 V  (tolerance 1.0e-09 V)
[C/D] 20 interior directed-edge matrix rows checked: all match EdgeCouple/EdgeLength, none match EdgeCouple**2 (tolerance 1.0e-09 rel)

BASIC POTENTIAL LINEAR-PRECISION TEST PASSED (real DevSim, real assembled matrix)
```

**`test_phase5_devsim_real.py`** — RC=0:
```
[3/4] DevSim import OK -> regions=['Mask', 'Si'] contacts=['Si_xmin', 'Si_xmax']
number of equations 550
[4/4] DevSim solve OK -> {'num_nodes': 550, 'potential_min': 0.0, 'potential_max': 1.0}
PHASE 5 FULL PIPELINE (...) RAN AGAINST REAL VIENNAPS 4.6.2 + DEVSIM 2.10.1 SUCCESSFULLY
```

## 5. matrix/analytic 수치
| 항목 | 값 |
|---|---|
| strict interior node 수 | **2** |
| free bulk-equation node 수 | **6** |
| L∞ | **0.000000e+00 V** |
| L2 | **0.000000e+00 V** |
| matrix checked row 수 | **20** |
| EdgeCouple/EdgeLength 일치 | 20/20 (rel tol 1e-9) |
| EdgeCouple² 불일치 | 20/20 (전부 불일치 확인) |

## 6. clean-env git diff --check
```
$ GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 git -c core.autocrlf=false diff --check -- tcad/device/devsim/solve.py tests/integration/test_basic_potential_linear_precision_real.py
(출력 없음)
$ echo $?
0
```
`solve.py`가 **전체 파일 교체가 아니라 실제 semantic diff만** 보이는지 `git diff`(같은 clean env)로 재확인했고,
§3에 인용한 flux 식 2곳 + docstring 정정 외에는 아무 변화도 없습니다. "기존부터 CRLF였다"는 설명으로 RC=2를
허용하지 않았고, 대상 파일을 실제로 LF로 정리해 **RC=0을 만들었습니다**(이전 배치의 RC=2 → 이번 RC=0).

일반 config도 RC=0입니다(`git diff --check` 경고만 출력, "LF will be replaced by CRLF the next time Git
touches it" — 이는 사용자 전역 `core.autocrlf=true`가 다음 checkout/add 시 재변환할 것이라는 경고일 뿐, 실제
whitespace 오류가 아닙니다).

**부가 확인**: 전체 저장소에 대한 두 config의 `git diff --check`도 모두 **RC=0**이었습니다(`data/lf_fix_after_state.txt`) — `solve.py`가 clean-env RC=2의 유일한 원인이었음을 재확인했습니다.

## 7. 다른 파일 변화 0
```
$ git status --porcelain -- tcad tests tcad_2d_stagewise.py | grep -E "solve.py|test_basic_potential_linear_precision"
 M tcad/device/devsim/solve.py
?? tests/integration/test_basic_potential_linear_precision_real.py
```
이 두 파일 외에 이번 세션에서 바뀐 `tcad/`·`tests/` 파일은 없습니다(narrow-scope dirty count 110 = 이전
Batch 7H-C1 종료 시점의 108개 기존 dirty + 이 2개). 신규 감사 데이터도 `docs/audits/2026-09-23-batch7h-c1-double-edgecouple-fix/`에만 추가했습니다(`data/lf_fix_before_state.txt`, `data/lf_fix_after_state.txt`, `data/lf_fix_test1_run.log`, `data/lf_fix_test2_run.log`, 이 문서, 갱신된 `SHA256SUMS.txt`).

## 8. HEAD/staged/commit
HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`는 그대로입니다. staged 0, 커밋 0이며 전체 회귀는 실행하지
않았습니다.

## 9. gate 유지
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`는 이번 보완에서도 전혀 건드리지 않았습니다.

커밋과 전체 회귀는 하지 않았습니다. Codex 검토를 기다립니다.
