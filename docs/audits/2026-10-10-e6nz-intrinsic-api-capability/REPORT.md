# E6NZ 무도핑 Si 공식 API capability: 열적 운반자와 저전계 전류 확인

PLAN 단독 고정8900cf9, 실행79ea8e3a56034f28eaa832e53b8f2e3c370b46a4.
[원격 run](https://github.com/tjrgns1753-create/tcad/actions/runs/37981805856), artifact remote-run-75.
세 fresh device에서 production sweep 총9회 solve, 사전56기준 전부 통과.
별도 None/UNRESOLVED canonical 입력2건은 write0/solve0으로 거부됐다.

## 물리 실측

explicit known-undoped Si 2×0.5um, E6I one_sided8 mesh73노드.
ProcessResult.doping은 None이며 가짜 zero DopingProfile/attachment를 만들지 않았다.
canonical state가 정확한 초기 bounds에서 알려진 ND=NA=0을 전달했다.
모든 donor/acceptor/net node값0, canonical before/after0, attachment0 유지.
전체73개 Electrons와 Holes는 각각1e10 cm^-3, 기준 n_i 대비 오차0.

| 전압 | 실제 전류 A/cm | 해석 전류 A/cm |
|---|---:|---:|
| 0V | 0 | 0 |
| +1mV | 2.4000000000000005e-10 | 2.4e-10 |
| -1mV | -2.4000000000000005e-10 | -2.4e-10 |

sigma=q*(mu_n+mu_p)*n_i, I=sigma*(H/L)*V.
이때 q1.6e-19, n_i1e10, mu_n400, mu_p200, 300K는 실제 설치된 모델에서 읽었다.
electron fraction2/3, hole fraction1/3와 KCL/affine Potential/양극성 기준을 통과했다.
이 비율은 해당 constant-mobility 모델의 결과이지 실제 모든 Si의 보편 값이 아니다.

공식 근거:
[simple_physics.py](https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py)의
IntrinsicElectrons/IntrinsicHoles, contact root, mobility와
[simple_dd.py](https://github.com/devsim/devsim/blob/main/python_packages/simple_dd.py)의 공개 DD 구성.
무도핑을 운반자 부재로 취급하는 것은 틀리지만, 미지 농도를 무도핑으로 대체해도 된다는
의미는 아니다. UNRESOLVED/None 반례를 함께 차단한 것이 핵심이다.

## 독립 검증

verify_artifact.py는 engine/Tk import 금지하에 실행 SHA/run, 입력14개와 원본6개
해시/크기, 고정 PLAN 해시를 확인하고 실행 커밋의 judge를 그대로 재판정했다.
56 checks equality, source current 부호 및 대칭, 실제 x/y extent2×0.5um,
전체73n/p 배열, 9solve와 장치/메쉬 cleanup을 대조했다.
evidence_integrity_pass=true, pilot_pass=true, engine_imports0.
추가 height 대조는 고정 geometry의 일관성 검사이며 원격 verdict/tolerance를 고친 것이 아니다.
합성 대조군과7개 오류 입력은 별도 테스트이며 실제 물리 결과로 집계하지 않는다.

## 정확한 범위

공식 DEVSIM API와 기존 import/apply_doping/sweep만 사용했다.
모델·계수·lifetime·solver tolerance·production·GUI·물리 gate 무변경.
초기 capability 스크립트에서 state.advance 메서드로 잘못 작성했던 호출은 원격 실행 전
기존 전역 advance(state,None,step_seed='etching') API로 정적 교정했다.
실제 원격 재실행은0회, 계산은 로컬에서 실행하지 않았다.

**GUI intrinsic 측정은 아직 미지원**이다. 현재 GUI 입력 branch의 refusal은 유지한다.
이 실험은 초기 known-undoped rectangle의 engine capability를 보여줄 뿐 임의 공정 순서,
PN, 고전계, 다중 재료, mesh 수렴 또는 intrinsic GUI source provenance를 승인하지 않는다.
다음 구현은 가짜 DopingProfile 없이 known-undoped canonical 입력만 GUI에 연결하고,
실제 전체 node/current/geometry 해석 검사를 통과한 결과만 렌더·export하는 작업이다.
