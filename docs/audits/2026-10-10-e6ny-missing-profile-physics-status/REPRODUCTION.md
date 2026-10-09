# 수정 전/후 로컬 반례

수정 전 실제 run_measurement 초입 AST를 추출한 unit --before:
{"mode": "before", "cases": 6, "engine_imports": 0}

None/빈 상태/CHEMICAL/UNKNOWN/mixed/ACTIVE-without-result에서 전부 상태를
갱신하지 않았고 안내에 has no carrier가 포함됐다.

수정 후 같은 실제 초입 AST:
{"mode": "after", "cases": 6, "engine_imports": 0}

CHEMICAL/UNKNOWN/mixed는 activation 미지원, 다른 입력은 GUI profile 미확보로
분류한다. 모든 경우 canonical 객체와 history 무변경, 기존 field cache 세 개 제거.
엔진/Tk import는 audit hook으로 금지한다. 합성 검사는 실제 solve로 집계하지 않는다.

첫 source-context 대조 실행은 존재하지 않는 test_field_source_context_mock.py를
잘못 지정해 파일 없음으로 실패했다. rg로 실제 test_electrode_source_context_mock.py를
찾아 실행해 통과했다. 이를 코드 회귀나 성공한 검증으로 숨기지 않는다.
