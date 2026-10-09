# 최초 E6N-U 실행의 설계 오류와 실제 FAIL 보존

실행 d6c1f1393170380cd88406c90265b6b50ebbd9ad,
run https://github.com/tjrgns1753-create/tcad/actions/runs/37976122403,
artifact remote-run-69는 **FAIL**이다. 이를 사후 기준 변경으로 PASS로 바꾸지 않는다.
원본 `raw_initial/` 및 최초 PLAN/구현 커밋을 그대로 보존한다.

첫 네 요청 n_single/p_single ±1mV는 각각 3 solve로 정상 계산됐다(총12회).
다섯 번째 n_comp_da_pos는 기존 COMPENSATED_TRANSPORT_MODEL_MISSING 계약으로
실제 GUI가 차단했고, 기대한 결과 snapshot이 없어서 감사 스크립트 assertion이 실패했다.
나머지 일곱 요청은 실행되지 않았다. 전체 verdict.json은 없고 생성하지 않는다.

최초 PLAN이 보상 도핑을 계산 가능한 production 대조군으로 가정한 것이 잘못이다.
이미 `canonical_node_doping`은 donor+acceptor의 양의 면적 공존을 region-level에서
차단한다. canonical ND/NA/net 농도는 유지되지만 transport 숫자는 승인하지 않는다.
상수 이동도 모델의 수학적 해석식을 유도할 수 있다는 사실이 현재 게이트를 통과할
권한은 아니다. 게이트·엔진·production은 수정하지 않는다.

부분 자료에서 관측된 p형 +1mV source 전류는 8.000000000023121e-5 A/cm,
-1mV는 그 반대 부호이며 n형의 약 0.5배다. 이는 부분 관측으로만 보고하며,
원래 전체 62개 판정이 통과했다거나 보상 도핑 결과가 계산됐다고 주장하지 않는다.

후속 실험은 별도 PLAN_BOUNDARY로 사전 고정한다. 단독 p/n는 수치 물리 비교,
보상 도핑 8요청은 농도 보존과 solver/write/map/export 차단 증거로 분리한다.
최초 실패 시 보상 분기의 호출 counters는 JSON에 저장되지 않았으므로 로그의
차단 안내만으로 실제 호출수 0을 독립 증명했다고 말하지 않는다. 후속 실험에서
실제 카운터를 기록한다. 원래 원격 solve 결과는 다시 쓰거나 수정하지 않는다.
