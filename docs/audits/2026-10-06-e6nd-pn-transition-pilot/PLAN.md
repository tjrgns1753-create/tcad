# E6N-D: 전이 메쉬 PN 바이어스 파일럿

## 목적과 제한

사용자의 자유로운 공정 순서에서 유지해야 할 실제 도핑 상태가 장치 계산에
정확히 전달되는지 확인하는 한정 파일럿이다. 제조 공정 검증은 아니다.
단일 Si, 40 um × 0.1 um, x=0 대칭 접합, NA=ND=1e17 cm^-3,
ACTIVE 도핑, 300 K, 기존 production 이동도·SRH 수명·접점·솔버를 유지한다.
공식 DEVSIM diode 예제의 Poisson 및 Scharfetter–Gummel DD 경로를 재사용한다.
출처: https://devsim.net/examples_diode.html ;
Scharfetter/Gummel (1969), DOI 10.1109/T-ED.1969.16566.
평형 DD 초기화 항등식은 독립적인 Poisson 정확도 증거가 아니다.

## 결과 확인 전 고정하는 실행

E6K L0/L1의 x좌표와 E6N-A의 y 행 수 16/32를 사용한다.
기존 structured_lateral_refine(center=0, half-width=0.1 um)만 사용한다.
N0=8037 nodes/15264 triangles, N1=31173/60736 예상.
정확한 conformity, 비둔각, 면적 보존 및 실제 NodeVolume gate를 검사한다.
각 메쉬의 forward/reverse는 서로 다른 새 장치다.
forward=[0.1,0.2,0.3,0.4,0.5,0.6] V,
reverse=[-0.25,-0.5,-0.75,-1.0] V: 기존 E6K와 동일, 총 28 solve 예정.
각 장치마다 production apply_doping의 기존 gate 거부 및 write/solve 0회 확인 후,
모든 native node의 canonical query를 확인하고 audit 전용 public API로 전달한다.
production gate 해제, 엔진 내부 수정, 별도 물리 식 도입은 하지 않는다.

## 사전 판정 기준

누락·None·비유한·오류·cleanup 실패는 PASS가 아니다.
canonical_checked=실제 node 수, unresolved=mismatch=0; 각 장치 모두 기록.
gate reason=STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED, write/solve_attempt=0.
solve_attempts=success=예정 횟수, solve/snapshot failure=0.
2D 전류 단위 A/cm, J=I/높이(cm); 실제 두께 없는 A 전류로 표시하지 않는다.
동일 L의 E6K 1D terminal J와 상대오차 forward<=1%, reverse<=2%.
KCL 상대오차 <=1e-3. 모든 비평형 전류 부호와 단조성을 확인한다.
전위는 각 native x에서 기존 1D 데이터를 선형 보간한 값과 최대 차이<=0.01 Vt.
이 보간은 정확 해석해가 아니며 carrier는 log 보간 비교 최대 상대차<=1%.
전계는 각 수평 edge의 1D 보간 전위 차/실제 길이와 비교한다.
전계 오차는 최대 기준장 크기로 정규화하여<=2%; 0장 부근 상대오차를 쓰지 않는다.
y 전위 불균일 max<=1e-5 V. 이 조건은 물리적으로 y 균일한 문제에만 해당한다.
N0→N1 전류 차 forward<=1%, reverse<=2%; 두 레벨 비교이지 수렴차수 증명이 아니다.
노드/edge 배열, native 전위·전자·정공·전계 snapshot 및 접점 전류를 보존한다.

## 실행 경계와 자원

PLAN LF 정규화 SHA를 backend import보다 먼저 고정 대조한다.
로컬은 엔진 없는 코드·기하·합성 판정 테스트만 수행한다.
실제 import/solve는 GitHub Windows. 각 메쉬 별 자식 프로세스와 기존 Windows Job
supervisor 사용, 후보 900초/전체 1800초/working set 6 GiB 샘플링 상한.
첫 실패나 시간초과에서 후속 메쉬 NOT_RUN, 알려지지 않은 solve 수는 null.
원시 출력 120 MB, 전체 artifact 200 MB 상한. 결과를 보고 허용오차를 바꾸지 않는다.
기존 PLAN/원본 증거/production/gate/main은 보존한다.
Serena는 현재 도구 목록에 없어 rg/직접 읽기로 대상·호출자를 조사한다.
대상은 기존 Obs/canonical/write_mesh 및 공식 import/sweep의 audit 호출자이며,
이번 수정은 새 audit 파일과 remote profile/request에만 제한한다.
