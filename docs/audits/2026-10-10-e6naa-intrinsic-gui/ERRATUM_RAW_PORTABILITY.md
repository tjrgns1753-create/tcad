# 원본 Git 저장 바이트 정정

독립 artifact 검증은 로컬 다운로드 및 보존 파일을 모두 통과했으나, 처음 Git에
추가한 E6NAA raw 중 records.json과 steps.json의 CRLF가 LF로 변환된 사실을 후속
`verify_raw_blobs.py`에서 발견했다. REPORT의 바이트 보존은 당시 로컬 파일에는
성립했지만 Git blob까지 증명된 것은 아니었다. 그 범위를 정정한다.

원본 artifact와 일치하는 로컬 파일을 -text attributes 아래서 정확히 재등록했다.
복원 커밋 `89e67b9`: records.json 75042→78730 bytes, steps.json 2246→2317 bytes.
다운로드 원본 자체, 수치, PLAN, physics 코드, 게이트, 원격 실행 결과는 바꾸지 않았다.

복원 뒤 E6NAA/E6NAB의 전체36원본(summary 포함)은 artifact SHA와 현재 Git blob,
local read_bytes가 모두 정확히 같음을 엔진 없이 재확인했다.
검증기: `../2026-10-10-e6nab-intrinsic-refusal/verify_raw_blobs.py`.
root gitattributes는 이번 날짜 E6N raw/**에만 -text/-diff를 적용하며, 이후 checkout
줄바꿈 설정으로 원본이 바뀌지 않도록 한다. 이전 보고서는 역사로 보존한다.
