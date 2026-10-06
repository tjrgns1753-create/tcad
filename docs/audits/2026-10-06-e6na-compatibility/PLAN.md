# E6N-A 원격 호환성 사전 기준

이번 작업은 GitHub-hosted Windows / Python 3.11 호환성 확인이다. 물리 계산과 엔진 import는 금지한다. 기존 PLAN과 물리 gate는 변경하지 않는다.

1. 설치된 DEVSIM helper 파일은 배포 메타데이터로 위치를 찾고 텍스트/AST만 읽는다. 고정된 검토 AST와 일치해야 한다.
2. 기존 엔진 없는 계약 테스트 6개를 그대로 실행한다. 각 테스트 20초, 전체 시험 110초, 외부 실행기 120초이며 정리 시간을 별도로 확보한다.
3. Windows Job에 배정한 자식에서 테스트를 실행한다. 중첩 Job, 정상/실패/시간초과/손자 프로세스 정리 검증이 모두 통과해야 한다.
4. 테스트 종료 코드 0만으로 물리 승인을 하지 않는다. 각 감독 결과 COMPLETED와 cleanup_ok=True를 모두 요구한다.
5. 실패는 숨기거나 자동 재시도하지 않는다. 로그와 결과를 5MiB 이하 artifact로 보존한다.
6. native engine import를 금지하는 감사 hook을 자식 진입점에 설치한다. helper AST 검증도 엔진을 import하지 않는다.
7. 시험 통과는 실제 DEVSIM 메쉬 import, PN 해, 수렴 또는 gate 해제 승인이 아니다.
