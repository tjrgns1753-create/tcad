# E6N-AH 완료: 물성 가정의 실제 기록과 GUI/저장 연결

## 판정
MODEL_EVIDENCE_RECORDED. 재료 calibration, 임의 농도/전계/온도, PN 일반 검증은 아니다.
실제 remote run38056456986 / source157d382918f309fcbd7e9a97051113fbcd04605b.
92 PASS / 0 FAIL / 0 TIMEOUT / 0 SKIP,170.617초. 새 unit1+기존 unit87+
실제 integration4. 기존87의 파일 해시 동일 PASS→PASS87. gate 변경0.

## 구현 전/후
새 unit을 구현 전 실행: helper 부재 ModuleNotFoundError로 실제 FAIL.
후: 실제 public API 반환값11개 그대로 기록;88개 누락/invalid 반례 거부.
pn/robust DD setup 직후 get_parameter, DD solve 전에 결손을 차단한다.
실제 get_parameter observer와 결과 metadata 및 JSON/CSV companion 일치를 확인.
GUI log와 notify도 동일 metadata formatter 사용. 가짜 기본값/zero를 만들지 않는다.

## 실제 물리 대조군
| 입력 | solve | source 전류(A/cm) | 확인 |
|---|---:|---:|---|
| n=1e16cm⁻³ |3|0.0016|기존 fixed-model 결과 유지|
| p=5e15cm⁻³ |3|0.0004|기존 fixed-model 결과 유지|
| known-undoped |3|2.4e-10|기존 analytic validator 통과|
| n_i 누락 주입 |1|보고0건|Poisson 이후 DD0, 이전 fields/history 성공0|
| mu_n NaN 주입 |1|보고0건|Poisson 이후 DD0, 이전 fields/history 성공0|

실제 parameter: T300K,mu_n400/mu_p200cm²/(V·s),n_i/n1/p1=1e10cm⁻³,
taun/taup=1e-8s,q1.6e-19C,eps9.8235e-13F/cm,V_t0.025887193125V.
엔진을 통해 읽은 값이지 새로운 실리콘 보정값은 아니다.
공식 simple_physics는 상수 parameter라고 명시한다:
https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py
Caughey–Thomas(1967)의 도핑/전계 의존 이동도 연구 범위와 비교해
고정 이동도가 모든 조건의 실제 Si를 보장한다고 일반화하지 않는다.
논문은 초록/서지만 확인했고 fitting coefficient를 적용하지 않았다.

## Serena 조사 및 호출 범위
도구 미노출, rg/직접 읽기 대체. pn_junction_iv_sweep는 GUI/CLI/pn_reference,
robust_iv_sweep는 GUI 및 실제 canonical-state control에서 호출.
semiconductor_equation 공식 helper와 setup SRH override는 변경 없음.
io.save_json/save_measurement_bundle는 기존 metadata serialization을 그대로 재사용.
MOS/Ohmic 별도 생성자는 새 transport provenance를 임의로 덧붙이지 않았다.

## 변경 diff
transport_evidence.py 신규: actual capture/validation/한국어 formatter.
pn_junction_iv_sweep.run_pn_junction_iv_sweep 및 robust 대응 함수:
import + setup 직후 capture + metadata.transport_model 각3줄.
TCADApplication.run_measurement: helper import, parameter 오류 status 분기,
로그/notify의 같은 model note. 실제 식/tolerance/단위/전류는 변경0.
전체 production diff는 IMPLEMENTATION.patch에 보존한다.
새 unit 및 실제 GUI integration은 기존 파일 assertion을 완화하지 않았다.

## 독립 검증
verify_artifact.py: source/run id, 원격 runner, inputs9의 Git blob/checkout 개행,
outputs94의 바이트 SHA/size, run.log SHA, 파일92개 exact set, 각 파일의
source LF SHA/log SHA/cleanup/skip, 기존87 baseline 비교를 별도로 확인.
5개 mutant(단위삭제/calibration허위/실패전류보고/실패기록삭제/NaN) 전부 차단.
raw_initial은 원본 artifact로 보존, .gitattributes -text -diff.
실제 GUI각 measured device 정리 및 modal0. 실제 엔진은 원격에서만 실행.
git diff --check 코드범위 RC0. main/gate/엔진 내부 변경0.

## 이어서 해결할 화면 문제
물리장 caption에는 calibration 한계가 아직 없다. AI에서 짧은 범위 안내를
연결하고 실제 canvas item으로 검증한다. AH의 수치 결과는 변경하지 않는다.
