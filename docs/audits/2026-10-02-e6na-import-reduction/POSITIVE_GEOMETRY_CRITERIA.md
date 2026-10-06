# E6N-A 별도 양성 기하 대조군 — analyze 실행 전 고정

## 목적과 경계

기존 실패 fixture의 좌표·연결·기대 판정은 수정하지 않는다.
이 대조군은 가로 방향 coarse/fine 전이를 갖는 별도 소형 직사각형 메쉬다.
기존 fixture의 uniform scaling이 아니다. 추가 fine/coarse strip과 회전된 전이 방향을 사용한다.
표준 RGB/NVB나 새 remesher가 아니며, 손으로 지정한 합성 삼각분할이다.
N0/N1/N2, PN domain, 도핑, 접점, 물리 파라미터는 변경하지 않는다.
이 합성 domain은 실제 PN 후보의 형상이나 깊이를 재현하지 않는다.

## 좌표·연결의 완전한 정의

좌표 단위 cm. h=2^-12cm, a=2h, L=0.004cm (기존 기준 유지).
binary h는 float 저장 좌표를 정확한 dyadic rational로 유지하기 위한 선택이다.
기하 정의와 예상식을 고정한 뒤 단일 시험만 수행한다. 결과를 보고 h를 조정하지 않는다.

먼저 보조 (u,v) 좌표를 정의한다.
- fine 열 u=-2a,-a,0: 각 v=0,h,2h,3h,4h. index=5*열번호+v/h (0..14).
- coarse 열 u=a,2a: 각 v=0,2h,4h. index=15+3*열번호+v/(2h) (15..20).
- 최종 좌표 (x,y)=(v-h,u). 영역 x=[-h,3h], y=[-4h,4h].

fine 두 strip: c=0,1와 k=0..3 각각
 (5c+k,5(c+1)+k,5c+k+1),
 (5(c+1)+k,5(c+1)+k+1,5c+k+1).
transition strip: k=0,1 각각
 A=10+2k, M=11+2k, B=12+2k, C=15+k, D=16+k,
 (A,C,M),(M,C,D),(M,D,B).
coarse 마지막 strip: k=0,1 각각
 (15+k,18+k,16+k),(18+k,19+k,16+k).
좌표 변환은 orientation을 뒤집으므로 최종 각 triangle의 마지막 두 index를 교환한다.

예정 node21개, triangle26개, 면적32h².
공유 변 midpoint는 실제 node로 일치한다. 모든 경계는 위 rectangle의 네 변이다.
일반 셀은 직각삼각형, 전이 apex의 밑변2h·높이2h는 비둔각 조건을 만족한다.
exact conformity/면적/경계/비둔각 검사를 별도로 통과해야 한다.

## 사전 지정 witness와 독립 해석값

선택 node6: (x,y)=(0,-a), 일반 fine strip 내부.
선택 node11: (x,y)=(0,0), 전이 strip apex. 두 node 모두 strict interior.
x=0의 strict interior는 이 두 node다. 기존 pair selection이 (6,11)을 선택해야 한다.

node6의 비영 edge weights: x 방향 이웃 각각2, y 방향 이웃 각각1/2.
V6=2h², 2Σw/V6=5/h².
node11: x=±h,y=0 이웃 각각2; x=0,y=-a 이웃1/2;
 x=±h,y=a 이웃 각각1/4. 따라서 Σw=5, V11=17h²/8,
 2Σw/V11=80/(17h²).

위 값은 각 triangle의 cot/2 및 incident w*length²/4를 직접 합한 값이다.
독립 기준 계산은 diagnostics.geometry_weights/exact_row를 호출하지 않는다.

x만의 함수에서 같은 x 이웃 항은 상쇄된다. projected rows:
R6(-h)=-1/h², R6(0)=2/h², R6(h)=-1/h².
R11(-h)=-18/(17h²), R11(0)=36/(17h²), R11(h)=-18/(17h²).
따라서 R6-R11은 (-h,0,h)에 (1,-2,1)/(17h²), 정확히 비영이다.

g=(x/L)^2:
A6=-2/L²=-125000cm^-2.
A11=-36/(17L²)=-2250000/17cm^-2.
|A6-A11|=2/(17L²)=125000/17cm^-2≈7352.94117647.
max row scale=5/h²=83886080cm^-2.
기존 상대 문턱1e-8*scale=0.8388608cm^-2.
차이는 이 문턱의 약8765배다. 문턱은 변경하지 않는다.

독립 exact geometry와 float 저장값을 대조하고 실제 uncertainty를 기록한다.
사전 예상 uncertainty≤1e-6cm^-2: binary 직각 edge weights는 exact이고,
sqrt(5)*h slanted edge의 곱/나눗셈은 float64 소수 연산이다.
이는 시험의 보수적 예상 상한이며 모든 native 계산의 엄밀 오차 정리가 아니다.
이 상한에서 두 번째 기존 문턱100*(uncertainty+100eps*scale)<0.000287cm^-2.
상한 불충족 시 원인을 보고하고 fixture/문턱을 조정하지 않는다.

## 사전 기대 결과

- 새 geometry 전체 analyze: NONINVARIANCE_WITNESS, pair[6,11], power2.
- 기존 tensor grid: INCONCLUSIVE. 선택 pair exact rows 동일도 별도 확인.
- 기존 transition/stencil-only: 기존 INCONCLUSIVE 유지.
- 새 fixture endpoint 방향 반전: 같은 witness.
- NodeVolume/EdgeLength/EdgeCouple 누락: 예외 차단.
- NaN weight/범위 밖 endpoint/NodeVolume 2배: 예외 차단.
- EdgeLength와 EdgeCouple 동시2배: 길이 무결성 예외 차단.
- 전체 x 좌표를0.01cm 평행 이동하고 길이를 재계산: NOT_MEASURED.

## 승인 범위

통과는 기하 기반 합성 판정기의 양성 경로만 승인한다.
네 polynomial 일치는 모든 함수 불변성의 증명이 아니다.
projected-row 동일은 해당 시험 pair의 선형 row 동일성만 증명한다.
실제 DEVSIM import/가중치/PN 정확도/메쉬 수렴/원격 실행은 승인하지 않는다.
