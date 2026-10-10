# E6N-AK 자동 색 범위의 물리적 오해 방지

## 반례와 기준

현재 caption의 .4e 표기로 1e16과 1e16+2 cm^-3가 둘 다 1.0000e+16으로 표시된다. 실제 선형색은 파랑과 빨강으로 나뉜다. 시각 대비가 물리적으로 큰 변화라는 인상을 줄 수 있다.

값/색/노드/방정식/gate를 바꾸거나 잡음 판정 threshold를 만들지 않는다. 표현만 고친다. 양 끝 값을 float64 왕복 가능한 17자리로 표시하고 Δ 및 Δ/max(|lo|,|hi|)를 함께 표시한다. 모두 0이면 상대 변화는 0으로 정의하되 zero 농도를 발명하지 않는다. 원시 Potential의 상대 범위는 기준 전위 의존임을 명시한다. 모든 layer에 '자동 색 확대; 물리적 유의성 보장 아님'을 넣는다.

엔진 없는 unit: 미세 양수 범위, 완전 균일, all-zero, 음/양 전위, node 배열·색 불변. 기존 caption/scope/node unit을 유지한다.

실제 검증은 GitHub-hosted Windows만: 기존 n/p/intrinsic×3 actual canvas test를 그대로 실행해 9장 caption 완전 포함/배열/색/좌표 불변을 확인한다. 기존 transport evidence GUI control도 실행한다. 총 신규 unit 1 + 기존 unit 3 + real 2 = 6개, timeout 각 120초/전체 360초. 기존 94개 전체 회귀를 중복 실행하지 않는다.

결과 전 이 PLAN을 커밋한다. 기존 raw 증거와 기존 PLAN은 수정하지 않는다. 구현 범위는 node_fields.py의 caption 및 신규 unit, audit/profile/request뿐이다. 전류 및 물성 calibration 승인 아님.
