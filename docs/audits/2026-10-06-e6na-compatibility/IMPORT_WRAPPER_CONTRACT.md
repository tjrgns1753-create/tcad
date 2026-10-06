# 실제 import 감사의 외부 실행 경계 보완

원래 E6N-A PLAN과 RESOURCE_EXECUTION_CONTRACT의 계산 예산은 변경하지 않는다.
후보 600초 / 전체 1800초 예산을 내부 Job 감독이 집행한다.

외부 실행기는 같은 1800초에 작업 트리를 먼저 종료하면 내부 cleanup과 최종 실패 증거 저장을 중단할 수 있었다. 따라서 외부 timeout만 1830초로 분리한다. 추가 30초는 종료·정리·기록 여유이며 새로운 계산 허용 시간이 아니다. 내부 예산·판정 tolerance·기하·physics gate는 불변이다.

공통 실행기의 DEVSIM 정보 조회 import도 E6N-A에서는 생략한다. 후보 진입점의 PLAN/입력/production SHA 확인을 먼저 실행하고, 그 뒤 후보 자식만 backend를 준비한다. 후보의 실제 패키지 버전과 소스 검사는 기존 감사 결과에 기록한다. 부모가 엔진을 준비하지 않는 계약을 유지한다.

호환성 시험 PASS와 원시 artifact 검토 완료 이전에는 실제 import 프로필을 요청하지 않는다.
