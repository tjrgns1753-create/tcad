# 합성 예상 판정 정정 — 최초 실패 보존

SYNTHETIC_REVIEW_CRITERIA.md의 전이 fixture 예상은 틀렸다.
최초 실행에서 정상 INCONCLUSIVE 뒤 전이 NONINVARIANCE_WITNESS assertion이 실패했다.
측정 값: 이차 pair 차이 1923.0769230769074, row scale 약6.8e11.
고정된 상대 문턱 1e-8*scale는 약6800이므로 witness를 충족하지 못한다.
exact projected row 차이는 비영이다. 즉 stencil 차이와 충분한 witness는 다르다.

메쉬 좌표·연결·물리 L·문턱은 변경하지 않았다. 잘못된 기대 assertion만
INCONCLUSIVE로 정정했고, exact 차이와 polynomial 차이가 실제 존재함을 추가 검사한다.
이 원 fixture와 축소 fixture는 모두 stencil-only 음성 대조군이다.

원래 요구한 전체 analyze 경로의 NONINVARIANCE_WITNESS 양성 대조군은
아직 충족하지 못했다. scalar classify 양성 테스트를 이것의 대체로 인정하지 않는다.
결과에 맞춰 fixture 크기를 확대하거나 tolerance를 낮춰 양성으로 만들지 않는다.
원격 실행 승인 전 별도 사전 계산/고정 fixture 검토가 필요하다.
