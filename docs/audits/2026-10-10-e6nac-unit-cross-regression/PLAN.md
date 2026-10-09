# E6NAC — intrinsic GUI 보완 뒤 unit 교차 회귀

실행 전에 MANIFEST로 현재 tests/unit/test_*.py 전체 목록과 LF SHA를 고정한다.
이전 W의83개 결과를 현재 결과로 대체 인용하지 않는다. 새 입력은 manifest의 count와
실제 원격 파일집합이 완전히 같아야 한다. hash mismatch는 실행 전 중단한다.
모든 파일은 독립 subprocess에서 딱1회 실행하며 기존60초 자원 한계를 유지한다.
출력/종료코드/cleanup을 파일마다 저장하고 실패를 skip이나 pass로 바꾸지 않는다.

테스트 assertion·fixture·production·gate를 수정하지 않는다. 전체 unit 결과만
검증하며, integration 전체 회귀나 물리적 타당성의 독립 승인으로 주장하지 않는다.
실행은 GitHub-hosted Windows에만 한정하고 로컬에서는 manifest/정적 검사만 한다.
대조 기준은 W의파일별 원본이며 새 파일은 별도로 분류한다.
