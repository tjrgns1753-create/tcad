# E6N-H: 현재 웨이퍼 canvas의 증거 출처 계약

시작 SHA d0dc7c27756fefe77416f341d8f6aad5d6ef2e96.
물리식·공정·측정 gate 변경 없이 redraw()의 거짓 대체 형상을 제거한다.
Serena 도구가 제공되지 않아 rg/직접 읽기로 redraw(), _draw_real_mesh_result(),
_view_flow_step(), reset(), run_oxidation() 및 관련 테스트를 조사했다.

수정 전 실제 Tk에서 두 반례를 재현한다: 공정 후 mesh 경로 누락 및 실제 파일 읽기 실패.
이때 정상 Si 사각형이 표시되는 현재 동작을 증거로 남긴다.
공정 후 mesh가 기대되면 오류 메시지만 표시하고 임의 Si/식각 깊이를 그리지 않는다.
공정 결과가 아직 없을 때만 입력 도식을 허용하며 계산 결과가 아님을 명시한다.
real mesh는 processed UI 플래그와 독립적으로 실제 파일에서 표시한다.
현재 canonical 상태의 UNRESOLVED/LEGACY 및 미지원 활성화는 화면에 경고한다.
이력 mesh는 현재 상태와 구분한다. 과거 사건만으로 현재 전체 상태를 판정하지 않는다.

원격 실제 ViennaPS로 virgin mesh 생성 및 positive-time unsupported 요청 후
canvas Si polygon의 실제 좌표/재료 대응과 전후 보존을 검사한다.
일부 미지원 영역 표시를 모든 영역의 차단 또는 물리 승인으로 과장하지 않는다.
재료 윤곽/전류/단위/기존 gate 회귀를 대표 테스트로 검사한다.
로컬은 AST 및 순수 검사만, Tk/engine/공정은 GitHub Windows에서 실행한다.
전체 회귀·main 병합·signed override·임의 tolerance 수정은 하지 않는다.
