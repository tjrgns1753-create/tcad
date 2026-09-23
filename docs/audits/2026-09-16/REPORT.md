# TCAD 물리 타당성 실행 감사 — 2026-09-16

## 판정과 범위

현재 버전을 “모든 공정 순서에서 실제 물리 현상과 일치한다”고 승인할 수 없다. 실제 GUI/ViennaPS/DevSim 경로의 미지원 상태 우회, 격자에 종속된 초기 산화막 생성, 상태 전달 계층의 농도·이력 오류를 재현했다. 아래는 코드 수정 요청이 아닌 실행 감사 결과이다. Production 및 기존 테스트 assertion은 변경하지 않았다.

최종 집계(2026-09-17 확인): **120개 파일 중 91 PASS / 29 FAIL / timeout 0 / skip 0**. Unit 44/44 PASS, integration 47 PASS / 29 FAIL이다. [전체 실행 결과와 개별 로그](RESULTS.md)를 확인할 수 있다. 29 FAIL을 곧바로 29개 물리 오류로 해석하면 안 된다. 미지원 상태의 정상 차단, API/자료형 호환 문제, assertion 불일치가 섞여 있으며, 아래 8개 문제는 별도 반례로 재현하여 구분했다.

기존 테스트 파일 전체를 발견하여 순차 실행했다. 파일별 결과와 전체 로그는 `validated-env/results.json`, `validated-env/*.log`에 있다. Unit 예산 60초, integration 예산 180초를 적용한 **시간 제한 감사**이다. 프로젝트의 900–5400초 정식 회귀 예산과 다르므로 timeout은 실패나 hang의 증거가 아니다. 무한한 공정 순서·연속 파라미터 전체의 검증은 아니며, 개별 제작 논문의 소자 실측곡선 재현까지 완료했다는 뜻도 아니다.

환경: ViennaPS 4.6.2, DevSim 2.11.0, NumPy 2.4.6, meshio 5.3.5. `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`. 실제 설치된 `../.venv/Library/bin`을 PATH에 추가하고 `DEVSIM_MATH_LIBS=mkl_rt.3.dll`로 실행했다. 처음 DLL 전체 경로로 실행한 시도는 access violation을 일으켜 종료했으며, 그 로그는 상위 감사 폴더에만 남겼다. **집계에는 validated-env 결과만 사용한다.**

검사 대상은 HEAD `3ba940404fd19c88eaaccc96a39ffe8444fb8851`에 미커밋 WaferState v2 변경이 올라간 working tree이다. HEAD만 별도 실행한 대조군은 없으므로 모든 실패를 신규 회귀나 기존 baseline으로 단정하지 않았다. 파일 안의 첫 assertion 실패 이후 사례들은 실행되지 않는다. 120개 파일 시도와 각 파일 내부의 모든 사례 완주는 구별해야 한다.

## A. 실제 backend/GUI에서 재현한 문제

### A1 — P0: 미지원 anneal 상태를 Implant Windows 측정이 우회한다

재현: 4 µm × 1 µm Si, grid 0.2 µm, Implant Windows의 background/source/drain donor를 각각 1e16 cm^-3, acceptor를 0으로 설정했다. 실제 GUI 도핑 handler와 900°C/600초 anneal handler를 실행한 뒤 0.01 V 측정을 실행했다. 이 조합은 handler 연결을 확인하기 위한 진단 입력이지, 실제 implant 조건으로 보정된 소자가 아니다.

- 측정 직전 canonical state: `net_doping=None`, `UNSUPPORTED_BY_MODEL`, active attachment 0개.
- 실제 `devsim.solve()` 호출: **7회**. 관찰 wrapper는 호출 횟수만 기록하고 원래 solver를 그대로 실행했다.
- GUI 표시: `I = 2.662641e-03 A`. 계산 후에도 canonical state의 농도는 `None`.
- 원인: `tcad_2d_stagewise.py:4890`의 robust branch는 `WaferStateV2`를 검증하지 않고 `doped_result.doping`을 직접 넘긴다. 일반 `apply_doping()` 경로의 안전장치가 적용되지 않는다.
- 영향: 미지원 결과를 숫자로 표시하며, 앞서 누적한 다른 도핑도 latest profile만 사용하는 경로에서 빠질 수 있다. 로그로 누락 사실을 알리는 것만으로 상태와 solver의 불일치가 해결되지는 않는다.
- 수정 기준: 모든 측정 진입점에 동일한 state 검증을 적용하고, continuation에서도 canonical active doping을 보존해야 한다. 미지원 상태에서는 node write/solver 호출 모두 0회여야 한다.

증거: `counterexample_gui.json`, `gui_measurement_full.log`, `counterexample_gui_stdout.log`.

전류 단위 주의: 이 프로젝트의 `CURRENT_CONVENTION_NOTE`에 따르면 2D 결과는 out-of-plane 1 cm 기준이다. GUI는 실제 폭 환산 없이 `A`로 표시한다. 따라서 위 수치를 실제 1 µm 폭 소자의 총전류로 해석하면 안 된다. 이 표시 문제는 상태 우회 문제와 별개이다.

### A2 — P0: 산화 초기조건이 mesh 크기에 따라 달라진다

동일한 새 Si 구조, Dry/1000°C, 0시간 또는 0.01시간을 실제 `ThermalOxidation.run()`으로 실행하여 volume mesh의 Si/SiO2 경계를 읽었다.

| Grid (µm) | 0시간 산화막 (nm) | 0.01시간 산화막 (nm) |
|---:|---:|---:|
| 0.10 | 99.5025 | 99.6902 |
| 0.05 | 49.7512 | 49.9954 |
| 0.02 | 19.9005 | 20.2143 |

원인: `tcad/process/oxidation/thermal.py:90`의 `setInitialOxideThickness(max(0.002, grid_delta_um))`. 수치해석을 안정화하려고 격자 한 칸 두께를 실제 초기 산화막으로 넣는다. 따라서 격자 변경이 동일 물리 문제의 정밀도 변경이 아니라 **초기 wafer 자체의 변경**이 된다. 0시간에도 초기 mesh에 없던 산화막이 생긴다. 작은 양의 Si top 이동도 관측했으나 이는 표면 추출/재구성 오차와 분리하지 않았으므로 별도 Si 생성 결함으로 판정하지 않았다.

Deal–Grove의 초기 두께는 물리적 초기조건이며 시간 적분에 들어간다. mesh 폭을 초기 두께로 대체하는 근거는 그 논문에 없다. 기존 stoichiometry test는 이 seed를 빼고 성장분만 검사하므로 통과해도 본 문제를 검출하지 못한다. [Deal–Grove 논문 재수록, 이론 및 초기조건](https://www.columbia.edu/~leonard/TISSSite/mvbd.html)

수정 기준: 실제 초기 산화막 두께를 입력/상태로 고정하고 grid만 변화시켜 수렴성을 확인해야 한다. 얇은 막을 backend가 표현하지 못하면 이를 표시해야 한다.

증거: `counterexample_oxidation.json`, `counterexample_oxidation_stdout.log`.

## B. Production 상태 함수를 직접 실행해 재현한 문제

다음은 실제 production 함수를 실행한 반례이나 ViennaPS가 해당 transform을 생성했다는 증거는 아니다. 명시적 rectangle transform을 입력하여 상태 전달 계약을 검사했다. 이 구분은 중요하다.

### B1 — P0: chemical/unknown 도핑을 electrical active 도핑으로 사용

같은 B attachment에 `chemical_state`만 `CHEMICAL`, `UNKNOWN`, `ACTIVE`로 바꾸어 조회했더니 세 경우 모두 `net=-1e18 cm^-3`, status 없음이었다. `wafer_state_v2.py:320`의 합산은 chemical_state를 검사하지 않는다. `attach_dopant()` 기본값도 `CHEMICAL`이다.

주입된 chemical concentration과 전기적 활성 농도는 일반적으로 동일하지 않다. 실리콘의 B implant anneal 모델 연구는 inactive cluster와 활성화 거동을 별도로 다룬다. [Chakravarthi & Dunham, SISPAD 2000](https://in4.iue.tuwien.ac.at/pdfs/sispad2000/00871234.pdf)

수정 기준: 사용자 지정 **활성 농도 초기조건**과 **주입된 chemical 농도**를 구분한다. `UNKNOWN`은 활성화 모델 없이 electrical query에 사용하지 않아야 한다. 완전 활성화/이온화 근사를 쓰는 경우도 명시적인 모델 조건이 필요하다.

### B2 — P0: 식각 분할 경계에서 농도가 두 배

Si `[-2,2]×[-2,0]`, uniform donor `1e17`에서 표면에 열린 trench `[-0.5,0.5]×[-1.5,0]`를 제거했다. 남은 같은 재료 내부의 인공 분할선에서:

| 조회점 (µm) | NetDoping (cm^-3) |
|---|---:|
| (-1, -1.500001) | 1e17 |
| (-1, -1.500000) | **2e17** |
| (-1, -1.499999) | 1e17 |

`rect_subtract()`로 만든 attachment들은 경계가 맞닿는다. `_point_in()`이 양끝을 포함하고 query가 모든 attachment를 합산하여 경계가 중복된다. 면적이 0인 경계라 inventory conservation 시험은 통과하지만 실제 mesh node에 잘못된 농도를 줄 수 있다.

수정 기준: 같은 원래 attachment의 분할 조각은 경계에서도 한 번만 기여해야 한다. 독립적인 두 도핑 application의 정상 합산과 구별해야 한다.

### B3 — P1: 겹치는 재증착을 허용하여 기존 농도가 0으로 바뀜

기존 Si `[-2,2]×[-2,0]`에 새 Si instance `[-1,1]×[-1.5,0.5]`를 deposition transform으로 추가했다. 양의 면적이 겹치지만 transform이 통과하여 두 ACTIVE cell이 동시에 존재했다. 기존 기판의 `(0,-1)` 농도는 `1e17 → 0`, status 없음으로 바뀌었다.

`_deposition_error()`는 ID/양의 면적은 검사하지만 기존 material 및 신규 cell 사이의 overlap을 검사하지 않는다. query는 top이 높은 새 cell을 선택한다. 이 반례는 잘못된 transform 입력에 대한 방어 결함이며, 실제 ViennaPS가 이런 transform을 생성했다는 주장은 아니다.

수정 기준: overlapping physical occupancy를 거부하거나 명시적인 material replacement로 처리하고 제거/추가 inventory를 기록해야 한다.

### B4 — P1: 같은 식각을 반복하면 provenance ID와 제거량 귀속 충돌

두 번의 etch에서 같은 `step_seed="etching"`을 사용했다. 제거 영역은 서로 다르지만 두 이벤트가 모두 `evt:etching:1`이 되었다. 각 영역의 기대 제거량은 `1e9 cm^-1`인데 첫 이벤트에 `2e9`, 두 번째에는 `None`이 기록됐다. 전체 event 4개 중 unique ID는 3개였다.

원인: `advance()`마다 `_IdGen(step_seed)`를 새로 만들며, inventory 업데이트는 ID가 같은 첫 event를 찾는다. 일반 caller도 category를 step_seed로 사용하므로 반복 공정을 구분할 수 있는 ID 계약이 필요하다.

수정 기준: state 이력 안에서 event/cell/attachment ID의 유일성을 보장하고, 반복 공정의 개별 제거량과 provenance를 별도로 검사한다.

### B5 — P1: barrier의 물리 지원 여부를 rectangle 개수로 판정

동일한 background `1e17`와 신규 application `5e18`에 대해 폭 1 µm barrier를 이동했다.

- 가장자리 `[-2,-1]`: 숫자를 허용. 아래에는 background만 `1e17`, 열린 위치에는 `5.1e18`, status 없음.
- 중앙 `[-0.5,0.5]`: 신규 application이 미지원 처리되고 조회가 `None`.

원인: `_carve_support_around_barrier()`는 남는 rectangle이 정확히 하나일 때만 numeric application을 허용한다. 이는 geometry 표현 제약이지 implant 차폐의 구성방정식이 아니다. 현재 경로에는 ion energy/species-dependent stopping 및 oxide thickness에 따른 투과 계산이 없다. SiO2를 통과하는 주입은 실제 모델링 대상이며, 마스크를 가장자리로 옮겼다는 이유만으로 차폐를 정확히 안다고 할 수 없다. [Hoessinger, implantation energy](https://www.iue.tuwien.ac.at/phd/hoessinger/node22.html), [15 nm SiO2를 통과하는 70 keV B 사례](https://www.iue.tuwien.ac.at/phd/hoessinger/node68.html)

수정 기준: 명시적 ideal hard-mask 프로파일 입력과 실제 oxide-through-implant 예측을 구분한다. 실제 implant 모델이 미지원이면 rectangle 하나인 경우도 동일하게 표시한다. 새 application의 불확실성과 기존 background를 별도로 보존한다.

### B6 — P1: v2 conversion의 SiO2 부피는 소비된 Si 부피와 1:1

두께 0.3 µm, 폭 4 µm Si를 conversion하면 소비 면적과 생성 SiO2 면적이 모두 **1.2 µm²**이고 새 oxide bounds는 소비된 Si bounds와 완전히 같다. 코드가 `material="SiO2", bounds_um=piece`를 생성한다.

순수한 평면 열산화라면 밀도/몰부피에 따른 팽창을 반영해야 하며, Si 소비/oxide 성장 약 0.44를 쓰면 oxide 두께는 약 0.682 µm여야 한다. [Radi, Oxidation 및 몰부피 비율](https://www.iue.tuwien.ac.at/diss/radi/diss/node21.html) 현재 event는 dopant redistribution을 UNSUPPORTED라고 표시하지만 새 oxide cell은 ACTIVE+MODELLED geometry로 노출된다. 이는 현재 core의 bookkeeping 한계이며, ViennaPS 실제 산화가 부피비 1을 사용한다는 뜻은 아니다.

수정 기준: consumed Si와 produced oxide extent를 각각 명시적으로 전달하거나, oxide geometry를 확정할 수 없으면 MODELLED material cell을 만들지 않는다. 실제 산화의 확산·편석까지 고려하지 않은 상태에서 남은 Si의 농도가 항상 그대로라고 주장해서도 안 된다.

B 항목 증거: `counterexample_state.json`, 재현 스크립트의 `state_checks()`.

## C. 실제 계산에서 정상 확인한 범위

- `test_physics_references_real.py`: 성장분의 Si 소비/oxide 비율은 0.5/1/2시간에서 각각 0.434/0.437/0.439. 반시간 두 번 대 한시간 한 번의 두께 차이는 0.39%. 이는 seed 문제 및 dopant segregation을 검증하지 않는다.
- `test_etch_selectivity_real.py`: 지정한 material rate와 선택비를 backend가 적용함을 통과. 입력 rate 자체의 실험 보정까지 입증한 것은 아니다.
- `test_order_independence_real.py`: 해당 파일에 정의된 순서 실행 사례 통과. 모든 순열에 대한 완전성 증명은 아니다.
- 별도 실제 PN probe: Na=Nd=1e16 cm^-3, 300 K, 4×2 µm, grid 0.2/0.1/0.05 µm에서 시행. 접합 주변 추가 refinement 포함. cm 변환 `1e-4`를 적용했다.

| Grid (µm) | Nodes | 평형 barrier (V) | 순방향 VA=+0.2 V, 전류 절대값 (A/cm) | 역방향 VA=-0.2 V, 전류 절대값 (A/cm) |
|---:|---:|---:|---:|---:|
| 0.20 | 2,921 | 0.71528958 | 2.063377e-9 | 7.757790e-11 |
| 0.10 | 11,391 | 0.71528958 | 2.038954e-9 | 7.592589e-11 |
| 0.05 | 44,781 | 0.71528958 | 2.054698e-9 | 7.738644e-11 |

바이어스는 p-contact를 0 V에 두고 n-contact를 움직였으므로 `VA=-Vn`이다. 해석적 `Vbi=Vt ln(Na Nd / ni²)`는 solver의 material parameter를 사용하면 0.71528958 V이다. 순방향/역방향 barrier는 각각 약 0.51529/0.91529 V. 유한 바이어스에서 양단 KCL 상대오차는 최악 약 1.8e-6이다. 0 V 전류는 절대값 약 1e-17 A/cm 이하로, 이 값에 대한 상대 KCL 비율은 유효한 오차 척도가 아니다.

이 세 grid의 전류 차이는 대략 2.2% 이내이나 비단조적이므로 엄밀한 mesh convergence order나 실험 전류 일치를 입증하지 않는다. 별도 저장한 W-charge는 비정렬 node들을 x별로 평균해 적분한 진단 proxy로, analytic sharp depletion width와 동일한 측정량이 아니며 수치도 안정적이지 않다. **공핍폭 절대값 검증은 완료하지 않았다.** barrier/전류 방향성과 공핍 전하 변화 방향만 확인했다.

증거: `counterexample_diode.json`, `counterexample_diode_stdout.log`.

## D. 미지원 범위와 모델 보정 문제

- 실제 곡면 공정 이후 정확한 transform이 없는 대부분의 state 전달은 fail-closed이다. 이는 잘못된 숫자를 내지 않는 보호 동작이지만, 연속 공정의 물리 구현 완료로 볼 수 없다.
- GUI anneal은 현재 diffusion/activation을 계산하지 않고 미지원 처리한다. 예전 x-only Gaussian broadening 함수의 시험 PASS는 현재 GUI에서 실제 diffusion이 작동한다는 증거가 아니다.
- Gaussian/step/window adapters는 x-only다. 실제 깊이 방향 implant profile, species/energy/dose 및 damage/activation을 재현하는 모델과 구분해야 한다.
- `semiconductor_equation.py:126`의 electron/hole lifetime은 모두 1e-8 s로 고정되며 주석의 근거는 예제와 수렴성이다. 해당 제작 공정의 측정 수명/결함 모델로 보정한 값이라는 증거는 없다. 따라서 절대 누설전류·재결합전류를 특정 제작 논문의 실측값과 일치한다고 승인할 수 없다.
- Phase 2/3의 전체 등록 식각/증착 모델 시험은 주로 API 실행과 mesh/snapshot 파일 생성을 검사한다. PASS가 해당 화학 조건의 실험 식각속도, 증착률, 선택비, 조성까지 논문과 일치한다는 뜻은 아니다. `INTERACTION_COEFFICIENTS`에는 현재 B/P intrinsic diffusivity의 네 파라미터만 문헌 수치로 등록돼 있다. backend 자체 모델의 출처와 별도로, 이 프로젝트 recipe의 조건별 보정 근거가 더 필요하다.
- 원자 수의 closed-form inventory가 정확하다는 사실만으로 constitutive model이 정확해지지 않는다. 반대로 실제 TCAD의 보존적 수치적분은 오차·수렴성을 검증해 사용할 수 있다. 현재 exact-rectangle-only 계약은 구현상의 제한이며 물리 법칙 자체의 요구는 아니다.

## 재현

프로젝트 root에서:

```powershell
$env:PYTHONIOENCODING='utf-8'
..\.venv\Scripts\python.exe -u docs/audits/2026-09-16/run_audit.py
..\.venv\Scripts\python.exe -u docs/audits/2026-09-16/counterexamples.py state
..\.venv\Scripts\python.exe -u docs/audits/2026-09-16/counterexamples.py oxidation
..\.venv\Scripts\python.exe -u docs/audits/2026-09-16/counterexamples.py gui
..\.venv\Scripts\python.exe -u docs/audits/2026-09-16/counterexamples.py diode
```

동시에 동일 회귀를 중복 실행하지 않는다. 각 script는 환경 설정을 자체 적용한다. 이 감사의 수정 우선순위는 A1/B1/B2 → A2 → B3/B4/B5/B6 → production caller 연결 및 논문별 보정이다. 미지원 assertion으로 기존 물리 계산 시험을 전부 대체해 녹색으로 만드는 것은 완료 기준이 아니다.
