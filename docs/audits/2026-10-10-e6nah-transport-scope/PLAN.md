# E6N-AH: 실제 transport parameter 기록과 화면·저장 일치

사전 기준. 수치 모델·계수·수렴 tolerance·canonical gate는 바꾸지 않는다.
로컬은 소스/합성 검사만, 실제 엔진/Tk 시험은 GitHub-hosted Windows만.

## 물리 질문
계산이 수렴했다는 사실과 실제 제작 Si의 물성이 검증됐다는 사실은 다르다.
현재 공식 simple_physics의 상수 이동도, Boltzmann 통계, SRH 수명을
그대로 기록한다. 논문 fitting 계수나 고농도/고전계 지원 경계는 만들지 않는다.
공식 근거: https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py
논문 범위 근거: Caughey–Thomas(1967), DOI10.1109/PROC.1967.6123
(초록/서지만 확인, 전체 계수 검증 주장 금지).

## 허용 변경
새 엔진 독립 transport_evidence helper; pn/robust DD 생성자에서 DD 설정 직후
실제 public get_parameter로 T, mu_n, mu_p, n_i, taun, taup, ElectronCharge,
Permittivity, V_t, n1, p1을 읽는다. 값·단위·공식 helper 출처·프로젝트 lifetime
override·재료 calibration 미검증을 metadata.transport_model에 남긴다.
이 API가 없거나 parameter 누락/비유한/비양수/boolean/비숫자이면 ValueError,
DD solve 전에 중단한다. 이미 수행한 Poisson solve를 0회라고 말하지 않는다.
화면 설명은 metadata에서만 포맷한다. 미기록/invalid 모델은 검증됐다고 표시하지
않는다. JSON/CSV sidecar는 기존 full-metadata 경로를 재사용한다.
다른 MOS/Ohmic 생성자는 이번 지원 범위 밖이며 모델 미기록 설명만 허용한다.

## 반례와 대조군 (결과 전에 고정)
1. 현재 소스에 transport 기록이 없음을 AST 확인. 새 테스트를 구현 전 실행하면
   helper 부재로 실패해야 한다. 누락 parameter를 정상 기본값으로 바꾸면 안 된다.
2. engine-free fake public API: 실제 반환값 그대로 기록, 11개 값·단위·API identity,
   계수 변경 0. missing/None/NaN/Inf/0/negative/bool/string 거부.
3. 실제 GUI uniform n(1e16), p(5e15), known-undoped, 4×1um, grid0.2,
   x contact/max source. n/p V0.01, intrinsic V0.001 (기존 5V/cm 범위).
   실제 get_parameter spy 기록 = 결과 metadata = JSON/CSV sidecar;
   실제 GUI log/notify는 같은 helper 설명 포함; delete 전에 capture;
   기존 n/p source 전류 +0.0016/+0.0004 A/cm 대비 상대오차≤1e-6;
   intrinsic은 기존 analytic validator 그대로. modal 0, leaked devices 0.
4. 실제 GUI parameter fault n_i 누락 및 mu_n NaN: 두 경우 측정 성공 문구,
   전류/fields/history/result 0건. Poisson 호출 횟수와 DD 차단을 실제 spy로 기록.
5. 기존 donor/acceptor 7-case, canonical real, headless real, intrinsic real을
   각 한 번. 새 unit+기존 AG 87개를 동일 subprocess 격리로 원격 실행.
   파일별 60초, integration120초, 총 profile900초. timeout/fail/skip 숨기지 않는다.

## 완료와 범위 제한
결과 SHA/PLAN/input/log/output 해시를 독립 대조하고 첫 실패 artifact 보존.
Serena 도구 미노출: rg/직접 파일 조사. pn/robust→GUI/CLI/1Dreference 호출 확인.
보상/chemical/anneal/positive oxidation/general PN gate 유지.
PASS는 모델 가정 기록·기존 대조군 회귀 확인일 뿐 실제 재료 calibration 승인이 아니다.
