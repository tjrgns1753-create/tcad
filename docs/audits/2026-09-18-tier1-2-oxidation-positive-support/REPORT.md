# Tier 1-2 — positive-time oxidation 지원 조건 조사 (Rev.2, 구현 없음)

Scope: 이 라운드는 조사·설계안만. `tcad/` production 코드는 전혀 수정하지
않았다. 이전에 승인된 zero-duration identity 수정(`tcad/process/oxidation/
thermal.py`, `locos.py`, `zero_duration.py`)은 그대로 두었고 되돌리지
않았다. 전체 회귀와 커밋은 실행하지 않았다. **Rev.2는 새 ViennaPS 실행
없이, 기존 raw JSON(out_B/out_C/out_AD/out_D2)만 재분석해 REPORT.md를
정정한 것이다.**

디렉터리: `docs/audits/2026-09-18-tier1-2-oxidation-positive-support/`
(이전 라운드의 `2026-09-18-tier1-2-oxidation-seed/`와 분리).

## Rev.2에서 무엇이 바뀌었나 (P0/P1 수정)

Rev.1은 B matrix(bare-Si + 물리적 seed 0.002um)의 grid=0.001/0.002 결과를
"해상됨"으로 판정했는데, 이는 **whole-process 물질 보존을 보지 않고
Deal-Grove 최종 두께 일치만 봤기 때문에 틀렸다.** 같은 raw JSON을
다시 계산하면:

```
grid=0.001: final_oxide=0.022823um, si_consumed=0.008958um
  whole-process ratio = 0.022823 / 0.008958 = 2.548   (기대 2.27 대비 +12%)
grid=0.002: final_oxide=0.022785um, si_consumed=0.008980um
  whole-process ratio = 0.022785 / 0.008980 = 2.537   (+12%)
```

이 두 case는 **"해상됨"이 아니라 "kinetics는 진행되지만 seed 생성
단계에서 물질을 비보존적으로 무상 생성하므로 bare-Si whole-process
전체는 미지원"**으로 재분류한다. 아래 P0-1/P0-3에서 상세히 다룬다.
D2도 정량 증거에서 정성 반례로 격하했다(P1-1). 판정표(구 8번)와
preflight 계약(구 9번)도 이에 맞춰 수정했다.

## 0. 요약 (Rev.2)

| 질문 | 답 |
|---|---|
| A. solver 실행 전에 지원 여부를 판정할 수 있는가? | **부분적으로만.** grid_delta와 domain-wide material 목록은 신뢰 가능. 위치별(per-location) oxide 두께는 native API가 없고, 이 감사 스크립트가 export+삼각형 교차로 직접 만들어야 했다. LOCOS wrap 여부 지식은 Python 프로세스 메모리에만 있고 `.vpsd` reload 후 소실된다(실측 확인, 변경 없음). |
| B. truly bare Si에 대한 positive-time 산화(native seed 경로)가 지금 ViennaPS 경로에서 지원되는가? | **아니다, 어떤 grid에서도 아니다.** grid=0.001/0.002는 계면이 실제로 진행되지만 seed 생성 자체가 물질을 무상 창조한다(whole-process ratio 2.54~2.55, 기대 2.27 대비 +12%). grid=0.005~0.05는 계면이 아예 안 움직인다. **6개 case 전부 UNSUPPORTED.** |
| C. 명시적으로 실제 Si/SiO2 stack을 구성한 경우는? | **grid ≤ oxide thickness인 6/9 case가 조건부 지원 가능**(ratio 2.27~2.32, Deal-Grove 오차 ≤2.3%) — 단, **이 결론은 검증된 explicit planar geometry에만 적용되고, bare-Si native seed나 임의 형상으로 일반화하지 않는다.** grid>oxide인 3/9 case는 무성장. |
| D. `getMaterialsInDomain()`에 SiO2가 있다는 사실이 지원의 충분조건인가? | **아니다 — 결정적 반례를 실측으로 확인(변경 없음, 승인됨).** domain의 다른 위치(D1/D3: 측방향 절반, D2: 상단 mesa)에는 진짜 SiO2가 있지만, 완전히 별개의 bare Si 표면(D1/D3: 반대쪽 절반, D2: 둘러싸인 trench 바닥)은 **같은 solve 안에서 0.5시간 동안 정확히 0 성장**했다(Si 계면이 소수점까지 전혀 안 움직임, SiO2도 전혀 생성 안 됨) — 솔버는 실제로 substep을 돌며 정상 완료를 보고했다. **HARD capability blocker.** |

## 1. production diff 0건 증명

```
git diff --stat -- tcad/     (positive-time 작업 관련, zero-duration 수정 제외)
```
아래 "12. HEAD와 커밋 없음 확인" 섹션의 실제 명령 출력 참조 — 이번
라운드에서 `tcad/`에 새로 손댄 파일은 없다(zero-duration 관련 기존 변경은
유지, 되돌리지 않음, 이번 라운드가 추가로 만든 변경은 0).

## 2. 실행한 matrix 전체 표

### 2.0 전체 case 집계 (Rev.2 정정)

| | case 수 | 세부 |
|---|---:|---|
| B (bare-Si native seed) | 6 | kinetics 진행되나 whole-process 비보존: 2 (grid=0.001/0.002) / 계면 무성장: 4 (grid=0.005~0.05) / **물리적으로 supported: 0** |
| C (explicit planar oxide) | 9 | supported: 6 (grid≤oxide) / 무성장: 3 (grid>oxide) |
| **B+C 합계** | **15** | |
| grid>oxide(또는 grid>seed) 무성장 실패 합계 | **7** | B 4개 + C 3개 |
| **물리적으로 supported로 인정되는 case** | **6** | **C의 6개 planar case뿐** — B는 0개 |

`growth/consumed ratio 2.27~2.32`는 **C의 supported 6 case와, B의
post-seed(=solver-internal) 관점에만** 적용된다. B의 whole-process
ratio는 2.54~2.55로 별도 표기한다(아래).

### 2.1 B. bare-Si, 물리적 seed 고정 0.002um (grid-floor 우회, `vps.Oxidation`
직접 호출), dry O2, 1000C, 0.5hr, domain 0.3x0.5um, grid별 별도 프로세스

| grid(um) | substeps | 최종 물리 oxide(um) | **whole-process** ratio (final/si_consumed) | **post-seed** ratio ((final−0.002)/si_consumed) | Deal-Grove 오차(최종 두께) | **최종 판정** |
|---:|---:|---:|---:|---:|---:|---|
| 0.001 | 26 | 0.022823 | **2.548** | 2.325 | +2.22% | **UNSUPPORTED** (seed 무상 생성) |
| 0.002 | 13 | 0.022785 | **2.537** | 2.315 | +2.05% | **UNSUPPORTED** (seed 무상 생성, 경계) |
| 0.005 | 5 | 0.001975 | null(소비≈0) | null | -91.15% | **UNSUPPORTED** (무성장) |
| 0.01 | 3 | 0.001950 | null | null | -91.27% | **UNSUPPORTED** (무성장) |
| 0.02 | 2 | 0.001900 | null | null | -91.49% | **UNSUPPORTED** (무성장) |
| 0.05 | 1 | 0.001751 | null | null | -92.16% | **UNSUPPORTED** (무성장) |

**whole-process vs post-seed, 무엇을 판정에 쓰는가**: grid=0.001/0.002는
Deal-Grove 최종 두께 자체는 +2%대로 잘 맞고, seed를 이미 존재하는
초기조건으로 인정한 뒤의 solver 성장(post-seed)도 ratio 2.31~2.33으로
보존적이다. **그러나 사용자가 준 실제 geometry는 bare Si(oxide=0)였다.**
whole-process 관점(`final_oxide / si_consumed`, 진짜 초기 geometry
기준)으로 보면 ratio가 2.55에 가깝고 이론값보다 **약 12% 크다** — seed
생성 단계 자체가 Si를 거의 소비하지 않고(t=0 si_consumed≈0, 이전
라운드에서 이미 확인) oxide를 만들어내기 때문이다. Deal-Grove 최종
두께가 맞는다는 사실은 "x_i=0.002um라는 초기조건의 kinetics가 맞다"는
것만 증명하지, **"bare Si 전체 공정이 물질보존적으로 지원된다"는 것을
증명하지 않는다.** 따라서 이 두 case도 UNSUPPORTED로 판정한다.

**무성장 case의 실측 디테일**: grid=0.005/0.01/0.02(미해상)는 substep이
5/3/2회 **실제로 돌며** CFL이 매번 `max_velocity=0.019785 um/hr`(물리적
으로 올바른 속도)까지 계산했다 — 단순히 "0 substep" 정지가 아니라,
**속도는 맞게 계산되는데 advection이 계면을 사실상 못 움직이는** 더
미묘한 실패 유형이다(raw native log:
`results/out_B/B_grid_0p0050_native.log` 등). 완료 로그는 항상
정상적으로("Oxidation complete", 요청한 hr 그대로) 찍힌다.

**결론: 현재 ViennaPS 경로에서 truly bare Si의 positive-time oxidation은
테스트한 어떤 grid에서도 지원된 것으로 판정하지 않는다.** 사용자가 실제
초기 geometry에 2nm oxide를 명시적으로 넣은 C case와는 절대 합치지
않는다 — 아래 2.2 참조.

### 2.2 C. Si/SiO2를 직접 구성한 explicit planar oxide, 3개 두께 스케일 x 3개
grid, 공통 조건 dry O2/1000C/0.5hr, case별 별도 프로세스

| initial oxide(um) | grid(um) | grid≤oxide? | 최종 oxide(um) | growth/consumed | Deal-Grove 오차 | 판정 |
|---:|---:|---|---:|---:|---:|---|
| 0.002 | 0.001 | 예 | 0.022823 | 2.324 | +2.24% | 해상됨 |
| 0.002 | 0.002 | 예(경계) | 0.022818 | 2.318 | +2.23% | 해상됨 |
| 0.002 | 0.005 | 아니오(2.5x) | 0.001975 | null | -91.15% | **무성장** |
| 0.02 | 0.01 | 예 | 0.038303 | 2.278 | +0.99% | 해상됨 |
| 0.02 | 0.02 | 예(경계) | 0.038556 | 2.286 | +1.77% | 해상됨 |
| 0.02 | 0.05 | 아니오(2.5x) | 0.019751 | null | -47.68% | **무성장** |
| 0.05 | 0.02 | 예 | 0.065271 | 2.289 | +0.52% | 해상됨 |
| 0.05 | 0.05 | 예(경계) | 0.065196 | 2.318 | +0.62% | 해상됨 |
| 0.05 | 0.1 | 아니오(2x) | 0.049502 | null(성장=0 정확히) | -23.33% | **무성장** |

**세 독립적 두께 스케일(0.002/0.02/0.05um, 25배 범위)에서 완전히 같은
패턴이 반복됐다**: grid≤oxide인 6개 case 전부 growth/consumed ratio가
2.27~2.32(물리값 2.27에 근접), Deal-Grove 오차 ≤2.3%. grid>oxide인 3개
case 전부 무성장(-23%~-92% 오차). **이 6개 supported case는 전부
`vps.MakePlane(...)`으로 직접 구성한, 실제 geometry에 존재하는
Si/SiO2 stack이다 — B처럼 솔버가 무에서 만든 seed가 아니다.**

**B(whole-process 2.54~2.55)와 C(2.27~2.32)의 차이는 "미세한 차이"가
아니라 근본적으로 다른 것을 측정한 결과다.** C는 처음부터 실제
geometry에 oxide가 있었으므로 `final/si_consumed`가 곧 물리적으로
의미 있는 전체 공정 보존비다. B는 실제 geometry가 bare(oxide=0)였는데
seed가 Si 소비 없이 생성되므로, 같은 계산식이 "seed 무상 생성 + 그
이후의 보존적 성장"을 섞어 평균 낸 값이 된다 — 그래서 이론값보다
높게 나온다. 두 값을 같은 표에 나란히 놓고 "약간 덜 보존적"이라고
표현하는 것은 부정확하다.

**판정 — 아래로 범위를 제한한다 (Codex 정정 반영)**:
> "명시적으로 사전 존재하는 planar Si/SiO2 geometry인 C matrix에서는,
> 실험한 0.002/0.02/0.05um 두께에 대해 grid≤oxide thickness인 6개
> case가 Deal-Grove 및 물질 보존과 일치했다."

**다음 주장은 금지한다** (Rev.1에서 암묵적으로 넘어갔던 과잉 일반화):
- bare-Si native seed(B)에도 동일 조건이 충분하다는 주장 — **거짓,
  위 2.1에서 실측 반증.**
- 임의의(arbitrary) oxide geometry에도 충분하다는 주장.
- trench, sidewall, 곡면(curve), partial coverage로 일반화하는 주장.
- 이 판정 규칙을 "universal support predicate"라고 부르는 것.

grid == oxide thickness(경계)에서도 C의 3/3 case가 반복 가능하게 정상
성장했다. grid > oxide thickness(2x, 2.5x, 2.5x)에서는 C의 3/3 case
전부 무성장. **1x~2x 사이 구간은 이번 조사에서 샘플링하지 않았다 —
임의의 허용오차나 정확한 임계 비율을 만들지 않는다.** 형상/surface
orientation 정보가 추가로 필요한지: **그렇다.** 이 matrix는 전부
평면(수직 방향 성장만 있는) 구조다 — **D1/D2는 partial coverage와
non-planar geometry를 이 planar C matrix에서 일반화할 수 없음을
보인다. 수직 sidewall 자체의 산화 거동은 이번 조사에서 측정되지
않았으며 UNKNOWN이다.**

## 3. raw JSON/native log 경로

- B: `results/out_B/result_B_grid_0p{0010,0020,0050,0100,0200,0500}.json`,
  `results/out_B/B_grid_0p*_native.log`, `results/out_B/B_matrix_summary.json`
- C: `results/out_C/result_C_oxide0p*_grid0p*.json`,
  `results/out_C/C_*_native.log`, `results/out_C/C_matrix_summary.json`
- A/D1/D3: `results/out_AD/results_AD.json`, `results/out_AD/*/native.log`
- D2: `results/out_D2/results_D2.json`, `results/out_D2/D2_native.log`
- 스크립트: `scripts/measure_common.py`(공용 측정), `scripts/run_case_B.py`,
  `scripts/run_B_matrix.py`, `scripts/run_case_C.py`,
  `scripts/run_C_matrix.py`, `scripts/investigate_AD.py`,
  `scripts/investigate_D2.py`

측정 방식(Item E)은 이전 라운드(Rev.3.1)에서 이미 검토받은 방법을 그대로
재사용했다: `oxide thickness = oxide top(y) − Si top(y)`, 동일 x에서 실제
삼각형 교차로 계산(`_vertical_triangle_interval`), native bbox는 증거로
쓰지 않음. **"LOCOS wrap이 없는 2-material(Si/SiO2) 도메인은 일반
`save_volume_mesh()`로 항상 안전하다"는 Rev.1 주장은 이번 라운드
D2에서 반증됐다(6번 참조)** — B/C/D1의 평면(planar) 구성에서는 (D1의
before oxide-side 단면 포함) 정상적으로 삼각화됐지만, D2의 비평면
(mesa+trench) 2-material 구성에서는 "before" SiO2가 통째로
삼각화되지 않았다. 그래서 B/C/D1 결과의 신뢰성은 유지되지만(모두
평면), "두 재료면 항상 안전하다"는 일반 규칙으로는 더 이상 인용하지
않는다 — 안전함이 확인된 범위는 검증된 planar 구성으로 한정한다.

## 4. Deal-Grove 계산식·입력 계수·실측 오차

모든 case에서 native log에서 직접 파싱: `B=0.010439 um^2/hr,
B/A=0.044911 um/hr` (모든 grid/seed/oxide 조합에서 동일 — T=1000C,
dry O2에만 의존하는 물리 상수이므로 예상대로 불변). `A = B/(B/A) =
0.232437 um`.

```
x_f^2 + A*x_f = x_i^2 + A*x_i + B*t
```

각 case의 x_i(초기 oxide), t=0.5hr을 대입한 예측값과 실측값의 상대오차는
위 2번 표에 전부 기록. **해상된 case는 전부 +0.5%~+2.3% 사이**(항상
예측보다 약간 큼, 방향이 일관됨 — 계통적 편향 가능성이 있으나 이번
라운드에서 원인 분리는 하지 않음), **무성장 case는 전부 -23%~-92%**로
질적으로 뚜렷이 구분된다.

## 5. oxide/Si 보존비 (Rev.2 정정)

위 2.0의 정정된 집계를 그대로 따른다 — **"해상된 9개"라는 표현은
틀렸다.** 정확히는:

- **물리적으로 supported(C의 6개)**: whole-process ratio 2.27~2.32,
  이론값 2.27 대비 최대 +2.4%.
- **B의 2개(grid=0.001/0.002)**: whole-process ratio 2.54~2.55(+12%,
  UNSUPPORTED로 판정), post-seed ratio만 보면 2.31~2.33으로 C와
  비슷하지만 이는 "seed를 공짜로 만든 뒤의 성장"만 골라본 것이므로
  전체 공정의 보존성 증거로 쓰지 않는다.
- **B+C의 나머지 7개(무성장)**: Si 소비가 사실상 0(또는 음수 노이즈)
  이라 비율 자체가 정의되지 않아 `null`로 남겼다 — 임의로 0이나
  무한대로 채우지 않았다.

## 6. 부분 oxide 반례 결과 (D)

### D1: 좌측 절반에만 real oxide(0.02um), 우측 절반은 bare Si (grid=0.01, dry O2/1000C/0.5hr)

```
parsed_native_log: substeps=4, hours_simulated=0.5, native_seed_message=None
  (전역에 이미 SiO2가 있어서 seed 로직 자체가 발동 안 함)

오xide측(x=-0.5): before y=[0.00005, 0.02] -> after y=[-0.0081, 0.0304]
  (실제 성장 확인 -- 솔버는 진짜로 돌았다)

bare측(x=0.5):    before Si y_max=0.0 -> after Si y_max=0.0  (완전히 불변)
                   SiO2 cross-section: before=None, after=None (전혀 생성 안 됨)
```

**결론: 완전히 bare한 Si 표면이, 같은 domain의 다른 곳에 real oxide가
있다는 이유만으로 0.5시간 동안 정확히 0 성장했다. 에러도 경고도 없다.**

### D3: 같은 구성, "다른 곳"의 oxide를 훨씬 두껍게(0.2um)

D1과 동일한 결과(bare측 Si 완전 불변, SiO2 생성 없음) — 두꺼운
oxide로도 결론이 바뀌지 않았다. `results/out_AD/results_AD.json`의
`D3_thick_oxide_elsewhere` 참조.

### D2: 상단 mesa에만 oxide, trench 바닥(둘러싸인 bare Si)은 무처리 — **정성 반례로만 사용 (Rev.2 격하)**

D2의 "before" SiO2 cross-section은 `None`이다(export 실패, 아래 설명) —
**즉 initial mesa oxide thickness를 정량적으로 증명하는 데는 D2를 쓸 수
없다.** D2가 실측으로 뒷받침하는 것은 다음 native/사후 사실뿐이다:

- native material 목록에 SiO2가 존재한다(`domain.getMaterialsInDomain()`,
  export와 무관한 사실).
- solver 이후(post-apply) mesa 쪽 Si는 실제로 소비됐다(before Si
  y_max=0.0 → after Si y_max=-0.00816, 이 AFTER 쪽 export는 정상
  삼각화됨 — before만 실패).
- trench 바닥의 Si는 solver 전후로 완전히 불변이다(y_max=-0.5 →
  -0.5, 변화 없음).
- trench 바닥에는 solver 이후에도 SiO2가 생기지 않았다(after
  cross-section도 `None`).

이것들을 종합하면 D2는 **"mesa는 성장하고 같은 solve 안의 둘러싸인
bare 영역(trench 바닥)은 전혀 성장하지 않는다"는 D1/D3의 결론을
다른 geometry(측방향 인접이 아니라 완전히 둘러싸인 형태)에서 보강하는
정성 반례**로만 분류한다 — mesa의 정확한 초기/최종 oxide 두께 같은
정량적 수치 증거로는 쓰지 않는다. **sidewall 자체(수직면의
surface-normal 두께)도 이번 라운드에서 측정하지 않았다 — Item E의
측정 계약이 수직(vertical) 단면만 다루므로, 수직벽은 명시적으로
UNKNOWN이다.**

**측정 방법론적 함정(원인 미조사, 범위 밖) — D2 한정, D1 아님**: D1의
before oxide-side SiO2 cross-section은 실제로 존재한다(y=[0.00005,
0.02], 위 D1 결과 그대로) — **D1은 export 실패 없이 정상 측정됐다.**
export 실패는 **D2에서만** 일어났다: D2에서 Process().apply()를 한
번도 거치지 않은 "before" 상태의 wrapped SiO2 level set이 일반
`save_volume_mesh()`로 삼각화되지 않았다(교차 단면이 `None`으로 나옴,
반면 native `getMaterialsInDomain()`은 SiO2가 있다고 정확히 보고함) —
Process().apply()가 내부적으로 level set을 한 번 재초기화/Expand하는
것으로 보인다. B/C/D1의 **검증된 planar export**는 이 문제 없이
성공했다 — "두 재료(Si/SiO2)면 일반 exporter로 항상 안전하다"는
Rev.1 주장이 틀렸다는 근거는 **D2의 non-planar(mesa+trench) wrapped
geometry로 한정**한다. `measure_common.py`의 docstring을 이에 맞게
수정했다(아래 "수정된 measure_common.py 문구" 참조).

## 7. `.vpsd` reload 전후 capability 비교

```
LOCOS registration(register_locos_export) 전:  is_locos_registered = False
명시적으로 register_locos_export() 호출 후:      is_locos_registered = True
같은 domain을 save_domain_state() -> load_domain_state()로 재로드 후:
  is_locos_registered(reloaded) = False   <- 소실
  materials_native(reloaded) = ['Si','SiO2']   <- 이건 보존됨
  num_level_sets(reloaded) = 2                 <- 이것도 보존됨
```

**결론**: `.vpsd` 재로드는 domain 자체의 기하/material 정보는 정확히
보존하지만, `register_locos_export()`가 만드는 wrap-topology 지식(어떤
materials/wrap_flags로 export해야 하는지)은 `id(domain)`으로 키가 잡힌
**Python 프로세스 로컬 메모리**일 뿐이라(`tcad/backends/viennaps/io.py`의
`_LOCOS_EXPORT_HINTS`) 재로드된 새 Domain 객체에는 전혀 남아있지 않다.
GUI의 실제 워크플로(subprocess마다 `.vpsd`를 저장하고 다음 클릭에서
새 프로세스가 reload하는 구조, CLAUDE.md "One wafer now accumulates
state" 참조)를 고려하면, **이 지식은 매 프로세스 경계마다 사라지고
재등록해야 한다** — 이 사실 자체가 A7/A8의 preflight 설계에 직접
영향을 준다: LOCOS wrap 여부를 전제로 하는 어떤 preflight도, worker
subprocess 경계를 넘어 지속되는 자기 판별 로직(예: recipe의
`_process_model_key`/`is_locos_registered` 재확인)을 명시적으로 갖추지
않으면 잘못된 exporter를 고를 수 있다.

## 8. case별 지원/미지원 판정표 (Rev.2 전면 수정)

Rev.1은 "fresh/inherited bare Si"를 물리적 seed가 grid에 해상되기만
하면 **허용**으로 판정했다 — 이는 위 2.1의 whole-process 재분석으로
더 이상 성립하지 않는다. grid=0.001/0.002처럼 seed가 grid에 "해상"돼도
seed 생성 자체가 물질을 비보존적으로 창조하므로, bare Si는 **어떤
grid에서도 허용되지 않는다.**

| case | preflight에서 아는 정보 | solver 실행 허용? | 근거 | 실패 시 상태 |
|---|---|---|---|---|
| fresh/inherited **truly bare Si**, positive-time thermal | grid_delta, material 목록(native) | **불허 — UNSUPPORTED (모든 grid)** | 현재 backend는 초기 nucleation/seed 생성을 물질 보존적으로 표현하지 못한다(2.1 실증: whole-process ratio 2.54~2.55, +12%). grid가 seed를 "해상"해도 이 문제는 해소되지 않는다 | `UNSUPPORTED_BY_MODEL`, solver 호출 자체를 하지 않음 |
| explicitly known planar SiO2 geometry (real construction provenance 확인됨) | grid_delta, SiO2 존재(native) + **동일 x에서 실측한 실제 두께**(export 필요) | **조건부 허용, 검증된 범위 내에서만** | C matrix가 검증한 범위: grid ≤ oxide thickness, 0.002~0.05um 두께, 평면 구조 한정. 이 범위를 벗어나면(더 두꺼운/얇은 oxide, 비평면) 별도 검증 없이 확장하지 않는다 | 두께<grid_delta면, 또는 provenance(진짜 geometry인지, 솔버가 만든 seed인지)를 구분할 수 없으면 `UNSUPPORTED_BY_MODEL` |
| partial oxide / trench / sidewall / 곡면 geometry | grid_delta, SiO2 존재(native, **domain-wide만**) | **불허 — HARD BLOCKER** | coverage와 surface-normal 두께를 증명할 방법이 없다(D1/D3: SiO2가 있어도 별개 bare 표면은 0 성장; D2: 정성적으로 같은 패턴 추가 확인, sidewall 자체는 미측정) | `UNSUPPORTED_BY_MODEL` |
| arbitrary inherited domain (provenance 불명) | grid_delta, material 목록(native)뿐 | **불허 — HARD BLOCKER** | material 목록만으로는 지원 여부를 증명할 수 없다(D1/D3로 일반화된 원칙) | `UNSUPPORTED_BY_MODEL` |
| reloaded LOCOS `.vpsd` | grid_delta, material 목록(native, 보존됨) — **wrap-topology 지식은 소실**(7번 실증) | **재등록 근거 없으면 불허** | LOCOS-wrap 여부를 다시 확인/재등록하지 않고는 어떤 두께 실측도 신뢰 불가 | 재등록 메커니즘이 없다면 `UNSUPPORTED_BY_MODEL` |
| fresh LOCOS (recipe로 pad geometry 구성) | fresh 구성이므로 pad oxide 두께/grid 둘 다 recipe에서 확정적으로 알려짐 | **Rev.3.1의 검증 범위(20nm pad, 특정 recipe) 내에서만 조건부 허용** | **실제 LOCOS mechanics(contactMode=2 elastic coupling)까지 이번 C planar matrix로 일반화하지 않는다** — C는 mechanics가 없는 순수 평면 oxidation만 다뤘다. 근거는 Rev.3.1의 20nm pad 사례 1건뿐 | 다른 pad 두께/grid 조합은 별도 검증 전까지 `UNSUPPORTED_BY_MODEL` |
| directly chained registered LOCOS | grid_delta, `is_locos_registered()`(같은 프로세스 내에서만 신뢰 가능, 7번 참조), 실측 SiO2 두께 필요 | **조건부 허용, 단 등록 정보가 같은 프로세스 내에서 검증됐을 때만** | wrap 여부를 알아야 올바른 exporter로 실측 가능 | 등록 정보 없이 판단해야 한다면(예: reload 이후) `UNSUPPORTED_BY_MODEL` |

판정 원칙 재확인(전부 실측으로 뒷받침, Rev.2에서 bare-Si 항목만 강화):
- support를 **증명**할 수 있을 때만 solver 실행. "SiO2 material이
  domain 어딘가에 있다"는 증명이 아니고(D1/D3), "Deal-Grove 최종
  두께가 맞는다"도 증명이 아니다(B — kinetics는 맞아도 seed 생성
  단계가 무상 창조라면 whole-process는 미지원).
- 증명 불가 시 `UNSUPPORTED_BY_MODEL`, solver 0회.
- grid에 맞춰 물리적 oxide/seed 두께를 부풀리지 않는다(현재 코드의
  버그를 재현하지 않는다).
- unsupported case에서 geometry를 변경하지 않는다.
- zero-duration identity(이미 승인/구현됨)와 positive-time unsupported는
  의미가 다르다: identity는 "input == output이 보장된 진짜 항등
  전이"이고, positive-time unsupported는 "무엇이 일어날지 모르는
  요청을 거부"하는 것이다 — 후자는 canonical WaferState를 **identity로
  유지해 전기 측정을 통과시키면 안 된다.**

## 8.1 다음 구현안의 핵심 (P1-3, 텍스트만 — 코드 없음)

- 현재의 grid-floor seed(`max(0.002, grid_delta_um)`)는 삭제한다.
- bare Si의 positive-time oxidation은 **solver 호출 전에**
  `UNSUPPORTED_BY_MODEL`로 판정한다 — 모든 grid에서(2.1 실증).
- unsupported 경로에서 solver 호출 0회, geometry의 산화 관련 변경
  0건(이미 zero-duration 수정이 증명한 "solver 0회" 패턴을 positive-time
  unsupported에도 동일하게 적용).
- positive-time unsupported transition은 **identity가 아니다** —
  `state_transition.kind`를 `"identity"`와 절대 혼동하지 않는다.
- WaferState는 이 경우 **fail-closed**로 전달되어, 이후 어떤 device
  electrical solve도 이 전이를 근거로 진행되면 안 된다.
- explicit existing oxide를 지원하려면 (a) geometry provenance(솔버가
  만든 seed가 아니라 진짜 구성된 geometry인지), (b) coverage(어느
  표면까지 덮는지), (c) 동일 x/surface-normal 실측 두께, (d) exporter
  topology(wrap 여부)를 **전부** 증명해야 한다 — 하나라도 증명 못 하면
  `UNSUPPORTED_BY_MODEL`.
- 초기 native oxide(예: 자연 산화막)를 지원하려면, 그 두께는 **사용자가
  명시한 실제 initial geometry로 구성**해야 하며, oxidation 스텝 도중에
  solver가 무상으로 생성해서는 안 된다 — 이것이 이번 라운드가 실측으로
  확정한 B의 근본 문제다.

## 9. 다음 구현에서 사용할 최소 preflight 계약 (텍스트 제안, 코드 아님)

```python
{
    "physics_status": {
        "resolution": "UNSUPPORTED_BY_MODEL",
        "reason_code": "OXIDE_THICKNESS_UNRESOLVED_AT_GRID",
        #  다른 reason_code 후보: "BARE_SI_SEED_NOT_MASS_CONSERVING" (2.1,
        #  모든 grid에서 적용 -- grid 해상 여부와 무관),
        #  "PARTIAL_OXIDE_COVERAGE_UNVERIFIABLE",
        #  "WRAP_TOPOLOGY_UNKNOWN_AFTER_RELOAD", "SIDEWALL_MEASUREMENT_UNSUPPORTED"
        "note": "...",
        "requested_initial_oxide_um": ...,   # None이면 native seed 요청
        "grid_delta_um": ...,
        "measured_min_oxide_um": ...,        # 알 수 있을 때만; 모르면 None
    },
    "state_transition": {
        "kind": "unsupported",
        "category": "oxidation",
        "reason": "...",
    },
}
```

`kind="identity"`는 실제 `time_hours=0` inherited 전이에만 쓴다(이미
구현/승인됨, 이번 계약과 절대 혼동하지 않는다). GUI에는 요청값·grid·거부
사유가 표시돼야 하고, CLI/flow도 같은 `state_transition`을 보존해야
한다는 원칙은 D1/D3/7번의 실측 결과가 직접 뒷받침한다 — "SiO2가
있다"는 표면적 정보만으로 GUI/CLI가 성공을 표시하면, 사용자는 실제로
전혀 산화되지 않은 표면을 산화된 것으로 오인하게 된다. **Rev.2 추가**:
`reason_code`가 `"BARE_SI_SEED_NOT_MASS_CONSERVING"`(또는 동등한
값)인 경우를 명시적으로 추가한다 — 이것이 2.1에서 확정된, bare-Si
positive-time 산화가 모든 grid에서 unsupported인 이유이며, 단순히
"grid가 안 맞는다"(`OXIDE_THICKNESS_UNRESOLVED_AT_GRID`)와는 다른
사유이므로 GUI 메시지도 구분돼야 한다.

## 10. 아직 증명하지 못한 형상/조건 목록

- **trench sidewall 자체(수직면)의 surface-normal 산화 지원 여부** —
  D2에서 수평 바닥만 확인, 수직벽은 미측정.
- **1x~2x grid/oxide 비율 구간의 정확한 임계값** — C에서 grid≤oxide는
  6/6 supported, grid/oxide=2~2.5는 3/3 no-growth failure로 양 끝만
  확인했고 중간은 미샘플링(정확한 임계값은 UNKNOWN). **B는 bare-Si
  whole-process 자체가 별도 사유로 UNSUPPORTED이므로(2.1) 이 임계값의
  supported 근거로 사용하지 않는다** — B의 grid=0.001/0.002가 "seed가
  grid에 해상됐다"는 사실은 이 임계값 논의와 별개다.
- **곡면(라운드된 모서리, LOCOS bird's-beak 형태의 완만한 경사) 표면** —
  전혀 테스트하지 않음.
- **여러 개의 독립된 bare 영역이 동시에 존재할 때, 이들 중 일부에만
  기존 oxide가 인접한 경우**(D1은 2영역만 테스트) — 3개 이상의 혼합
  케이스 미검증.
- **grid가 위치에 따라 다른(비균일 mesh) 경우** — 이번 조사는 전부
  균일 grid만 사용.
- **explicit pad_oxide_thickness_um이 LOCOS mask/oxide mechanics
  (contactMode=2)와 상호작용할 때**의 해상 조건 — Rev.3.1은 20nm
  pad oxide 사례 1개만 확인했고, 이번 라운드는 mechanics 없는 순수
  평면 oxidation만 다뤘다.
- **D2의 "before" export가 wrapped level set을 삼각화하지 못하는
  현상의 근본 원인**(D1은 이 문제 없이 정상 측정됐음, D2 한정) —
  우회(구성 파라미터로 대체)만 했고 원인 조사는 하지 않음.
- ~~B와 C의 ratio 차이 원인~~ — **Rev.2에서 설명됨**(2.1 참조): B는
  whole-process에 seed의 무상 생성이 섞여 있고, C는 처음부터 진짜
  geometry라 섞일 게 없다. 더 이상 "아직 증명 못 한 것" 목록이 아니다.
- **B의 post-seed ratio(2.31~2.33)가 C의 ratio(2.27~2.32)보다 정확히
  얼마나/왜 살짝 높은지의 미세한 잔차** — 둘 다 "보존적"이라는 정성적
  결론에는 영향 없지만, 정확한 원인(seed 생성이 solver 초기 상태에
  남기는 잔류 수치오차 등)은 분리하지 않았다.

## 11. `git diff --check`

```
$ git diff --check
(경고만 존재 — CRLF 관련, 실제 whitespace 오류 없음)
$ echo $?
0
```

## 12. HEAD와 커밋 없음 확인

```
$ git status --porcelain=v1 -- tcad/process/oxidation/
 M tcad/process/oxidation/locos.py
 M tcad/process/oxidation/thermal.py
?? tcad/process/oxidation/zero_duration.py

$ git diff --stat -- tcad/process/oxidation/
 tcad/process/oxidation/locos.py   | 8 +++++++-
 tcad/process/oxidation/thermal.py | 7 ++++++-
 2 files changed, 13 insertions(+), 2 deletions(-)
```
이 라운드 시작 전(이전 zero-duration 라운드가 끝난 시점)과 **완전히
동일한 diff** — 이번 조사 라운드는 `tcad/`에 단 한 줄도 추가하지
않았다. 새로 생긴 것은 `docs/audits/2026-09-18-tier1-2-oxidation-
positive-support/`(untracked) 뿐이다.

```
$ git rev-parse HEAD
3ba940404fd19c88eaaccc96a39ffe8444fb8851
```
세션 시작 시점과 동일 — 커밋 없음.