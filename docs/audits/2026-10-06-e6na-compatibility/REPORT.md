# 원격 호환성 검증 결과

## 결론

수정 전 run 37418524399는 Python 3.11 AST 반례에서 FAIL이었다. 해당 누락 검사만 수정한 run 37418782974는 6개 테스트 모두 PASS이다. PN 물리 정확성이나 실제 메쉬 import를 승인한 결과가 아니다.

## 검증된 범위

- GitHub-hosted Windows, Python 3.11.9, DEVSIM 배포 버전 2.11.0.
- 배포 helper 파일을 텍스트로 읽은 AST SHA는 고정 검토 SHA fd33b1c5c4a5f199916c550c138df3da8fce46a8ad8a8c8a87548b73a205611e와 일치.
- test_contract, test_review_followup, test_flux_source_contract, test_resource_supervisor, test_supervised_entry, test_positive_geometry: 6/6 COMPLETED, exit_code=0, cleanup_ok=True.
- 공통 실행기 engine 정보는 NOT_IMPORTED. 시험 기록 engine_imports=0, actual_solves=0.
- resource_supervisor의 중첩 Job, 실패·timeout·손자 정리·정리 실패 차단 반례도 통과했다.
- 이 메모리 검사는 주기적 working-set 관측이지 순간 메모리 할당의 하드 상한이 아니다.

## 원시 증거

원격 source 33db041942fe18446443834673d1c3010c0fe219, Actions https://github.com/tjrgns1753-create/tcad/actions/runs/37418782974, artifact remote-run-35.

result.json SHA: 5a35a58fab15dfdbf20e7fa12f133fc0c666cf031adf38003bcf775f77e2dce1.
run.log SHA: 8ce178d0aac2a2df4bad23ca7ae46b9dc6e597d0bf3d4b628e9ef5ca25a091f9.

다운로드한 7개 출력의 해시 및 전체 run.log 해시를 summary와 직접 비교했다. omitted_outputs=[], log_truncated=False. artifact 전체는 Codex 작업공간 e6na-compat-37418782974에 원문 보존했다. summary의 원시 입력 SHA는 Windows checkout 바이트 기준이며 PLAN 진입점 SHA는 LF 정규화 기준이다. 둘은 서로 다른 의미다.

## 다음 실행의 범위

실제 import 감사는 기존 PLAN과 입력 해시 preflight를 엔진 없이 다시 통과했다. N0부터 순차 실행한다. FAIL/INCONCLUSIVE/NOT_MEASURED면 N1/N2는 NOT_RUN. PN solve·게이트 해제·main 병합은 하지 않는다. 내부 1800초 계산 예산은 불변이며 외부 1830초는 cleanup 여유를 포함한다.
