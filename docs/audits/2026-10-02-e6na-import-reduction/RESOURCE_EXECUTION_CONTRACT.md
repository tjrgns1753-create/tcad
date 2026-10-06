# E6N-A 후보별 감독 계약 — 사용자 승인 후 구현

기존 PLAN.md 및 기존 증거는 수정하지 않는다. 후보별 프로세스 격리 구조는
사용자의 2026-10-02 "ㄱㄱ" 승인으로 도입한다. 원격 실행 승인은 별도다.

- 부모는 엔진을 import하지 않는다. 후보별 새 Python bootstrap을 시작한다.
- bootstrap은 부모의 release 파일이 생성되기 전에는 대상 코드를 시작하지 않는다.
- 부모는 kill-on-close Windows Job Object에 bootstrap을 연결한 뒤에만 release한다.
- Job Object 연결 실패면 후보를 실행하지 않는다. breakaway 플래그를 허용하지 않는다.
- 후보 시작은 Popen 이전 monotonic 시각이다. 후보600초, 전체1800초는 기존 PLAN과 같다.
- 전체 시작은 부모 입력 preflight 직후, output directory 생성 다음 시각이다.
- 후보 및 전체 deadline의 작은 값으로 감시한다. 운영 감시 간격은0.5초다.
- 정상/비정상/한계초과 모두 Job 트리 종료 및 잔존 PID0을 확인한다.
- OS 정리 확인은 최대5초다. 이 시간은 계산 예산을 연장하지 않는 정리 비용이다.
- working set은 Job에 속한 프로세스들의 현재 working set 합이며6GiB 초과 시 종료한다.
- commit은 별도 관측한다. commit6GiB 강제한계를 설정했다고 주장하지 않는다.
- 0.5초 사이의 순간 peak나 할당 자체를 방지하지 않는다. working set 보호는 sampled다.
- 메모리/PID 조회 실패는 FAIL이다. 프로세스 종료와 조회 경합도 보수적으로 FAIL 처리한다.
- 요소400000 상한은 예정 개수로 생성 전, 실제 개수로 생성 후 확인한다.
- 파일120MiB/전체200MiB는 유지한다. raw 배열, JSON, NPZ uncompressed header 및
  실제 serialized 크기를 확인한다. 로그는 주기 감시이므로 한 주기 초과량은 가능하다.
- timeout/cleanup 실패/자식 증거 누락은 FAIL, 후속 후보 NOT_RUN이다.
- timeout으로 solve 횟수 기록이 소실되면 None이다. 기록 없이0으로 만들지 않는다.
- 부모는 child의 PLAN SHA/attempts/cleanup/status/NPZ SHA를 확인한 뒤에만 채점한다.
- 부모의 트리 정리는 DEVSIM delete_device/delete_mesh 성공의 대체 증거가 아니다.

이번 계약의 합성 검증은 운영 안전장치 검증이며 PN/메쉬 수렴/물리 정확도 증명이 아니다.
Python3.11 및 GitHub-hosted Job 중첩 호환성은 원격에서 아직 확인하지 않았다.
