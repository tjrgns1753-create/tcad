# Tier 1-2 — oxidation seed 오염 조사 (Rev.3, 구현 없음, Codex 검토 대기)

Scope: 재현 + 원인 격리 + 확장 matrix 조사만. 산화 코드는 여전히 수정하지
않았다. 전체 회귀도 돌리지 않았다. 이 디렉터리는 Tier 1-1 r4의
`docs/audits/2026-09-18-tier1-1-r4/`와 분리되어 있다.

**Rev.3 변경 사항** (이번 라운드, Matrix 1~4 재실행 없이 기존 raw 결과
재사용 + 신규 조사만 수행): (1) 보존 계산을 세 관점으로 분리
(PHYSICAL_BARE_SI_ACCOUNTING / SOLVER_INTERNAL_SEEDED_STEP /
NAIVE_POSTHOC_NOMINAL_SUBTRACTION) — `conservation_v3.py`/
`conservation_v3.json`, 기존 `results.json`(Rev.1)과 `results_v2.json`
(Rev.2)의 raw 값만 읽어서 재계산, 신규 ViennaPS 실행 없음. (2) Matrix 4의
`additional_oxide_added_um` 필드를 `measured_delta_*`/`nominal_delta_*`
로 분리. (3) Matrix 5 LOCOS 세 경로 각각에 대해 `Process.apply()` 직전/
직후 실제 geometry snapshot을 찍어 identity를 **수치로 assert**
(`investigate_v3_locos.py`/`results_v3_locos.json`) — 최초 시도에서 자체
export 버그(LOCOS "topmost wins" 삭제 문제를 제 스냅샷 함수가 그대로
밟음)를 발견해 `investigate_v3b_fix.py`/`results_v3b_corrected.json`로
재실행. (4) fresh LOCOS pad-oxide grid-floor 4-case targeted matrix 추가.
(5) Rev.2의 부정확한 문장 2건 제거·교체(아래 각 섹션에 표시).

**Rev.2 변경 사항** (유지): Codex 1차 검토에서 지적된 P0(문제 범위 오류),
P1 3건(측정량 미분리, native bbox 증거 오용, Group B 명명 오류)을 모두
수정했고, 요청된 5개 matrix + 물성 보존 확인을 실제 ViennaPS 실행으로
전부 수행했다. Rev.1의 잘못된 결론("time>0에서는 물리적으로 정상적인
거동")은 **삭제**한다.

파일: `repro_oxidation_time0.py`/`results.json`/`full_stdout.log`
(Rev.1, 최초 재현), `investigate_v2.py`/`results_v2.json`/
`full_stdout_v2.log`(Rev.2, 전체 matrix), `fix_m5c.py`/
`m5c_corrected.json`(Rev.2의 M5c 재실행 — Rev.3에서
`SUPERSEDED_INVALID_FIXTURE`로 재분류, 아래 참조),
`conservation_v3.py`/`conservation_v3.json`(Rev.3, 보존 3-view),
`investigate_v3_locos.py`/`results_v3_locos.json`(Rev.3, LOCOS 최초 시도
— pad oxide 수치는 export 버그로 무효, identity 결론은 유효),
`investigate_v3b_fix.py`/`results_v3b_corrected.json`(Rev.3, LOCOS-aware
export로 정정한 최종 공식 수치).

## 측정량 정의 (P1 수정)

기존 `oxide_thickness_um` 하나로 뭉뚱그렸던 것을 3개로 분리한다
(`investigate_v2.py`의 `measure()`):

- **`ambient_surface_displacement_um`** = `SiO2_y_max(export) − initial_Si_surface_y`
  — 원래 bare-Si 표면(y=0) 대비 바깥쪽(ambient) 계면이 이동한 거리.
- **`total_oxide_thickness_um`** = `SiO2_y_max(export) − SiO2_y_min(export)`
  — 지금 이 순간 SiO2 층의 실제 전체 두께.
- **`silicon_consumed_um`** = `initial_Si_surface_y − Si_y_max(export)`
  — Si/SiO2 계면이 원래 표면(y=0)에서 아래로 이동한 거리(실제 Si 소비량).

t=0에서는 Si/SiO2 계면이 전혀 움직이지 않으므로 1번≈2번이지만, t>0에서는
Si가 소비되어 계면이 내려가므로 둘이 달라진다 (아래 표에서 실증).
셋 다 **export mesh(meshio) 기준으로만** 계산한다 — 이유는 바로 아래.

## native bbox 증거 정정 (P1 수정)

Rev.1의 "native bbox와 export의 SiO2 y 범위가 일치한다"는 주장은
**삭제**한다. 실측으로 확인한 사실은 다음과 같다 (`investigate_v2.py`의
`native_bbox_sanity_check`, grid=0.05, t=0.5 실제 성장 전/후 비교):

```
native isolated bbox BEFORE growth: [{'index': 0, 'y_min': 0.0, 'y_max': 0.0}]
native isolated bbox AFTER  growth: [{'index': 0, 'y_min': 0.0, 'y_max': 0.0},
                                      {'index': 1, 'y_min': 0.05, 'y_max': 0.05}]
export mesh AFTER growth (authoritative): Si={'y_max': -0.006414...} SiO2={'y_max': 0.058781...}
```

즉 0.5hr 실제 성장이 일어나 SiO2 표면이 0.05→0.0588um, Si 계면이
0→-0.0064um로 실제 이동했는데도, isolated `getBoundingBox()`는 **성장
전과 후가 완전히 동일**하다 (seed 생성 시점의 값 그대로). native bbox는
level set의 실제 advection 이후 위치를 반영하지 못한다 — level set 자신의
내부 구성 시점 bbox(혹은 그와 동등한 고정값)를 반환할 뿐이다.

이제부터 native 호출의 증거 범위는 다음으로 **제한**한다:
- `getMaterialsInDomain()` — SiO2 material이 domain에 실제로 추가됐음을 증명.
- native level-set bbox — (t=0에 한해서만) seed로 새로 생성된 표면이
  대략 어디 있는지 증명 (성장이 없었던 시점이므로 우연히 export와 일치).
- export mesh — 두 level set 사이가 실제 SiO2 material region으로
  삼각화됐음을 증명, **그리고 t>0의 실제 이동한 계면 위치는 export mesh만이
  신뢰 가능한 근거**.
- native bbox와 export의 교차확인은 **t=0의 최초 seed 위치 확인에만**
  유효하다 (본 조사에서 재확인: grid=0.02/0.05/0.10 t=0 각각
  0.019999999552965164/0.05000000074505806/0.10000000149011612 — 2nd
  round는 편의상 재실행하지 않고 Rev.1 결과를 그대로 인용).

## Group B 명명 정정 (P1 수정)

Rev.1의 "`bareDefault`"는 `setInitialOxideThickness(0.002)`를 **명시
호출**한 케이스였다 — "생략"이 아니었다. Rev.2에서 세 가지를 모두 분리해서
실행했다 (Matrix 1):

- **setter 자체를 생략**(`M1_no_setter_call`) → ViennaPS 진짜 bare
  default 확인: 로그 `"no SiO₂ layer found; seeding 0.002000 µm native
  oxide."` — **ViennaPS 자신의 내부 기본값은 정확히 0.002um**
  (thermal.py 주석의 주장과 일치, 이번에 직접 재확인).
- **`setInitialOxideThickness(0.0)` 명시 호출**(`explicit_2nm_seed`가
  아니라 `setter_explicit_0.0`로 개명) → 다른 로그 메시지
  `"no SiO₂ layer found; inserting zero-thickness oxide seed."` — degenerate
  두께-0 계면이 생기며, native `getMaterialsInDomain()`은 `['Si','SiO2']`를
  보고하지만 **export mesh는 SiO2 삼각형이 0개**(`save_volume_mesh()`
  자체의 "missing material" 경고가 실제로 발동)이고 t=0.5에서도 전혀
  성장하지 않는다(총 두께 0.000000, si_consumed=0.000000, 두 시점 동일) —
  0 두께 seed는 "산화막 없음"이 아니라 "영원히 자라지 않는 degenerate
  계면"이라는, 또 다른 실패 모드다.
- **`setInitialOxideThickness(0.002)` 명시 호출**(구 Group B, 이제
  `setter_explicit_0.002`) → 진짜 default와 동일 결과.

## [P0] 문제 범위 수정: seed는 time=0만의 문제가 아니다

Codex 지적을 실측으로 확인했다. grid=0.05um(현재 프로덕션 floor: seed
50nm), t=0.5hr, bare Si 시작:

```
B = 0.010439 um^2/hr   (로그에서 직접 파싱, 아래 모든 케이스에서 동일 확인)
B/A = 0.044911 um/hr
A = B/(B/A) = 0.232437 um
```

Deal-Grove (`x_f^2 + A*x_f = x_i^2 + A*x_i + B*t`):

| 시나리오 | x_i | 예측 x_f | ViennaPS 실측 total_oxide_thickness_um | 예측 대비 오차 |
|---|---|---|---|---|
| bare-Si (물리적으로 맞는 답) | 0 | 0.020625 um | — | — |
| 50nm seed를 real initial oxide로 취급 | 0.05 | 0.065022 um | **0.065196 um** | **0.27%** |

ViennaPS 실측값은 "50nm 기존 oxide가 있었다"는 예측과 0.27% 이내로
일치하고, 진짜 물리적 정답(bare-Si, 20.6nm)보다 **3.16배** 크다. 즉 이
seed는 t=0에서만 보이는 표면적 결함이 아니라, **kinetics 자체에
실제로 참여해서 최종 두께와 Si 소비량을 오염시키는 진짜 초기조건**이다.

**Rev.1의 "time>0에서는 물리적으로 정상적인 거동"이라는 문장을 삭제하고
다음으로 대체한다:**

> "50nm pre-existing oxide 초기조건에 대해서는 Deal-Grove와 일치하지만
> (0.27% 오차), bare-Si 공정 결과로는 물리적으로 잘못됐다 (진짜 정답보다
> 3.16배 큼). 이는 grid_delta_um이라는 순전히 수치적 선택에 의해 결정된
> 오차이며, grid를 바꾸면 '물리적으로 맞는 답'이 달라진다 (Matrix 2 참조)."

## Matrix 1 — seed setter 3가지 × {t=0, t=0.5} (grid=0.05)

| 케이스 | t | material(native) | substeps | total_oxide_um | ambient_disp_um | si_consumed_um | 비고 |
|---|---|---|---|---|---|---|---|
| no_setter (진짜 default) | 0 | Si,SiO2 | 0 | 0.001751 | 0.002000 | -0.000249(≈0) | seed=0.002um |
| no_setter | 0.5 | Si,SiO2 | 1 | 0.001751 | 0.002000 | -0.000249(≈0) | **grid=0.05가 2nm seed 해상 불가 → 0.5hr 시뮬레이트됐다고 보고되지만 전혀 성장 안 함(정지)** |
| setter=0.0 | 0 | Si,SiO2(native만) | 0 | 0.000000 | 0.000000 | 0.000000 | export에 SiO2 삼각형 0개(경고 발동) |
| setter=0.0 | 0.5 | Si,SiO2(native만) | 1 | 0.000000 | 0.000000 | 0.000000 | **두께 0 seed는 영원히 안 자람** |
| setter=0.002 | 0 | Si,SiO2 | 0 | 0.001751 | 0.002000 | -0.000249(≈0) | default와 동일 |
| setter=0.002 | 0.5 | Si,SiO2 | 1 | 0.001751 | 0.002000 | -0.000249(≈0) | 위와 동일하게 정지 |

핵심 발견: grid=0.05에서 물리적으로 올바른 2nm seed조차 **완전히 성장이
정지**한다 (0.5hr을 "시뮬레이트했다"고 보고하면서 두께가 조금도 안 변함,
에러도 경고도 없음) — thermal.py 주석에 있던 "stalls below gridDelta"
서술이 정확했음을 재확인. 즉 grid_delta_um으로 seed를 띄우는 현재 floor는
"수렴 안 하는 것"과 "물리적으로 틀린 두꺼운 seed로 도망치는 것" 사이의
트레이드오프였다 — 두 갈래 다 문제.

## Matrix 2 — t=0.5hr, grid 3종, 현재 floor seed vs Deal-Grove

| grid | seed(floor) | Deal-Grove bare-Si | Deal-Grove w/ seed as x_i | ViennaPS 실측 | 예측 대비 오차 | bare-Si 대비 배율 |
|---|---|---|---|---|---|---|
| 0.02 | 0.020 | 0.020625 | 0.037973 | **0.038556** | 1.535% | **1.87x** |
| 0.05 | 0.050 | 0.020625 | 0.065022 | **0.065196** | 0.268% | **3.16x** |
| 0.10 | 0.100 | 0.020625 | 0.111751 | **0.111067** | -0.612% | **5.39x** |

**동일한 물리 레시피(같은 T, oxidant, t=0.5hr, bare Si 시작)가 순전히
grid_delta_um 선택만으로 38.6nm/65.2nm/111.1nm — 거의 3배 범위로 달라진다.**
매 grid마다 자기 자신의 seed를 x_i로 넣은 Deal-Grove 예측과는 0.27~1.5%로
정확히 일치한다(즉 노이즈가 아니라 결정론적 오염). 이것이 현재
`max(0.002, grid_delta_um)` floor의 실제 위험이다.

## Matrix 3 — 미세 grid(0.001/0.002um), 물리적 2nm seed가 실제로 해상되는가

작은 domain(0.3 x 0.5 um)에서 `setInitialOxideThickness(0.002)`(grid로
플로어링하지 않은 진짜 2nm)로 t=0.5hr 실행:

| grid | seed==grid? | 실행시간 | substeps | Deal-Grove(x_i=0.002) 예측 | ViennaPS 실측 | 오차 |
|---|---|---|---|---|---|---|
| 0.002 | 1x(경계) | 5.26s | 13 | 0.022328 | **0.022785** | 2.05% |
| 0.001 | 0.5x(2배 오버샘플) | 48.71s | 26 | 0.022328 | **0.022823** | 2.22% |

두 grid 모두 **수렴했고**, 진짜 2nm seed를 물리적 초기조건으로 넣은
Deal-Grove 예측과 ~2%대 오차로 일치한다 — Matrix 1의 grid=0.05(25배
언더샘플) 완전 정지와 뚜렷이 대조된다. 즉 "2nm seed가 해상되려면 grid가
seed 크기와 같거나 더 작아야 한다"는 것이 실측으로 확인됐다(정확한
경계값은 이 두 점만으로는 특정할 수 없음 — 0.002~0.05 사이 어딘가).
실행시간은 grid=0.001에서 48.71s로 grid=0.002의 9배 이상 — 미세 grid로
"항상 물리적 seed 사용"을 강제하면 비용이 크다는 것도 확인.

## Matrix 4 — 기존 실제 SiO2가 있는 구조

grid=0.05, 미리 `MakePlane`으로 진짜 0.05um SiO2를 얹어둔 Si 웨이퍼에
thermal.py와 동일하게 `setInitialOxideThickness(max(0.002,grid))`를
**무조건 호출**하며 오xidation 실행:

| t | native seed 메시지 발동 | BEFORE=AFTER(identity)? | 이번 스텝 추가 oxide | 이번 스텝 Si 소비 |
|---|---|---|---|---|
| 0.0 | **발동 안 함**(None) | **예, 완전 identity** (모든 y 범위 소수점까지 동일) | 0 | 0 |
| 0.5 | **발동 안 함**(None) | — | 0.015196 um | 0.006663 um |

**중요한 발견**: thermal.py는 `setInitialOxideThickness()`를 SiO2 존재
여부와 무관하게 무조건 호출하지만, **ViennaPS 자신의 C++ 코드가 이미
SiO2 layer 존재 여부를 확인하고 있어서** ("no SiO₂ layer found; seeding..."
메시지는 SiO2가 없을 때만 발동), 이미 진짜 oxide가 있는 경우엔 seed가
추가되지 않는다 — t=0에서 완전한 identity, t=0.5에서도 스퓨리어스 재-seed
없이 순수하게 기존 0.05um를 x_i로 한 실제 성장만 일어난다. 즉 **버그는
"SiO2가 이미 있을 때 seed가 또 생기는 것"이 아니라, "SiO2가 정말 없을
때(bare Si) native-oxide seed가 grid 크기로 부풀려지는 것"**으로 범위가
좁혀진다.

### Matrix 4 필드 정정 (Rev.3, P0)

기존 `additional_oxide_added_um = after.total − real_oxide_um`
(nominal 0.05 고정값 사용)은 t=0에서도 **-0.0002487um**을 반환해 "완전
identity"라는 서술과 숫자가 안 맞아 보이는 문제가 있었다 — 이는
export mesh 자체의 discretization 잔차(0.05 요청 시 실제 삼각화된 값은
0.049975...로 grid 노이즈 수준 차이가 남)를 nominal 값과 비교했기 때문.
`conservation_v3.py`로 measured/nominal을 분리해 재계산(재실행 없이
기존 raw 값만 사용):

| t | measured_delta_oxide_um (after.total−before.total) | nominal_delta_oxide_um (after.total−0.05) | measured_delta_si_um | t=0 identity(측정 기준)? |
|---|---|---|---|---|
| 0.0 | **0.0000000000** | -0.0002487555 | **0.0000000000** | **예, 정확히 0** |
| 0.5 | 0.0154448324 | 0.0151960769 | -0.0066630849 | — |

**measured 기준으로 재확인하면 t=0 identity는 정확히 0으로 성립한다** —
Rev.2가 보였던 -0.0002487은 nominal 값(고정 0.05)과 measured before(약
0.049975)의 discretization 차이일 뿐, identity 위반이 아니었다.

## Matrix 5 — LOCOS 세 경로 (Rev.3: 실제 identity 수치 assert)

`tcad.process.registry`로 실제 `LocosOxidation`/`ThermalOxidation`
클래스를 그대로 호출(우회 없음). 공통 recipe:
grid=0.05, x=3.0, y=2.0, mask 1.0~2.0um, mask_material="Mask", t=0.

**방법 (Codex 제안 그대로 구현)**: production 코드를 전혀 수정하지 않고,
`vps.Process`(모듈 레벨 속성)를 감사 스크립트 안에서만
`with process_spy(...):` 블록 동안 spy 클래스로 임시 교체해 실제
`apply()` 직전/직후 domain을 export한다. 블록이 끝나면 원래
`vps.Process`로 즉시 복원되고(`investigate_v3_locos.py`의
`process_spy`/`process_spy_locos` context manager), 이 교체는 디스크에
아무것도 남기지 않는다 — `session.py`가 갖고 있는 `vps` 참조도 같은
모듈 객체를 가리키므로 locos.py 내부의 `module.Process(...)` 호출도
그대로 spy를 타게 된다.

**중요한 자체 발견**: 최초 시도(`investigate_v3_locos.py`)의 snapshot
함수가 일반 `save_volume_mesh()`를 썼는데, 이는 이 프로젝트가 이미
CLAUDE.md에 문서화한 "LOCOS topmost-wins export erosion" 문제를 그대로
밟아 pad oxide 두께를 실제 값의 1/40~1/400로 잘못 측정했다(경고
"missing 1 material(s)"가 매 실행마다 발동한 것이 증거). `LocosOxidation.
_locos_stack_spec()`이 공개하는 실제 stack 스펙([Si,SiO2,Mask],
[False,True,False])으로 `save_locos_volume_mesh()`를 직접 써서
(`investigate_v3b_fix.py`) 재실행했다 — **A/B 경로의 identity 결론(True/
True)은 두 스냅샷이 같은 방법을 일관되게 썼으므로 최초 시도에서도
이미 맞았지만, 절대 두께 수치는 정정된 버전만 신뢰한다.**

| 경로 | 1) solver identity(prepared→post-apply) | 2) public-step identity(input→output) |
|---|---|---|
| (A) fresh LOCOS | **True** | **N/A** (아래 설명) |
| (B) chained LOCOS-on-LOCOS | **True** | **True** |
| (C) LOCOS on 완전 bare non-LOCOS Si | **False** | **False** (아래 수치) |

- **(A) fresh LOCOS**: `_build_locos_geometry()`가 준비를 마친 시점
  (apply 직전)과 apply 직후의 SiO2/Mask/Si 범위가 소수점까지 완전히
  동일 — **solver identity = True**(수치 assert 완료,
  `results_v3b_corrected.json`의 `M5_A_corrected`). **public-step
  identity는 성립 여부를 따질 수 없다(N/A)** — fresh LOCOS는
  `run()` 입력이 `None`(inherited domain 없음)이므로 "입력=출력"이라는
  개념 자체가 처음부터 적용되지 않는다(from-scratch 빌드는 원래
  아무것도 없는 상태에서 pad oxide+mask geometry를 만드는 것이 그
  스텝의 정의이며, 이는 seed 오염이 아니라 "새 wafer를 만든다"는 것의
  당연한 결과다). **삭제/교체**: Rev.2의 "t=0에서 identity로 추정됨"이라는
  문장을 이 명확한 A1/A2 구분으로 대체한다.
- **(B) chained LOCOS-on-LOCOS**: inherited domain(SiO2=[0,0.05],
  Mask가 재-wrap되어 [-0.5,0.55]까지 뻗어 있는 상태, 1단계 run()의 최종
  출력)과, 2단계 run()이 끝난 뒤의 최종 domain을 비교 — **완전히 동일**
  (`public_identity=True`), 그리고 2단계 자신의 apply() 전/후도 동일
  (`solver_identity=True`). 둘 다 수치로 assert됨.
- **(C) LOCOS on 완전 bare non-LOCOS Si**: `ThermalOxidation().
  prepare_domain(recipe)`만 호출(=`Process()`를 한 번도 실행하지 않은
  진짜 bare Si+trench 기하, Mask/Si만 존재, SiO2 없음)을
  `LocosOxidation(inherited_domain=...)`에 체이닝:
  ```
  Oxidation: no SiO₂ layer found; seeding 0.050000 µm native oxide.
  Oxidation: starting LOCOS simulation, ... total=0.000000 hr, ...
  Oxidation: LOCOS complete — 0 substep(s), 0.000000 hr simulated.
  ```
  입력에는 SiO2가 전혀 없었는데(`getMaterialsInDomain()`이 `['Mask','Si']`
  만 보고, native 호출이므로 export 정확도와 무관하게 신뢰 가능) apply 후
  `['Mask','Si','SiO2']`로 바뀐다 — **solver/public identity 둘 다
  False, 수치로 확인**. **주의(export 신뢰도 caveat)**: 이 경로는
  ViennaPS 자신의 오xidation 모델이 native하게 SiO2 level set을
  생성하는 경로라서 `[Si,SiO2,Mask]/[False,True,False]` wrap 스펙을
  이 스크립트가 안전하게 가정할 수 없다 — 그래서 `investigate_v3_
  locos.py`의 최초(미보정) export로 얻은 "SiO2 thickness ≈ 0.55um"라는
  절대 두께 수치는 **신뢰 불가이며 정량 결과에서 제외한다**. authoritative
  `seed_created_thickness_um`은 Rev.3.1에서 `null`로 교체했고, 원래 숫자는
  `raw_untrusted_measurement` 아래에 감사 이력으로만 남겼다
  (locos.py의 이 분기는 `mask_material`이 recipe에 있으면 LOCOS의
  mask/oxide elastic-contact mechanics(`contactMode=2`)까지 함께
  활성화하므로, 단순 seed 두께보다 더 복잡한 재구성이 일어날 수 있음을
  시사한다 — mechanics 자체의 영향은 이번 라운드에서 분리 규명하지
  않았다). **확실한 것은 SiO2 material이 무(無)에서 생겼다는 사실
  자체이며, 이는 export 방법과 무관한 native 사실이다.**

**SUPERSEDED_INVALID_FIXTURE**: Rev.2의 최초 `fix_m5c.py` 실행(및 그
이전 `investigate_v2.py` matrix5 항목)은 "non-LOCOS" 도메인을
`ThermalOxidation().run()`(즉 `Process()`를 실제로 호출)으로 만들어서,
그 호출 자체가 이미 thermal.py의 t=0 seed를 심어버린 뒤 LOCOS를
체이닝한 것이었다 — 그래서 "SiO2가 이미 있으니 재-seed 안 함"으로
보였던 것은 **오염된 fixture의 false negative**였다. 이 결과는 공식
Matrix 5 집계에서 **제외**하고, 위 (C)의 진짜 bare-Si 버전만 공식
결과로 채택한다(`investigate_v3_locos.py`의 `SUPERSEDED_INVALID_
FIXTURE` 딕셔너리, `results_v3_locos.json` 참조).

## fresh LOCOS pad-oxide grid-floor 4-case matrix (Rev.3, 신규)

`DEFAULT_PAD_OXIDE_THICKNESS_UM = 0.02`([locos.py:152](../../../tcad/process/oxidation/locos.py:152))도
`recipe.get("pad_oxide_thickness_um", max(0.02, grid_delta_um))`
([locos.py:211-214](../../../tcad/process/oxidation/locos.py:211))로
grid 플로어링된다 — thermal.py의 seed와 **별개의** grid-dependent
hidden-geometry 후보. 모두 t=0, `process_spy_locos`로 apply 직전/직후
실제 pad oxide 두께를 export(LOCOS-aware, `save_locos_volume_mesh()`
사용)로 측정 (`investigate_v3b_fix.py`):

| case | grid | pad 요청 | prepared 두께(실측) | expected(공식) | 일치? |
|---|---|---|---|---|---|
| 1. grid=0.01, 미지정 | 0.01 | (없음→floor) | **0.020000** | 0.02 | 예 |
| 2. grid=0.02, 미지정 | 0.02 | (없음→floor, 경계) | **0.020000** | 0.02 | 예 |
| 3. grid=0.05, 미지정 | 0.05 | (없음→floor) | **0.050000** | 0.05 | 예 |
| 4. grid=0.05, 명시 0.02 | 0.05 | 0.02(명시) | **0.020000** | 0.02 | 예 |

**판정 (Codex 판정 기준대로)**:
- 미지정 케이스가 grid에 따라 20/20/50nm가 됐다 — **이는 thermal seed와
  별개의, 진짜 grid-dependent hidden-geometry 버그다.** case1/2는 아직
  20nm 기본값이 살아있지만(grid이 그보다 작아 floor가 안 걸림),
  case3(grid=0.05)은 요청한 적 없는 50nm로 조용히 부풀려진다 — 에러도
  경고도 없음.
- 명시적 20nm(case4)는 grid=0.05(2.5배 언더샘플)에서도 **t=0 초기
  형상만은** 정확히 0.02um로 구성됐다. 그러나 이것은 양의 시간 산화의
  해상도를 증명하지 않는다. Rev.3.1 실측에서 같은 `grid=0.05`, 명시적
  20nm, `time=0.5hr` 조건은 완료 로그를 냈지만 산화막 성장과 Si 소비가
  모두 0으로 정지했다. 따라서 이 조건은 현재 **지원 불가/fail-closed
  대상**이다. 세부 수치는 `REPORT_REV3_1.md`를 참조한다.
- 결론: **fresh LOCOS는 영향이 없다고 결론 내릴 수 없다** — pad
  oxide가 grid로부터 "조용히" floor되는 것은 thermal.py의 문제와
  똑같은 클래스의 버그이며, 유일한 차이는 "recipe가 명시적으로
  pad_oxide_thickness_um을 주면 이 특정 버그를 피할 수 있다"는 회피
  경로가 이미 존재한다는 것뿐이다. 이 항목을 이번 Tier 1-2 범위에
  포함할지, 별도 Tier로 분리할지는 다음 라운드에서 결정할 사항으로
  남긴다(제안: thermal.py의 seed와 같은 근본 원인 카테고리이므로 같은
  Tier에서 함께 고치는 것이 합리적으로 보이나, 최종 판단은 Codex 몫).

## 물성 보존 확인 — 세 관점으로 분리 (Rev.3, P0 수정)

Rev.2의 계산은 관점이 섞여 있었다(oxide 쪽은 nominal 0.05, Si 쪽은
export mesh의 raw offset을 그대로 써서 기준이 안 맞았다). `conservation_
v3.py`로 세 관점을 명확히 분리했다 — **재실행 없이, Rev.1(`results.json`
의 t=0, seed=0.05, grid=0.05 케이스)과 Rev.2(`results_v2.json`의 Matrix 2
grid=0.05, t=0.5 케이스)의 기존 raw export 좌표만 다시 계산**:

### 1) PHYSICAL_BARE_SI_ACCOUNTING — bare-Si 물질 보존 판정 (유지)

```
real_initial_oxide = 0
oxide_created       = 0.0651960769 um
silicon_consumed    = 0.0064143287 um
ratio                = 10.164   (기대 ≈2.27)
```
**이것이 현재 production 결과가 bare-Si 물질 보존을 위반한다는 실제
판정값이다 — 그대로 유지.**

### 2) SOLVER_INTERNAL_SEEDED_STEP — seed를 실제 initial condition으로
받아들인 이후, ViennaPS 자신의 성장 자체가 보존적인가

같은 50nm-seed/grid=0.05 레시피의 t=0(BEFORE, seed 직후) export와
t=0.5(AFTER) export를 직접 차분:
```
before.total_oxide = 0.0497512445 um   (seed 직후, Rev.1 raw)
after.total_oxide  = 0.0651960769 um   (t=0.5, Rev.2 raw)
delta_oxide = after.total − before.total = 0.0154448324 um

before.si_interface = 0.0002487562 um
after.si_interface  = -0.0064143287 um
delta_si = |after.si_interface − before.si_interface| = 0.0066630849 um

ratio = delta_oxide / delta_si = 2.318   (기대 ≈2.27, mesh discretization 안에서 근접)
```
**이는 ViennaPS가 생성된 seed를 실제 initial oxide로 간주한 뒤에는
내부적으로 대체로 보존적인 성장을 한다는 증거다** — 문제는 이 성장
단계가 아니라, 애초에 seed가 "공짜로"(거의 0의 Si 소비로) 만들어지는
생성 단계에 있다(1번 관점).

### 3) NAIVE_POSTHOC_NOMINAL_SUBTRACTION — 참고 수치, 보존 test 아님

```
additional_oxide = after.total − nominal_seed(0.05) = 0.0151960769 um
ratio (1번의 silicon_consumed=0.0064143287 대비) = 2.369
```
**이 2.369는 물질 보존 test가 아니다.** "사용자가 최종 두께에서 nominal
seed만 단순 차감했을 때 생기는 불일치"를 보여주는 참고 수치일 뿐이다.

**사후 subtraction 금지의 결정적 근거 (핵심은 보존비의 작은 잔차가
아니라 kinetics 자체가 바뀐다는 것)**:
```
bare-Si Deal-Grove 예측(x_i=0, t=0.5):        0.020625 um
seed-run ViennaPS 실측:                        0.065196 um
seed-run − nominal 50nm:                       0.015196 um
```
seed-run 원본도, 사후에 50nm를 뺀 값도 **둘 다 bare-Si 정답(0.020625um)을
복원하지 못한다.** 이유는 numerical seed가 최종 두께 하나만 바꾼 게
아니라, Deal-Grove kinetics의 실효 초기조건(A, CFL 스텝이 적분을
시작하는 지점) 자체를 처음 substep부터 바꿔놓았기 때문이다 — 두께에서
숫자를 빼는 사후 보정으로는 이미 오염된 적분 과정을 되돌릴 수 없다.

**Rev.2의 다음 문장을 이 섹션으로 교체(제거)**: "(A')는 그 50nm을 억지로
'진짜 initial oxide였다'고 재해석했을 때만 비율이 다시 2.37로 그럴듯해
보이는데... seed가 진짜 초기 oxide가 아니라는 것의 방증"이라는 서술은
2.37이 2.27과 "다르다"는 것을 근거로 삼았는데, 이는 부정확하다 — 관점
2(SOLVER_INTERNAL_SEEDED_STEP, ratio=2.318)가 보여주듯 seed 생성 **이후**
ViennaPS 성장 자체는 오히려 보존적이다. subtraction을 금지하는 진짜
이유는 위에 정리한 kinetics 오염(bare-Si 정답을 복원 못 함)이다.

## 구현 설계안에 포함할 원칙 (서술만, 코드 없음)

아래는 다음 라운드 설계를 위한 분석이며, 이번 라운드에서 구현하지 않는다.

1. **zero duration = P(0) = identity 계약.** Matrix 4에서 이미 실증:
   진짜 SiO2가 있으면 t=0은 자동으로 identity다(ViennaPS 자체가 그렇게
   동작). 문제는 bare Si에서 seed가 SiO2를 "만들어 버리는" 것 — 즉
   identity가 깨지는 지점은 "t=0 처리 로직"이 아니라 "seed를 만드는 이유"
   자체다. 향후 설계는 이 성질(ViennaPS가 실제 SiO2 존재 시 자동
   identity)을 재사용할 수 있는지, 아니면 명시적으로 t=0을 가로채 아무것도
   하지 않고 반환해야 하는지 — 후자를 택할 경우 "임시 if 우회"가 아니라
   geometry/material/provenance가 전부 그대로 보존되는 것을 테스트로
   증명해야 한다(Matrix 4의 identity 비교 방식을 그대로 재사용 가능).
2. **physical initial oxide ≠ numerical seed, 항상 구분.** 이번 조사의
   측정량 3분리(ambient_surface_displacement/total_oxide_thickness/
   silicon_consumed)와 보존 비율 확인이 이 구분을 검증하는 실제 방법임을
   보였다 — 앞으로 어떤 수정이든 이 세 측정량과 2.27 비율 체크를 회귀
   테스트로 남겨야 한다.
3. **physical initial oxide를 grid_delta에서 유도 금지.** Matrix 2가
   정확히 이 위반의 크기를 보여준다(같은 물리 레시피가 grid 하나로
   1.87x~5.39x 차이). 유도한다면 오직 온도/시간/oxidant 같은 물리
   파라미터, 혹은 recipe가 명시한 실제 초기 oxide 두께에서만 와야 한다.
4. **recipe에 없는 native oxide를 조용히 가정 금지.** thermal.py/
   locos.py 둘 다 이 원칙을 위반 중이다(레시피가 두께를 요청한 적 없는데
   silent하게 20~100nm가 생김).
5. **solver가 필요한 두께를 현재 grid로 표현 못하면 UNSUPPORTED_BY_MODEL로
   차단.** Matrix 1이 근거: grid=0.05에서 물리적으로 올바른 2nm seed는
   조용히 "정지"한다(에러도 경고도 없이 0.5hr을 시뮬레이트했다고 보고하며
   두께가 안 변함) — 이것이 현재 가장 위험한 실패 모드다(사용자에게
   보이는 것은 "정상적으로 끝난 산화 스텝"인데 실제로는 아무 일도 없었던
   것). 자동 refinement가 검증되기 전까지는 이 상황을 명시적으로 차단해야
   한다는 지침에 동의하는 실측 근거.
6. **numerical seed를 최종 geometry에 남기거나 두께에서 단순히 빼는 방식
   금지 — 이유를 실측으로 확인(Rev.3에서 근거 교체).** numerical seed는
   bare-Si 물질 보존을 깨지만(PHYSICAL_BARE_SI_ACCOUNTING, ratio=10.16),
   생성된 seed를 실제 초기 산화막으로 재해석하면 ViennaPS 내부 성장
   자체는 대체로 보존적이다(SOLVER_INTERNAL_SEEDED_STEP, ratio=2.318,
   2.27에 근접) — 즉 "성장 단계가 보존을 어긴다"는 것이 아니다.
   subtraction을 금지하는 핵심 이유는 보존비의 작은 잔차(2.369 vs 2.27)가
   아니라, **numerical seed가 Deal-Grove kinetics와 최종 Si 소비량 자체를
   이미 바꿔놓았다는 것**이다: bare-Si 정답은 0.020625um인데, seed-run
   원본(0.065196um)도 사후에 nominal 50nm를 뺀 값(0.015196um)도 둘 다 이
   정답을 복원하지 못한다(둘 중 어느 것도 0.020625um와 일치하지 않음) —
   최종 두께에서 숫자를 빼는 사후 보정으로는 이미 오염된 적분 과정
   (Matrix 2의 grid별 1.87x~5.39x 오염, `initial_dt`가 seed 크기에 따라
   달라지는 것 등)을 되돌릴 수 없다.
7. **대안별 비교는 다음 라운드 구현 설계 문서에서 수행.** 이번 라운드는
   조사만 수행하라는 지시이므로, "grid 자동 세분(refinement)" vs
   "UNSUPPORTED_BY_MODEL로 명시 차단" vs "recipe에 real initial oxide를
   요구" 등 대안별 geometry/kinetics/Si consumption/provenance 보존
   비교표는 실제 설계안 작성 시점에 채운다.

## 추가로 확인된, 아직 분류하지 않은 사실

- LOCOS의 `is_fresh_locos`/`is_chained_locos` 경로는 **thermal.py의
  seed 호출 자체는** 받지 않는다(가드로 스킵됨, Matrix 5 A/B에서 solver
  identity=True로 재확인) — **그러나 "fresh LOCOS는 영향 없다"고 결론
  내릴 수 없다**: 별도의 pad-oxide grid-floor 버그가 실측으로 확인됐다
  (바로 위 섹션, grid=0.05에서 미지정 pad oxide가 요청한 적 없는 50nm로
  조용히 부풀려짐 — thermal seed와 같은 클래스의 문제).
- `setInitialOxideThickness(0.0)`은 "산화막 없음"이 아니라 "영원히
  자라지 않는 degenerate 표면"을 만든다(Matrix 1) — 향후 설계에서 "seed를
  아예 안 만드는" 방법으로 0.0을 넘기는 시도를 하지 말아야 한다는 실측
  근거.
- (C) LOCOS on bare Si 경로는 `mask_material`이 recipe에 있으면 LOCOS의
  mask/oxide elastic-contact mechanics(contactMode=2)까지 함께
  활성화되어, 단순 grid-floor seed보다 더 복잡한 재구성이 일어나는 것으로
  보인다(SiO2 삼각형 범위가 seed 두께보다 훨씬 넓게 관찰됨) — 이
  mechanics의 정확한 영향은 이번 라운드에서 분리 규명하지 않았고,
  export 신뢰도 문제(위 Matrix 5 (C) 참조)와도 얽혀 있어 별도 조사가
  필요하다.

## 제약 준수 확인

- production 코드 수정: **없음.**
- `vps.Process` spy는 감사 스크립트(`investigate_v3_locos.py`/
  `investigate_v3b_fix.py`) 프로세스 내부에서만 `with` 블록으로 임시
  교체되고 블록 종료 즉시 원본으로 복원된다 — 어떤 production 파일에도
  monkeypatch가 저장되거나 남지 않음.
- 입력 0 우회/반올림/threshold 은폐: **없음**, 모든 수치는
  `results.json`/`results_v2.json`/`conservation_v3.json`/
  `results_v3_locos.json`/`results_v3b_corrected.json`의 raw 값.
- 비싼 Matrix 1~4 전체 재실행: **하지 않음** — 기존 raw export 좌표만
  재사용해 재계산(`conservation_v3.py`).
- 구현 착수 및 전체 회귀: **하지 않음.**
- 이 보고서와 추가 조사까지만 제출, 재검토 대기.

## HEAD / diff 확인

- `git diff --stat -- tcad/process/oxidation/` → **출력 없음(0건)**,
  `git status --porcelain=v1 -- tcad/process/oxidation/` → **출력 없음**
  (추적/미추적 변경 모두 0). `thermal.py`/`locos.py` 완전히 미수정.
- `git diff --check` → rc=0, 통과.
- `git rev-parse HEAD` → `3ba940404fd19c88eaaccc96a39ffe8444fb8851`,
  세션 시작 시점과 동일 — 커밋 없음.
