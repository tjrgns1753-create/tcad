# E6N-K 접점 장치·CSV 결과의 출처 계약

기존 장치는 접점을 해석한 mesh/현재 canonical state/pin과 연결되어야 한다.
현재 상태와 달라진 장치를 DC solve에 사용하거나 이전 결과를 현 상태의
CSV로 내보내지 않는다. 이는 출처 검사이며 물리 모델·지원 gate 변경이 아니다.

고정 검사: 파일 내용 해시(같은 경로 덮어쓰기 포함), canonical state 객체
정체성, pin 이름/역할/좌표/target_region. 파일이 없거나 출처 기록이 없으면
일치한다고 추정하지 않는다. 같은 bytes와 동일 상태/pin은 통과한다.
canonical 상태는 immutable v2 전이를 기준으로 한다. state 내부의 임의
강제 변조는 이번 계약의 지원 범위가 아니다.

수정 전 AST 추출 exporter에서 이전 결과가 출처 확인 없이 파일 대화상자에
도달하는 반례를 확인한다. 수정 후 순수 context 반례·실제 Tk/DEVSIM import
상태 변경 차단·기존 DC canonical gate·기존 uniform DD 대조군을 검사한다.
동일 source context의 CSV export는 합성 BiasPoint로 배선만 검사한다.
stale 차단은 canonical certainty 상실로 취급하지 않고 재해석 필요를 알린다.

엔진/Tk import와 공정/solve는 원격 Windows만. 로컬은 순수 Python/AST.
새 물리 방정식, tolerance 완화, gate 해제, main 병합, 전체 회귀 없음.
