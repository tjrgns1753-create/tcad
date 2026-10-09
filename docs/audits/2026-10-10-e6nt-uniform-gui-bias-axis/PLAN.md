# E6N-T: 실제 GUI 균일 Si의 전압·접점·측정 방향 대조

시작 HEAD dcf7b3c. 이번에는 production 수정 없이 실제 물리 검증 범위를 확장한다.
엔진은 GitHub-hosted Windows에서만 import/solve한다.

## 고정 물리 문제

기존 E6I one_sided_8 mesh와 canonical(path, ACTIVE)를 그대로 재사용한다.
단일 Si 2µm × 0.5µm, donor 1e16cm^-3 / acceptor 0, 300K,
공식 Poisson + Scharfetter-Gummel DD, 기존 이동도·SRH·solver 설정 불변.
공식 식 근거: DEVSIM python_packages/simple_dd.py / simple_physics.py.
부호 및 affine 전위는 같은 uniform 문제에서만 판정한다. 실제 PN의 지수 I-V
또는 MOS 반전 모델을 이 저항의 해석식으로 판단하지 않는다.

## 사전 8개 실제 GUI 요청

1. x / max source / +1mV
2. x / max source / -1mV
3. x / max source / 0V
4. x / min source / +1mV
5. y / max source / +1mV
6. y / min source / +1mV
7. y / max source / -1mV
8. y / max source / 0V

매번 fresh 장치와 canonical 상태를 사용한다. 각 3 solve, 총 24회 예산.
기존 GUI는 import axis extrema의 두 접점을 사용하며 이름을 실제 반환에서 확인한다.
창·도핑·메쉬·물리 파라미터를 결과에 맞춰 이동하거나 조정하지 않는다.

## 사전 해석 기준 (기존 E6I 기준을 재사용)

native q/n_i/mu_n/mu_p/T/수명이 기존 EXPECTED_PARAMS와 같은지 확인한다.
기존 resistor_judge.theory로 n0,p0와 sigma=q(mu_n*n0+mu_p*p0)를 계산한다.
축 방향 length와 수직 height는 실제 node 좌표 범위에서 구한다.
G=sigma*height/length는 A/(V·cm), I_source=G*V, I_ground=-G*V다.
x: height=.5µm / length=2µm; y: height=2µm / length=.5µm.
따라서 동일 +1mV에서 y/x 전류비 기대값은 16이며 재료 물성을 바꾸지 않는다.

- 비영 bias 전류 해석식 상대차 <=1% (TOL_CURRENT).
- KCL |Is+Ig|/(G*1mV) <=1e-6 (TOL_CONSERVATION).
- 0V |I|/(G*1mV) <=1e-4 (TOL_EQUILIBRIUM); 0으로 강제 교체하지 않는다.
- 모든 node carrier finite/양수. n/n0 변화 <=1e-4 (TOL_N_UNIFORM).
- affine Potential 최대차 / max(|V|,1mV) <=1e-2 (TOL_PSI_LINEAR).
- 역부호/접점교환/축전환 차이는 해당 해석 기준과 함께 수치로 제출한다.
- 실제 GUI 성공 로그·단위 A/cm·caption 두 전압·73 node 표시·JSON
  전체 snapshot/point equality·실패/누락 결과 없음·device cleanup 확인.

## 실행과 증거 경계

순수 judge는 엔진 없이 합성 정상/부호 오류/축 길이 오류/NaN/누락 기록을 차단한다.
parent resource supervisor, child 150초, profile 400초, artifact 8MB.
전체 regression, 기존 PN 재실행, gate 해제, main 병합, production 물리 변경 없음.
결과가 안 맞으면 원시 자료를 그대로 제출하고 기준 완화하지 않는다.
24 solve는 단일 저항의 8개 요청 검증이지 모든 TCAD 케이스 승인 숫자가 아니다.
