# E6NX 실제 GUI 통합 회귀: 2 PASS / 1 FAIL

계획 1191fd2, 실행 014d012957407e7401603cec573894299a2f9833.
[원격 run](https://github.com/tjrgns1753-create/tcad/actions/runs/37980319550), artifact remote-run-73.
부모 18.829초, TIMEOUT/ERROR/SKIP 각각0. 세 script를 각 한 번 실행했고 기존 assertion은 수정하지 않았다.

## 실측

- canonical gate 5.516초 PASS. GUI CHEMICAL 기록은 측정0/write0/history0.
  명시적 ACTIVE Gaussian+window 누적은 solve 호출7회, 실제876노드의 NetDoping과
  canonical/독립 attachment 합의 오차0. Gaussian이 실제 필요한 노드454개.
  양단 로그 전류 ±0.002670276 A/cm. 이는 비균일 donor 저항의 상태 전달/KCL 검사이며
  독립 해석해·mesh convergence·PN 승인은 아니다.
  anneal 후876노드 전부 UNRESOLVED 차단, query None, solve/write/history0.
  uniform 대조군126노드, solve3회, NetDoping 오차0, 전류 ±0.0016 A/cm.
- headless10.531초 PASS. zero-time materialization/identity, 실제 Bosch 식각과 SiO2
  증착, positive-time 산화 refusal, 워커 검증 예외가 정상 분리됐다. 전체 모달0.
  Si 상단 하강0.069~0.091um은 관측값이며 정확 깊이 법칙 검증으로 주장하지 않는다.
- donor/acceptor2.500초 FAIL, 기존148행. ND1e16/NA5e15 입력의 재부착 후
  COMPENSATED_TRANSPORT_MODEL_MISSING으로1326노드가 차단됐는데 테스트가
  Measurement: Voltage source 성공 문구를 요구했다. 보상 transport 미지원 gate는
  올바르게 적용됐고 이를 통과시키려고 물리 코드를 바꾸지 않는다.
  이후 Gaussian/window/barrier 부분은 미도달이다. 후속 coverage를 통과로 집계하지 않는다.

## 독립 대조

verify_artifact.py는 engine/Tk import를 금지하고 실행 SHA/run, 입력12개와 세 script
LF SHA, 원본6파일 크기/SHA, 각 로그SHA와 skip 여부, records→verdict equality를 확인했다.
evidence_integrity_pass=true, suite_pass=false. 원본 실패를 PASS로 치환하지 않았다.

같은 파일별 최신 baseline이 없어 NEW_REGRESSION/PRE_EXISTING의 확정 분류는 하지 않는다.
production/기존 테스트/모델/gate 변경0. 전체 regression 및 기존 PN 감사 반복0.

## 별도 발견

canonical B0는 CHEMICAL attachment를 갖지만 last_doped_result가 없어 초기 return 한다.
로그의 측정 단계에서 UNSUPPORTED/last_physics_status가 없고, 기존 안내는
도핑이 없으면 운반자가 없다고 말한다. 이는 물리적으로 부정확한 UI 설명이다.
활성화 미지원과 GUI device input 미확보를 구분하는 최소 보완을 E6NY로 진행한다.
원래 donor/acceptor 테스트의 전체 migration은 후속 과제로 남기며 부분 검사를 전체
barrier 통합 검증으로 바꾸지 않는다.
