# E6NY 활성화 미지원과 GUI 입력 미확보 구분: 실제 검증 통과

PLAN 6f0c515, 검증 입력 고정1e76c77, 실행576bc1b3ea6d66456675903ee88840f52b2ec890.
[원격 run](https://github.com/tjrgns1753-create/tcad/actions/runs/37981039050), artifact remote-run-74.
고정 검증 세 개 PASS, FAIL/TIMEOUT/ERROR/SKIP0. 새로운 물리 모델을 구현한 것은 아니다.

## 실제 변경

- source_context.py missing_device_profile_status: 엔진 없는 provenance 분류17줄.
- run_measurement의 last_doped_result None 분기: status와 reason 로그를 먼저 표시.
- 신규 unit은 실제 GUI 메서드 초입 AST로6반례를 재현/검증했다.
- canonical integration은 기존 assertion을 유지하고 B0의 reason/status/history를 강화했다.

기존 'no doping profile -> no carriers'는 잘못된 물리 설명이었다.
[공식 simple_physics.py](https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py)의
IntrinsicElectrons=n_i*exp(Potential/V_t), IntrinsicHoles=n_i²/IntrinsicElectrons에서
NetDoping=0도 운반자 부재를 뜻하지 않는다. 이것이 GUI intrinsic 측정을 승인하는 것은 아니다.

## 재현과 결과

수정 전6반례는 state가 있어도 status=SENTINEL을 남기고 has no carrier를 말했다.
수정 후 CHEMICAL/UNKNOWN/mixed는 DOPANT_ACTIVATION_MODEL_MISSING, 그 외
profile cache 없음은 DEVICE_PROFILE_NOT_AVAILABLE로 명시했다.
state와 history 무변경, field cache 제거, 엔진/Tk import0. 기존 source-context unit도 통과.

실제 GUI B0: solve/write/history0, UNSUPPORTED_BY_MODEL과 activation reason 기록.
실제 B1/B2: canonical 객체 유지, NetDoping mismatch0, history1, 정상 solve 유지.
anneal A: query None, solve/write0, 장치 누수0. 활성화·보상 transport gate는 해제하지 않았다.

verify_artifact.py가 실행 SHA/run, 입력11개, 고정3파일의 LF SHA, 원본6개 해시와
판정 equality를 대조하고 METRICS의 위 상태와 숫자를 독립 검사했다.
evidence_integrity_pass=true, suite_pass=true, 독립 재검사 엔진/Tk import0.

## 한계

영역별 activation 물리·intrinsic GUI 측정·PN·산화 지원은 새로 구현하지 않았다.
83개 unit baseline은 이전 W 실행 SHA에 대한 것이며 이번 추가로 전체84개를
모두 재실행했다고 주장하지 않는다. 이번에는 변경 관련 고정3검증만 실행했다.
X에서 실패한 기존 donor/acceptor 테스트는 assertion 수정 없이 그대로 남는다.
모델·농도·geometry·엔진 내부·main 무변경. 상세 semantic diff는 실행 커밋에 있다.
