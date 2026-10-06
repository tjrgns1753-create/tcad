# E6N-D2: 세 번째 메쉬의 제한적 추가 확인

이 계획은 첫 두 메쉬의 결과를 본 뒤 작성한 사후 확장이다. 원래 PLAN과
PILOT_NOT_APPROVED 판정을 수정하거나 소급 승인하지 않는다.
두 메쉬의 28 solve 성공에도 분포 오차 기준이 실패했고, 공통 x좌표에서도
역바이어스 캐리어 차이가 7.6%→2.0%로 남았다. 보간만으로 설명되지 않는다.

동일 물리 문제·공식 API·기존 production sweep·자원 supervisor만 사용한다.
새 모델, 이동도/수명/도핑/솔버/접점 변경, 메쉬 알고리즘 변경은 금지한다.
기존 E6N-A N2: E6K L2 x좌표, y 행 수 64, 122761 nodes/242304 triangles.
순·역방향 새 장치 각각 canonical 검사 후, 기존과 동일 10개 비평형 바이어스와
각 장치 초기 2 solve: 총 14 solve 예정. 각 장치 gate의 write/attempt=0 확인.
engine import보다 앞서 이 계획과 원래 계획의 LF 정규화 SHA를 대조한다.

판정 기준은 원래 PLAN의 수치 기준 그대로다. 새 메쉬가 실패해도 완화하지 않는다.
동일 L2 1D 참조와 전류/전위/log-carrier/수평 edge 전계를 비교한다.
N1→N2 J 상대차 forward<=1%, reverse<=2%. 실제 원시 N1 증거를 참조한다.
물리 승인 대신 FINE_PILOT_PASS 또는 FINE_PILOT_NOT_APPROVED로만 기록한다.
두 단계의 수치 추세로 모든 PN 수렴이나 공정 연속성을 승인하지 않는다.

물리 계산은 GitHub Windows 한 개 owned process tree에서만 실행한다.
900초, working set 6 GiB 샘플링, artifact 120 MB. timeout/cleanup 실패 시 차단.
기존 N0/N1을 재실행하지 않는다. production·gate·기존 원본 증거는 보존한다.
