# E6N-N 실제 노드 hover와 reset

검증된 E6N-M 배열만 사용한다. DEVSIM 추가 조회/solve/엔진 변경 없음.
화면에 실제로 전체 노드를 표시한 현재 layer에서 마우스와 가장 가까운 노드가
3픽셀 이내일 때만 그 노드의 값·단위·실제 좌표를 보여 준다. 마우스 위치의
보간 값이라고 하지 않는다. 표시 cap·출처·측정 설정·history 조건은 기존과 같다.
멀리 있는 마우스, 오래된 source, 실패한 재측정 뒤에는 수치를 표시하지 않는다.
reset은 노드 배열과 source context를 해제한다.

로컬 순수 helper 및 AST GUI 테스트로 screen scale·모든 layer·radius 외부·
오래된 상태·reset을 검사한다. 원격에서는 기존 E6N-M actual uniform DD 73개
노드 자료와 실제 Tk 이벤트 handler를 대조하고 기존 단위·gate 대조군을 재사용.
새 물리 검증/PN gate 해제 없음. hover 반경은 UI hit-test이며 물리 tolerance 아님.
