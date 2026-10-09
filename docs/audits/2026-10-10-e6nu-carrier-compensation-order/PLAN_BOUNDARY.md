# E6N-U2: 단독 p/n 수치 검증과 보상 transport 차단을 분리한다

시작 HEAD bccc1a0. 최초 U1의 FAIL은 그대로 보존한다. 원래 PLAN을 수정하지 않는다.
새 실험의 판단 대상은 "보상 전류 계산"이 아니라 다음 두 분리 계약이다.

1. n_single/p_single 각각 ±1mV: 실제 GUI→DEVSIM의 저항 해석해와 비교.
2. n_comp_da/n_comp_ad/p_comp_ad/p_comp_da 각각 ±1mV: canonical ND/NA/net와
   순서 보존, COMPENSATED_TRANSPORT_MODEL_MISSING로 0 write/0 solve/0 field capture,
   성공 숫자·map·export 없음. 총12요청 중 수치 계산은4개×3=12 solve 예산.

이미 코드에 있는 compensated_transport_problems와 canonical_node_doping의
region-level capability gate를 수정하거나 우회하지 않는다. 실제 저항 식을 만들 수
있다는 이유로 같은 노드의 donor/acceptor를 net-only로 숨겨 gate를 통과시키지 않는다.

단독 프로필 수치 기준은 최초 PLAN의 q/ni/mu/T/geometry, I=GV1%, KCL1e-6,
majority1e-4, affine Potential1e-2를 그대로 재사용한다. p/n 전류비0.5도 확인한다.
모든 native donor/acceptor/net 배열, 전체73노드 fields와 JSON equality를 기록한다.

보상 프로필의 ND/NA/net는 요청합을 그대로 유지해야 한다. 이는 numeric canonical
농도를 알려준다는 뜻이지 transport를 승인한다는 뜻이 아니다. 차단 전/후 모든73개
지점 query와 attachment 수, 상태 객체 identity를 확인한다. 명시적 입력 순서를
records에 보존한다. 양쪽 순서의 최종 농도가 같고 transport refusal reason도 같아야 한다.
미지원 transport에 전류나 carrier 배열을 만들어 채우지 않는다.

실제 base.Observer로 solve 시도와 doping write를 기록한다. capture callback 카운터는
공개 API read 시작 전에 센다. 차단 이후 export를 눌러도 저장 dialog0회/파일없음,
field3레이어 노드0개, history증가0, 성공 블록없음, device cleanup이어야 한다.
export 차단 안내 오류는 측정 자체의 거절 오류와 따로 기록한다.

순수 judge는 실제 지원/차단 기록을 서로 바꿔도 PASS가 안 되도록 합성 반례로 확인한다.
누락 case, compensation collapse, 1 solve, 1 doping write, fake current, fake field,
반대순서 ND/NA 훼손을 차단한다. 부재는 None이며 전류0으로 대신 채우지 않는다.

조사·합성 테스트는 로컬, 실제 엔진/Tk/solve는 GitHub-hosted Windows만.
matrix child180초, parent500초, artifact12MB. PLAN hash를 engine import 전에 검사한다.
production·gate·engine 내부·기존 원본·전체 회귀·main은 변경하지 않는다.
