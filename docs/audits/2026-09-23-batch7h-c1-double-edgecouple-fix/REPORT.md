# Batch 7H-C1: remove the double-EdgeCouple bug in run_basic_potential_solve

Branch `claude/waferstate-v2`, HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851` throughout (unchanged, nothing
staged, not committed). One production file changed
(`tcad/device/devsim/solve.py`), one new test file added
(`tests/integration/test_basic_potential_linear_precision_real.py`). No other `tcad/`/`tests/` file touched;
all 132 pre-existing dirty files preserved unmodified.

**Verdict: `MINIMAL_LAPLACE_SKELETON_DOUBLE_WEIGHTING_FIXED`.**

This does NOT mean "all DevSim flux problems are solved", "PN/DD is verified", "signed override is approved
for production", or "mesh convergence is confirmed" — none of those are claimed. The gate
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED` is unchanged.

## 1. 시작 상태
- HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`, branch `claude/waferstate-v2`, staged 0.
- `git status --short`: 132 pre-existing dirty entries (unchanged from before this batch).
- 실행 중인 python 프로세스: Serena MCP와 그 language server뿐(명령줄로 확인, regression/test 프로세스 없음).
- 허용 파일의 시작 SHA-256 (`data/start_hashes_allowed_files.txt`):
  - `tcad/device/devsim/solve.py` = `c58ba404572858e1bb7c0aa33555ca442fa238b32a26016370872ef798e0440c`
  - `tests/integration/test_phase5_devsim_real.py` = `80c2bf2e821958dc1be1115be2a255efdb46d7646dd3ccd937577fdb6b92d592`
- `data/start_state.txt`에 `git status --short` 전문과 최초 `git diff --check` (일반 config, RC=0)을 기록.

## 2. CLAUDE.md / Serena 조사 결과
repo-root `CLAUDE.md` 하나만 적용됩니다.

`mcp__plugin_serena_serena__activate_project(tcad)` 재활성화 후:
- `find_symbol("run_basic_potential_solve", "tcad/device/devsim/solve.py")` → [solve.py:59-119](tcad/device/devsim/solve.py:59) (수정 전 본문 전체를 읽음, 버그 코드 라인 확인: `CreateEdgeModel(..., "(Potential@n0-Potential@n1)*EdgeCouple")` at what was line 80/82-83).
- `find_referencing_symbols("run_basic_potential_solve", "tcad/device/devsim/solve.py")` → **정확히 한 곳**: [tests/integration/test_phase5_devsim_real.py:72-77](tests/integration/test_phase5_devsim_real.py:72) (`solve_result = run_basic_potential_solve(...)`).
- `rg`로 재확인(fallback 아님, 교차검증): `grep -r "run_basic_potential_solve"` → 4개 파일 매치. production/test caller는 `test_phase5_devsim_real.py`뿐이고, 나머지 2건은 이 batch가 새로 만든 `docs/audits/2026-09-23-batch7h-c-flux-discretization/scripts/prod_solve_check.py`(이전 배치의 read-only 감사 스크립트, production caller 아님)와 `solve.py` 자기 자신입니다. **Serena와 rg가 완전히 일치**했습니다.
- Serena 실패 없음, fallback 사용 안 함.

## 3. 수정 전 false-green 재현 결과
[test_basic_potential_linear_precision_real.py](tests/integration/test_basic_potential_linear_precision_real.py)를 **production 수정 전에** 작성해 원본 `solve.py`(hash `c58ba404…`)로 실행했습니다.

```
[fixture] 12 nodes, 6 interior -- {'num_nodes': 12, 'potential_min': 0.0, 'potential_max': 1.0}
[A] Linf=8.333333e-02 V  L2=4.487637e-02 V  (tolerance 1.0e-09 V)
AssertionError: node 1 at x=0.600000 um: Potential=0.3333333333333333 V, analytic=0.3 V,
error=3.333333e-02 V exceeds tolerance 1.0e-09 V -- this is the linear-precision failure
mode of the double-EdgeCouple bug
```
**RC=1** (`data/pre_fix_run.log`). 실패 사유는 요구된 세 가지 중 하나인 **potential L∞ error**입니다(3.33e-2 V, 사전 tolerance 1e-9 V보다 훨씬 큼). fixture가 우연히 false-green을 만들지 않음을 확인했습니다.

## 4. production before/after diff
`git diff -- tcad/device/devsim/solve.py` (일반 git config, autocrlf=true, 의미론적 diff): **21 insertions, 7 deletions**.

```diff
-Real API used (verified against installed DevSim 2.10.1). The
-derivative-model naming convention below ("{model}:{variable}@n0" for
-edges, a plain "1" for a linear contact residual) is not invented —
+Real API used, per DevSim's own public equation-assembly contract
+(devsim.net's "Equation and models" manual page): a bulk `edge_model`
+passed to `devsim.equation()` is integrated by DevSim itself against
+`EdgeCouple` ("the length of the perpendicular bisector of an element
+edge") during assembly — so the edge model string must define only the
+flux/field density (e.g. a gradient term), never multiply by
+`EdgeCouple` itself, or the couple gets applied twice, corrupting the
+assembled matrix coefficient (confirmed directly by reading the
+assembled matrix via `devsim.get_matrix_and_rhs()`: multiplying by
+`EdgeCouple` inside the edge model produces a coefficient of
+`EdgeCouple**2` instead of the correct `EdgeCouple/EdgeLength`; see
+docs/audits/2026-09-23-batch7h-c-flux-discretization/REPORT.md and the
+regression test this fixed,
+tests/integration/test_basic_potential_linear_precision_real.py).
+
+The derivative-model naming convention below ("{model}:{variable}@n0"
+for edges, a plain "1" for a linear contact residual) is not invented —
 it is DevSim's own convention, found by reading the source of
 devsim.python_packages.model_create.CreateEdgeModelDerivatives /
 CreateNodeModelDerivative (used by DevSim's bundled diode examples,
@@ -30,9 +44,9 @@ isolate a real equation-setup mistake from an environment problem):
     )
     CreateSolution(device, region, "Potential")
     CreateEdgeModel(device, region, "PotentialEdgeFlux",
-                     "(Potential@n0-Potential@n1)*EdgeCouple")
+                     "(Potential@n0-Potential@n1)*EdgeInverseLength")
     CreateEdgeModelDerivatives(device, region, "PotentialEdgeFlux",
-                                "(Potential@n0-Potential@n1)*EdgeCouple",
+                                "(Potential@n0-Potential@n1)*EdgeInverseLength",
                                 "Potential")
     devsim.equation(device=, region=, name=, variable_name="Potential",
                      edge_model="PotentialEdgeFlux")
@@ -77,10 +91,10 @@ def run_basic_potential_solve(
     )

     CreateSolution(device, region, "Potential")
-    CreateEdgeModel(device, region, "PotentialEdgeFlux", "(Potential@n0-Potential@n1)*EdgeCouple")
+    CreateEdgeModel(device, region, "PotentialEdgeFlux", "(Potential@n0-Potential@n1)*EdgeInverseLength")
     CreateEdgeModelDerivatives(
         device, region, "PotentialEdgeFlux",
-        "(Potential@n0-Potential@n1)*EdgeCouple", "Potential",
+        "(Potential@n0-Potential@n1)*EdgeInverseLength", "Potential",
     )
```
**실제 수정은 단 두 줄**([solve.py:94, :97](tcad/device/devsim/solve.py:94)의 문자열 `*EdgeCouple` → `*EdgeInverseLength`). 함수 반환 API, fallback, mesh별 분기, signed override는 추가하지 않았습니다.

## 5. docstring 정정 내용
- **모듈 docstring 예제식** ([solve.py:32-36](tcad/device/devsim/solve.py:32) 옛 줄번호): `*EdgeCouple` → `*EdgeInverseLength`로 정정.
- **"verified against installed DevSim 2.10.1" 제거**: 특정 버전을 하드코딩하지 않고 "DevSim's own public equation-assembly contract (devsim.net's 'Equation and models' manual page)"로 대체.
- **이중 적용 경고 추가**: edge model은 flux/field density만 정의해야 하고, DEVSIM equation assembly가 EdgeCouple을 적용하므로 식 안에서 EdgeCouple을 다시 곱하면 이중 가중이 된다는 것, `get_matrix_and_rhs()`로 직접 확인한 실증(EdgeCouple² vs EdgeCouple/EdgeLength)을 명시하고 7H-C 감사 보고서와 이번 신규 테스트를 인용했습니다.

## 6. 신규 테스트 fixture와 analytic solution
[test_basic_potential_linear_precision_real.py](tests/integration/test_basic_potential_linear_precision_real.py):
- **fixture**: `create_gmsh_mesh`/`add_gmsh_region`/`add_gmsh_contact` 공개 API로 직접 만든 2×1 um 직사각형 단일 region. x-column 4개(0, 0.6, 1.5, 2.0 — 불균일), y-row 3개(0, 0.4, 1.0 — 불균일), 각 cell을 왼쪽아래→오른쪽위 대각선 하나로 2개 삼각형으로 분할 — **이 분할은 rectangle의 종횡비와 무관하게 항상 직각 1개+예각 2개**이므로 obtuse가 절대 생기지 않습니다. 12 node, 12 triangle, interior node 6개((0.6,0.4), (1.5,0.4) 등).
- **해석해**: Potential(x,y) = x/2 (V), left(x=0)=0V, right(x=2)=1V, 상하는 명시적 Dirichlet 없음(natural zero-normal-flux).
- **tolerance**: `EXACT_V=1e-9 V`, `MATRIX_REL_TOL=1e-9`(첫 실행 전 고정, 결과를 보고 조정하지 않음).
- assert A/B: **모든** node(단 2개 min/max가 아니라)가 analytic 값과 tolerance 이내로 일치.
- assert C/D: 공개 `get_matrix_and_rhs(format="csr")`로 읽은 실제 assembled matrix의 interior off-diagonal 계수가 EdgeCouple/EdgeLength와 일치하고, EdgeCouple²과는 불일치.
- assert E: `checked > 0`로 실제로 interior edge row가 검사됐음을 확인(빈 루프로 인한 false-green 방지).

## 7. matrix coefficient 비교
수정 후 실행(`data/post_fix_run.log`):
```
[C/D] 20 interior directed-edge matrix rows checked: all match EdgeCouple/EdgeLength,
none match EdgeCouple**2 (tolerance 1.0e-9 rel)
```
20개 방향성 edge row **전부** `EdgeCouple/EdgeLength`와 상대오차 ≤1e-9로 일치했고, `EdgeCouple²`과는 전부 불일치했습니다.

## 8. 수정 전/후 수치
| | node 수 | interior node | Linf (V) | L2 (V) | matrix vs EdgeCouple/EdgeLength | matrix vs EdgeCouple² |
|---|---|---|---|---|---|---|
| **수정 전** | 12 | 6 | **8.333e-2** (assert 실패, node 1에서) | 4.488e-2 | — | — |
| **수정 후** | 12 | 6 | **0.000e+00** | 0.000e+00 | 20/20 일치(rel ≤1e-9) | 20/20 불일치 |

## 9. 기존 Phase 5 결과
`tests/integration/test_phase5_devsim_real.py`를 수정 후 코드로 재실행: **RC=0**.
```
[3/4] DevSim import OK -> regions=['Mask', 'Si'] contacts=['Si_xmin', 'Si_xmax']
number of equations 550
[4/4] DevSim solve OK -> {'num_nodes': 550, 'potential_min': 0.0, 'potential_max': 1.0}
PHASE 5 FULL PIPELINE (...) RAN AGAINST REAL VIENNAPS 4.6.2 + DEVSIM 2.10.1 SUCCESSFULLY
```
기존 min/max assertion은 그대로 유지했습니다(min=0.0, max=1.0 그대로 통과 — etched geometry에서는 해석적 선형장이 보장되지 않으므로, 지시대로 Phase 5 테스트에 강제로 analytic profile을 요구하지 않았습니다. 정밀 검증은 §6의 신규 결정론적 fixture가 전담합니다).

## 10. control 결과
| control | RC | 비고 |
|---|---|---|
| 7H-C `prod_solve_check.py` (read-only, production 함수를 수정 없이 그대로 호출) M1 | — | matrix `EdgeCouple/EdgeLength` rel=2.2e-16, `EdgeCouple²` rel=5.1e9(불일치), φ=x/L 오차 **1.1e-16 V** |
| 〃 M2 | — | φ 오차 **0.0 V** |
| 〃 M3 (Delaunay+obtuse) | — | matrix는 여전히 `EdgeCouple/EdgeLength`와 일치(이중 적용 버그는 해결됨). φ 오차 **3.29e-2 V** — 이는 **7H-B/7H-C에서 이미 규명된, 이 배치가 건드리지 않는 별개의 obtuse-mesh flux 가중 이슈**입니다. |
| 〃 M4 (강한 obtuse) | — | 같은 이유로 φ 오차 **4.79e-2 V** 잔존 |
| `test_phase6_characterization_real.py` (resistor/Ohmic 경로, `resistor_equation.py` 무수정) | 0 | I-V curve 정상 산출 |
| `test_phase7_doping_real.py` (semiconductor potential-only 최소 테스트) | 1 | **이 배치와 무관한 기존 실패**입니다. `tcad/device/devsim/doping_mapping.py`의 WaferStateV2 canonical-doping fail-closed gate에서 `UnsupportedDopingState`가 발생하며, `solve.py`/`run_basic_potential_solve`에는 도달하지도 않습니다. 이 브랜치에 WaferStateV2 관련 방대한 기존 dirty 변경이 있음을 `git status`로 이미 확인했습니다(§1). |
| `test_wafer_state_v2_devsim_mapping_gate_mock.py` (mock, `python` 직접 실행) | 0 | PASS |
| `test_measurement_canonical_state_gate_real.py` | 0 | PASS (이 테스트는 `run_basic_potential_solve`를 호출하지 않는 별도 robust-solve 경로) |

전체 로그: `data/controls_run.log`.

## 11. gate 유지
`STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED`는 이번 배치에서 전혀 건드리지 않았습니다.

## 12. 허용 범위 밖 변경 0 증거
```
$ git status --porcelain -- tcad tests tcad_2d_stagewise.py | grep -v "이전부터 dirty였던 132개"
 M tcad/device/devsim/solve.py
?? tests/integration/test_basic_potential_linear_precision_real.py
```
이번 세션에서 실제로 바뀐 것은 이 2개 파일뿐입니다(§1의 132개 기존 dirty 파일은 그대로). 신규 audit 파일은 전부 `docs/audits/2026-09-23-batch7h-c1-double-edgecouple-fix/`에만 있습니다(`SHA256SUMS.txt`, 6개 데이터 파일).

## 13. git diff --check
**두 config를 모두 실행해 그대로 보고합니다(요약하지 않음).**

일반 git config(사용자 전역 `core.autocrlf=true` 적용, 이 브랜치의 실제 사용 환경):
```
$ git diff --check
(출력 없음)
$ echo $?
0
```

프로젝트 관례의 clean-env config(`GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 git -c core.autocrlf=false diff --check`):
```
tcad/device/devsim/solve.py:1: trailing whitespace.
...(134줄, solve.py의 모든 줄)
$ echo $?
2
```
**직접 조사해 원인을 확정했습니다**: 이 파일의 워킹트리 사본은 **이번 세션이 시작되기 전부터 이미 CRLF**였습니다(`git status --short`엔 안 잡혔지만, `git show HEAD:...|sha256sum` = `edde1c2b…`가 제가 세션 시작 시 기록한 워킹트리 해시 `c58ba404…`와 다름 — 즉 전역 `core.autocrlf=true`가 이미 이 파일을 CRLF로 변환해 두었고, git status는 autocrlf-aware 비교라 이를 dirty로 보지 않았을 뿐입니다). `tcad/mesh/interface.py`(이번 세션에서 손대지 않은 기존 dirty 파일)로 같은 clean-env 명령을 돌리면 0줄 — 즉 이 CRLF 상태는 **solve.py에 이미 있던, 이 배치 이전부터의 환경 조건**이지, 제 수정이 새로 만든 것이 아닙니다. Edit 도구는 기존 줄바꿈 방식을 보존했을 뿐 새로 CRLF를 주입하지 않았습니다.

## 14. HEAD / staged / commit
HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`는 그대로입니다. staged 0, 커밋 0이며 전체 회귀, PN, DD, IV, L4/L5는 실행하지 않았습니다.

## 15. 남은 한계
- **obtuse mesh의 flux 오차는 이 배치의 범위가 아닙니다.** §10의 M3/M4 결과가 보여주듯, 이중 적용 버그를 없애도 obtuse 삼각형이 있는 mesh에서는 여전히 φ 오차가 남습니다(7H-B/7H-C가 이미 규명한 별개 원인). signed override, mesh 개선은 이번에 넣지 않았습니다(지시대로).
- **`test_phase7_doping_real.py`의 기존 실패는 조사·수정하지 않았습니다.** `solve.py`와 무관하며, 범위를 넓히지 말라는 지시에 따랐습니다.
- **PN/DD/IV/L4/L5는 실행하지 않았습니다.**
- **CRLF 상태는 원인을 확정했을 뿐 정리하지 않았습니다.** 파일 전체 줄바꿈 정규화는 이번 배치의 2줄 수정보다 훨씬 넓은 diff가 되므로 하지 않았습니다.

전체 회귀와 커밋은 하지 않았습니다. Codex 검토를 기다립니다.
