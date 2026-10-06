# 자원 정책 변경안 — 승인 전, 실행기 미연결

기존 PLAN과 실제 원격 실행 결과는 수정하지 않는다. 600초/후보, 1800초/전체,
6GiB 메모리, 파일120MiB/전체200MiB 예산도 늘리지 않는다.
현재 run_e6na.py의 사후 검사로 실행 중 제한을 보장한다고 주장하지 않는다.

## 필요한 구조 변경

부모 supervisor는 엔진을 import하지 않고 후보 하나씩 별도 child를 시작한다.
child가 backend를 import한 직후 solve trap을 설치하고 기존 후보 import-only 경로를 실행한다.
부모는 monotonic 시간을 이용해 후보 시작부터600초/전체1800초를 감시한다.
Windows Job Object에 child를 생성 직후 배치하고 kill-on-close와 메모리 한계를 사용한다.
할당 실패·Job Object 연결 실패·메모리 조회 실패는 실행을 허용하지 않는다.
Job Object 메모리 commit 제한과 기존 working-set6GiB는 서로 다른 측정이므로
이를 동일하다고 표현하지 않는다. working set/자식 합계도 감시하고
정확한 측정 범위/감시 간격을 새 승인 문서에 고정해야 한다.

현재 부모+단일 device 구조에서 후보 child로 옮기면 cleanup, 소스 식 확인,
후보 결과 전달/NPZ 취합의 실행 계약이 바뀐다. 이번 보완에서는 구현·연결하지 않는다.
아래 순수 policy prototype은 판단 로직 합성 검증만 하며 운영 watchdog이 아니다.

## 실패와 cleanup

한계/감시 실패면 부모가 child process tree를 종료하고 후보 FAIL + 이후 NOT_RUN으로 기록한다.
종료 실패/후손 잔존/결과 불완전은 별도 오류이고 PASS로 바꾸지 않는다.
native 함수가 멈추면 child의 finally cleanup은 보장되지 않는다.
부모에서 process-tree 종료 확인을 별도로 기록하고 정상 엔진 cleanup과 구분한다.
전체 wrapper timeout은 마지막 보호일 뿐 후보별 supervisor의 대체가 아니다.

## 출력 완전성

배열의 uncompressed nbytes와 UTF-8 JSON/witness/메타데이터 bytes를 합산한다.
각 serialized file 및 전체 필수 payload 예산을 저장 전에 검사한다.
NPZ header/ZIP container overhead와 최종 파일 실제 bytes도 저장 후 재확인한다.
초과면 결과는 FAIL이고 저장된 일부 파일을 유효 증거 세트로 승인하지 않는다.
artifact 전달의 omitted_outputs와 파일 누락/해시 오류를 사후 독립 verifier가 검사한다.
report.json 내부 verdict만 보고 원격 결과를 승인하지 않는다.

## 아직 필요한 승인

후보별 프로세스 격리, 메모리 정의/OS 한계, 감독 interval, source 재확인,
전체/후보 timer 시작점 및 artifact verifier의 실행 위치를 고정한 PLAN 보완 승인.
승인 전 원격 재실행 없음. 기존 단일-process 실행기를 자원 계약 충족으로 승인하지 않음.
