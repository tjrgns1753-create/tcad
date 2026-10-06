# E6N-F: 공식 1D 기준해의 구간 2분할 수렴 검사

시작 SHA b3db789. 이번에는 production·gate·엔진·기존 원본을 변경하지 않는다.
새 remesher와 추가 2D 계산 없이, E6N-E 공식 1D 메쉬의 구간에 midpoint 하나씩을
추가한다. 원래 x좌표는 정확히 유지한다. 1,545→3,089 노드가 기대값이다.
단일 Si, 40 µm, 대칭 ACTIVE NA=ND=1e17 cm⁻³, 300 K, 기존 이동도/SRH/
접점/solve 종료 기준/순·역방향 바이어스를 그대로 유지한다.

실행 전에 본 PLAN의 LF 정규화 SHA 및 E6N-E 원본 record/arrays SHA를 검사한다.
로컬은 엔진 없는 코드·합성 검사만, 실제 import/solve는 GitHub Windows에서만 한다.
기존 run_reference.build_device/canonical_audit/run_device 및 strict cleanup을
재사용한다. 새 순방향 8회, 역방향 6회 = 14회 solve만 허용한다.
엔진 내부나 SG 식을 다시 작성하지 않는다.

사전 통과 기준:
- 실제 mesh x집합이 3,089개 지정 좌표와 정확히 같고 도핑 및 canonical 검사 정상.
- 각각 solve 시도=성공=8/6, 실패 및 snapshot 실패 0, cleanup 정상.
- 기존 물성 및 접점 metadata 동일, 실제 Donors/Acceptors/NetDoping 쓰기 확인.
- 모든 바이어스의 전류 상대 변화: 순방향 ≤1%, 역방향 ≤2%.
- KCL 상대 오차 ≤1e-3, 전류 부호·크기 단조성 정상.
- 지정 snapshot의 원래 1,545 좌표에서 전위 변화 ≤0.01 Vt,
  전자·정공 상대 변화 각각 ≤1%. 보간 없이 정확한 좌표로만 비교한다.
- 전계는 동일한 coarse 구간의 양 끝 전위로 계산한 구간 평균끼리 비교한다.
  기준 peak로 정규화한 차이 ≤2%. 서로 다른 edge 중심값을 직접 비교하지 않는다.

PASS는 이번 대칭 PN 기준해의 지정 refinement 안정성만 의미한다.
연속해에 대한 오차 상한이나 일반 PN/제작 공정 검증은 아니다.
gate는 유지하며 이전 N2 수치 일치 결과를 보존한다.
14회 solve는 프로세스 트리 120초/6GiB 예산, 결과 총 10MB 예산으로 실행한다.
누락·NaN·좌표 이동·solve 실패·불완전 cleanup은 명시적인 실패이며 기준을 완화하지 않는다.
