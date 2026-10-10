# E6N-AH 사전 조사: GUI 전류의 모델 가정과 실제 Si 검증 분리

읽기 전용 조사. 새 solve/engine import/물리 코드 수정 없음.
AF/AG의 성공을 고농도/고전계/임의 온도의 실제 Si 전류 승인으로 확대하지 않는다.

## 소스에서 확인한 사실
`tcad/device/devsim/semiconductor_equation.py`는 공식
SetSiliconParameters/CreateSiliconPotentialOnly/CreateSiliconDriftDiffusion
helper를 사용한다. 엔진 내부를 수정한 것이 아니다.

설치본 `devsim/python_packages/simple_physics.py`의 기본값은
mu_n=400,mu_p=200 cm²/(V·s), n_i=1e10cm⁻³.
SetSiliconParameters는 이를 상수 parameter로 등록하고 T는 kT/V_t 계산에 쓰며,
온도에 따른 이동도/n_i model을 제공한다고 주장하지 않는다.
공식 저장소의 동일 함수도 constant parameters라고 명시한다.
https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py

프로젝트 setup_drift_diffusion_equation은 taun=taup=1e-8s로 덮어쓴다.
현재 주석의 근거는 예제값 및 수렴 개선이다. 그것만으로 특정 제작 Si의
실측 lifetime이라고 승인할 수 없다. uniform mass-action 대조군의 성공과
재결합이 중요한 PN 특성의 정량적 물성 검증은 구분해야 한다.

현재 pn_junction_iv_sweep의 metadata는 temperature/physics/units를 기록하지만
실제로 사용한 이동도/n_i/SRH lifetime 및 calibration provenance는 기록하지 않는다.
GUI 최종 전류 출력도 단위는 설명하지만 해당 물성 가정을 함께 보여주지 않는다.
따라서 software/API 사용과 실제 재료의 정량적 유효성이 혼동될 여지가 남는다.

## 논문 대응
Caughey & Thomas, Proceedings of the IEEE55(12),2192–2193(1967),
DOI10.1109/PROC.1967.6123. 실리콘 이동도의 도핑·전계 의존 실험 관계를
다루는 논문이므로 고정 이동도를 모든 농도/전계에 일반화할 근거로 쓸 수 없다.
https://ieeexplore.ieee.org/document/1448053/
여기서는 공식 초록/서지 및 코드 범위를 대조했다. 논문 전체의 fitting
coefficient를 학습·검증했다고 주장하거나 새 계수/지원 임계값을 만들지 않는다.

공식 DEVSIM은 사용자 model과 이동도 model을 연결하는 예제를 제공한다.
https://github.com/devsim/devsim/blob/main/examples/mobility/gmsh_mos2d.py
다만 해당 예제를 연결하는 것만으로 이 프로젝트의 mesh, 농도 범위,
고전계, PN 수렴 및 재료 calibration이 자동 승인되는 것은 아니다.

## 다음 구현의 우선순위
1. 실제 API get_parameter로 사용된 mu_n/mu_p/n_i/T/taun/taup를 cleanup 전에
   capture하여 CharacterizationResult metadata와 GUI/JSON에 같은 값으로 기록.
2. fixed-mobility/Boltzmann/SRH assumptions와 재료 calibration 미검증을 표시.
   수렴=True나 기본예제값을 물리 보장이라고 승격하지 않는다.
3. 고농도/고전계 지원조건은 문헌 구성방정식 및 기존 실제 검증 범위를
   조사해 별도 사전 기준을 세운 후 gate 또는 공식model 재사용으로 해결.
   통과 사례에 맞춰 arbitrary threshold/계수/tau를 조정하는 것은 금지.

이번 조사에서는 위 구현을 아직 하지 않았다. 생산 변경은 AF의3개 파일뿐이며
원격 수치 검증은 고정 low-bias pure n/p 모델 조건으로 한정한다.
