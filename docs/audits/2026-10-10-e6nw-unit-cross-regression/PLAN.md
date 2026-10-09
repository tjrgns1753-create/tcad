# E6N-W: 공통 측정 코드 변경 후 tracked unit 83개 교차 회귀

시작 HEAD a892ac0. Q/R/S의 접점·캡션·요청 bias 검증과 V의 기록 범위 수정 뒤
tracked tests/unit/test_*.py 83개를 원격에서 정확히 한 번 실행한다.
manifest는 각 파일의 LF 정규화 SHA를 실행 전에 고정한다. 다른 파일을 추가/삭제하여
숫자를 맞추거나 실패 assertion을 완화하지 않는다.

실행은 GitHub-hosted Windows이며 로컬은 manifest/소스/정적 검사만 한다.
새 감사 parent가 existing resource_supervisor로 파일마다 subprocess를 관리한다.
개별60초, 전체900초, artifact8MB. 결과·raw log를 파일마다 즉시 기록한다.
timeout은 성능/실행 예산 초과이지 물리 오류 판정으로 바꾸지 않는다.

PASS는 해당 unit script rc0/cleanup true라는 뜻이다. 합성·mock 테스트를 실제
물리검증으로 집계하지 않는다. integration 디렉터리, 기존 PN42 solve, 양의 시간
산화/디바이스 sweep 및 전체 regression은 실행하지 않는다.
unit 내부 엔진 호출 여부를 부모 버전 probe 기록으로 추론하지 않는다.

83개가 전부 기록돼야 완료이며 실패/timeout/누락은 그대로 보고한다.
파일별 결과가 있는 직전 동일 suite baseline이 없으므로 NEW_REGRESSION=0을
단정하지 않는다. 실패하면 먼저 소스/trace 근거로 이번 변경과의 관련성을 분리한다.
고정된 이번 source SHA에 대한 raw 목록을 다음 비교용 기준으로 남긴다.

production·gate·엔진·기존 원본/PLAN·test assertion 수정 없음. main 병합 없음.
