# 첫 원격 시험의 Python 3.11 결함

Run 37418524399, source 836178a: 설치 helper AST는 고정 SHA와 일치했다. 첫 두 계약 테스트는 통과했지만 test_flux_source_contract의 비어 있지 않은 type_params 반례가 실패했다. 따라서 전체 호환성은 FAIL이며 실제 import 감사를 시작하지 않았다.

Python 3.11 FunctionDef의 _fields에는 type_params가 없다. 테스트가 동적으로 추가한 비어 있지 않은 속성은 ast.iter_fields에 나타나지 않아 기존 검사가 누락했다. _canonical의 AST 순회 전에 getattr로 해당 속성의 비어 있지 않은 값을 명시적으로 차단한다. Python 3.12+의 실제 필드와 Python 3.11의 동적 속성 모두에 같은 거부 계약을 적용한다.

예상 AST SHA, 정상 helper, 허용 tolerance, 원본 물리 증거, 기존 PLAN은 바꾸지 않았다. 같은 사전 기준으로 수정된 코드의 새 시험을 실행한다. 이것은 실패를 무시한 자동 재시도가 아니라 발견된 코드 결함 수정 후의 별도 실행이다.

첫 run의 artifact는 로컬 작업공간 e6na-compat-37418524399에 원문 보존했다. engine_imports=0, actual_solves=0이며 engine-free 공통 실행기도 NOT_IMPORTED로 기록했다.
