# E6N-AE: SiO2 barrier 검출 틈의 원인 조사
사전 기준. production/test/기존 evidence/gate는 변경하지 않는다.
기준 SHA d02861002357e7a3268b450bb5a9bf60a5200ca7.
Serena 도구 미제공: 직접 읽기/rg 대체.
로컬 소스/정적/합성만, 실제 ViennaPS/GitHub Windows 원격만. DEVSIM import/solve 금지.

## 가설 및 구분
derive_barrier_covered_windows는 실제 triangle interior가 아니라 vertex bucket의 min/max만
읽는다. float32 좌표/추정 spacing/bucket 경계로 빈 bucket이 생길 수 있다.
AD의 x=-4.75,-4.25 부근 보호구간 틈을 실제 SiO2 부재라고 미리 판정하지 않는다.
native geometry와 exported triangle geometry와 detector 출력은 각각 기록한다.

## 고정 입력/사전 결과 기준
기존 DIRECT_EXPLICIT_GEOMETRY chain helper 그대로:
width10, yextent8, Sidepth5, oxide0.3, grid0.1um.
Case before: explicit blanket stack.
Case after: inherited selective isotropic etch, remask[-5,-1.5],[1.5,5],
PHS0/Si0/SiO2-0.6, time1s. 산화 호출0이며 실제 Process etch는 허용한다.
probes [-4.75,-4.5,-4.25,-4,-3,0,3,4.25,4.75]um을 먼저 고정.
before는 전9지점 native SiO2 top>Si top, exported 두 material 존재를 확인한다.
after는 x0만 opened(oxide 없음), 나머지8은 보호됨. native Si displacement <= 기존
native_eps(8.0); oxide height 기준은 native request0.3/0(고정 geometry)로 비교한다.
exported 각 column에 삼각형-스캔라인 교차를 독립 계산하고 실제 연속 interval 합을 읽는다.
native oxide 있음/exported oxide 없음: EXPORT_REPRESENTATION_MISMATCH.
native/exported >=0.01um oxide 있음/detector false: DETECTOR_FALSE_NEGATIVE.
native/exported oxide없음/detector true: DETECTOR_FALSE_POSITIVE.
단순 threshold 변경/rounding/빈구간 채우기는 하지 않는다.

## 저장/실행
실제 before/after VTU를 원본 보존, native columns arrays와 detector windows/probe 데이터 JSON.
모든 byte hashes, fixed PLAN LFsha, run ID/SHA, engine counts.
DEVSIM import는 audit hook으로 차단, doping writes/solves0.
결과 rc는 조사실행 완전성과 데이터 검증의 성공이며 detector 물리 승인 뜻이 아니다.
누락/NaN/native fixture 실패는 FAIL로 중단한다.
whole width 혹은 nonplanar 일반 검출을 승인하지 않으며 생산수정은 다음 증거판단 후만 한다.
