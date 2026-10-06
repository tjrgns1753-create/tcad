# E6N-E: N2와 동일한 x격자의 1D 수치 기준

## 1. 목적과 물리 제한

E6N-D의 실제 PN 전류는 안정적이지만 내부 carrier 비교는 실패했다.
N2의 역바이어스 정공 최대차는 1.39%, 공통 x좌표에서는 0.73%였다.
이번 작업은 reference 보간 오차를 분리하는 사후 진단이며 이전 미승인을
취소하거나 TCAD 제조 공정 전체/일반 PN을 승인하는 작업이 아니다.
기존 42회 2D solve는 재사용하고 한 번도 재실행하지 않는다.

물리 조건은 기존 N2와 동일: 단일 Si, 길이 40 um, 높이 0.1 um,
대칭 x=0 PN 접합, donor/acceptor 1e17 cm^-3 ACTIVE, 300 K,
기존 production 이동도/SRH 수명/Poisson·SG drift-diffusion/솔버 설정.
공식 API만 사용하고 엔진 내부·production 코드·gate는 수정하지 않는다.
공식 예제: https://devsim.net/examples_diode.html ; SG 원문 DOI
10.1109/T-ED.1969.16566. 1D와 2D 비교는 같은 모델의 수치 일관성 검증이지
실측 제작 논문과의 독립 일치는 아니다. y 균일 물리 문제에 한정한다.

## 2. 고정 입력과 실행

E6N-D2 원격 run 37424675525, source 7b2d2178597ef042fcd9b068df2018a797dafa1d.
`N2/arrays.npz` SHA eb5538684433427b6c328d4e3b334566353a16d0e391a28c24e434d54b1784e7.
`N2/record.json` SHA ef4466ff4c35f432ad0db46109a786da855a71266600e377cf3e36da1588dce5.
순·역방향 native x의 unique 배열은 정확히 동일하고 1545개다.
이 x값(cm)을 재변환/보간/반올림하지 않고 공식 create_1d_mesh/add_1d_mesh_line에
직접 공급한다. 각 line의 ps는 전체 길이 0.004 cm로 지정해 추가 subdivision을
요청하지 않는다. 최종 native x의 집합·개수·중복을 정확 대조하고 불일치면
숫자 근사나 fallback 없이 solve 전에 중단한다.

먼저 같은 x격자에서 uniform donor=1e16 cm^-3 ACTIVE 저항 대조군을
fresh device로 실행: 초기 2 solve와 +1 mV 한 점, 총 3 solve.
PN은 fresh forward/reverse 각각 기존 바이어스 전체를 유지한다:
forward 0.1,0.2,0.3,0.4,0.5,0.6 V / reverse -0.25,-0.5,-0.75,-1 V.
초기 2 solve씩 포함 총 14 solve. 전체 새 1D solve 17회 예정, 2D solve 0.
모든 장치에서 canonical query를 node별 검사하고 실제 production apply_doping을
호출한다. 1D에 2D PN gate를 거짓으로 적용하거나 강제로 해제하지 않는다.
생성한 node 모델과 전달된 실제 Donors/Acceptors/NetDoping을 원시 배열로 저장한다.

## 3. 사전 판정 조건

필수 증거 누락/None/비유한/오류/cleanup 실패는 PASS가 아니다.
모든 장치의 node 수=1545, canonical checked=1545, unresolved=mismatch=0.
solve 시도/성공 각각 control3/forward8/reverse6, 실패·snapshot 실패=0.
실제 native dimension=1. Production metadata의 1D current_unit=None은 유지한다.
별도 audit 대조군으로만 1D raw current를 A/cm²로 해석한다.
대조군 n0=(ND+sqrt(ND²+4ni²))/2, p0=ni²/n0,
sigma=q*(mu_n*n0+mu_p*p0), J=sigma*0.001/L.
native 단자 raw 값과 해석식 상대차<=1e-6, KCL 상대차<=1e-6를 요구한다.
이 대조군이 실패하면 PN 실행도 차단한다. 1D production 단위 표시를 고치지 않는다.

N2의 2D I/H와 새 1D raw J: forward 상대차<=1%, reverse<=2%,
각 장치 KCL<=1e-3, 순·역 전류 부호/증가 경향을 확인한다.
T/ni/q/mu_n/mu_p/taun/taup/eps/Vt를 두 결과에서 실제 parameter로 대조한다.
기존 snapshot bias: forward 0,0.3,0.5,0.6 / reverse 0,-0.5,-1 V.
native 2D 각 x를 정확히 같은 1D node에 매핑(보간 금지)하여 전위 최대차<=0.01Vt,
전자/정공 최대 상대차<=1%, 2D y 전위 spread<=1e-5 V.
수평 2D edge의 동일한 두 x 끝점에서 새 1D psi 차/실제 edge length를 계산한다.
이는 동일 구간 평균 전계이며 중심점 전계로 부르지 않는다.
전계 차는 기준 peak field로 정규화<=2%, 0장 지점의 상대오차를 쓰지 않는다.
1D/2D native E와 실제 psi 차/edge length 관계를 따로 확인한다.
Native x/y/NodeVolume/도핑/edge geometry/전위/carrier/전계/단자 전류를 보존한다.

## 4. 실행 경계/자원/완료

PLAN의 LF-normalized SHA 및 위 입력의 byte SHA를 backend 준비보다 앞서 검사.
로컬은 읽기·정적 검사·엔진 없는 합성 반례만, 실제 import/solve는 GitHub Windows.
기존 Windows Job supervisor: 전체 300초, sampled working set 6 GiB,
artifact 20 MB. 실패 시 재시도/허용오차 조정 없이 기록하고 다음 장치 중단.
MATCHED_REFERENCE_PASS는 이 문제의 동일 x격자 수치 비교가 통과했다는 뜻만이다.
원래 E6N-D 실패와 gate는 유지한다. 전체 regression/main 병합/엔진 내부 수정 금지.
Serena는 현재 도구 목록에 없어 rg/직접 읽기로 조사했다. 조사 대상은 공식 1D
메쉬 builder, canonical mapping, 기존 Obs/PN sweep/strict cleanup이며,
새 audit/profile 외 production caller나 bypass를 만들지 않는다.
