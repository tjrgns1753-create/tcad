# E6N-A 보완 합성 기준 — 엔진 실행 전 고정

기존 PLAN은 수정하지 않는다. 기존 witness 문턱도 바꾸지 않는다.

## fixture와 예상 판정

좌표는 cm이다. x={-1e-5,0,1e-5}, y 범위 [-1e-5,0].
정상 fixture는 y 4등분인 tensor grid이다. 모든 x=0의 제어체적 정규화
x 연산자는 같으므로 INCONCLUSIVE를 예상한다(불변성 일반 증명은 아님).

전이 fixture는 왼쪽 strip을 y 4등분, 오른쪽을 2등분한다.
오른쪽 각 직사각형을 왼쪽 변의 중점을 공유하는 3개 직각/비둔각
삼각형으로 연결한다. 폭=1e-5, 높이=5e-6이므로 전이 비둔각 조건
w>=h/2를 충족한다. x=0의 midpoint와 coarse vertex는 서로 다른
오른쪽 투영 가중치/제어체적을 가진다. 기존 네 polynomial 중
이차 작용과 exact projected row의 차이로 NONINVARIANCE_WITNESS를 예상한다.
이는 수학적 합성 대조군이며 PN·공정 검증이 아니다.

동일 fixture의 좌표를 s=1e-6으로 축소하면 stencil coefficient는 여전히
다르지만 고정 L=0.004cm의 polynomial 작용/row scale 비가 기존 문턱보다
작아진다. 따라서 stencil-only 반례는 INCONCLUSIVE를 예상한다.
좌표 단위나 실제 E6N 후보는 바꾸지 않는다.

정상 fixture EdgeCouple에 float64 1 ULP 변화만 주면 INCONCLUSIVE를 예상한다.
EdgeLength와 EdgeCouple 동시 2배, 누락, 잘못된 endpoint는 차단한다.
endpoint 방향 반전은 정상이고, 비교 node 없는 메쉬는 NOT_MEASURED다.

## 새 길이 무결성 기준

공식 EdgeLength 정의는 두 endpoint 사이 거리다(DEVSIM models.html 표5.2).
동일 저장 좌표에서 hypot으로 다시 계산한다. 허용 상대 차이는 64*eps64.
float64 subtraction·곱/합·sqrt의 소수 연산 roundoff보다 여유 있는
진단 기준이다. 엄밀한 native 전체 오차 정리나 원래 좌표 복원은 아니다.
절대 길이 floor는 없고 길이 0/비유한은 차단한다. 이 새 증거 검사 기준은
기존 witness/물리 tolerance를 완화하지 않는다. 실제 wheel 대응은 아직 미측정이다.

## 자원 정책 변경 승인 전

시간·메모리의 사후 검사 문제는 기존 단일-process 구조에서 해결됐다고
주장하지 않는다. 별도 RESOURCE_POLICY_PROPOSAL.md를 검토하기 전 원격 재실행 금지.
