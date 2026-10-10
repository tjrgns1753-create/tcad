# 원본 Git 바이트 보존 정정

최종 git blob 전수 대조에서 AI 원본의 `outputs/e6nai_out/records.json` 및 `outputs/e6nai_canvas_out/metrics.json` 두 파일이 다운로드된 artifact와 달랐다. 첫 git add 때 raw_initial 경로의 -text 속성이 빠져 CRLF가 LF로 정규화됐고, 속성을 추가한 뒤 일반 git add는 이미 staged된 동일 stat 파일을 다시 읽지 않았다.

다운로드 원본은 변형되지 않았으며 summary SHA와 일치했다. 바뀐 것은 기존 Git에 저장된 두 JSON의 줄바꿈이다. `git add --renormalize`를 이 raw_initial 경로에만 적용하여 -text/-diff 계약대로 원본 바이트를 다시 staged했다. 원본 내용/실행/물리 판정은 재생성하거나 바꾸지 않았다.

이전 커밋의 두 blob은 portable raw 증거로 쓰지 않는다. 수정 커밋 이후 `verify_preserved_blobs.py`로 5개 batch의 출력 146개와 각 summary/run.log 10개를 모두 runner 및 다운로드 바이트와 대조한다. 이는 계산 결과의 물리 승인과 별개의 evidence transport 수정이다.
