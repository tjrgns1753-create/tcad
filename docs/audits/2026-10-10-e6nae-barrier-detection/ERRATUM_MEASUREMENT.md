# 실행 전 측정 계약 정정

원본 PLAN은 변경하지 않는다. 최초 실행 38053776361의 FAIL도 보존한다.
`native_eps`는 같은 native 표면의 공정 전후 차이용이며 요청 좌표와
초기 측정 좌표의 비교용이 아니다. 최초 probe는 두 비교를 혼동했다.
기존 offset matrix에도 grid=0.1/top=0.3 조합은 없어 경험적 허용오차를
그대로 이 조합의 검증 근거로 확대하지 않는다.

입력, 공정, 9개 위치, 두께 검출 기준 0.01um은 유지한다.
수정 실행은 초기 요청 대비 offset을 값 그대로 기록하며 이것을 물리 성장이나
검증된 초기 위치 오차라고 승인하지 않는다(REQUEST_OFFSET_RECORDED_ONLY).
초기 9개 위치에 native oxide가 존재함을 확인하고, 식각 후 8개 보호 위치의
native oxide top을 실제 초기 reading과 기존 native_eps(8)로 비교한다.
열린 x=0에서는 Si와 SiO2의 실제 native top 차이를 같은 한계로 비교한다.
모든 native 배열과 export 원본을 assertion 전에 저장한다.
production/기존 PLAN/기존 raw/geometry/kinetics/gate 변경은 없다.
