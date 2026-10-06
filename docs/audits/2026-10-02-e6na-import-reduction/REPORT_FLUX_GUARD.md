# E6N-A 공식 helper 소스 검사 우회 보완

## 범위 / 판정

실행 위치: 로컬. 파일 읽기·AST 분석·Python spy·합성 테스트만 실행했다.
엔진 import/실제 mesh import/solve/원격 실행/전체 회귀는0회다.
사용자가 직접 구현을 승인했다. 시작 HEAD 509f5e50db8cab3ae59c36c2c4693f27ade30567,
브랜치 claude/remote-runner. 이전 미커밋 보완을 보존했고 stage/commit/push는 하지 않았다.

판정: REVIEWED_HELPER_AST_GUARD_VERIFIED_WITHOUT_ENGINE.
원격 실행 승인이나 PN/공정 물리 정확성 승인이 아니다.

## 조사와 설계

Serena 도구가 제공되지 않아 이전과 같이 rg/직접 읽기로 조사했다.
적용 CLAUDE.md/한국어 AGENTS 지침과 기존 범위를 유지했다.
target은 run_e6na.require_flux_source이며 caller는 _execute_import_audit와
test_review_followup이다. production caller는 없다.

주석-only 소스를 getsource 반환값으로 제공한 수정 전 callback count=1을 재현했다.
설치된 simple_physics.py를 엔진 import 없이 읽어 CreateSiliconPotentialOnly를 검토했다.
검토 내용: edge 모델 tuple에서 ElectricField/필드 식, PotentialEdgeFlux/flux 식을
꺼내 CreateEdgeModel에 전달하고 PotentialEquation의 edge_model을 PotentialEdgeFlux로 연결한다.

일반 Python dataflow 해석기를 새로 만들지 않고 검토된 함수 구조 하나를 고정 AST
allowlist로 허용한다. 이름·상수·호출·루프·조건·방정식 연결 모두 AST 지문에 포함된다.
주석/함수 docstring/소스 공백·줄바꿈은 무시한다. 식 문자열 내부 공백은 상수의 일부이므로
의미적으로 같을 수 있어도 달라지면 차단한다. 다른 버전/리팩터링은 수동 재검토 전 불허한다.
Python3.11과3.12+의 빈 type_params 필드 차이만 canonical 직렬화에서 제거한다.
비어 있지 않은 type_params는 미지원이다. 서로 다른 실제 Python 버전에서의 실행은 하지 않았다.

예상 AST SHA는 코드 상수
fd33b1c5c4a5f199916c550c138df3da8fce46a8ad8a8c8a87548b73a205611e.
검사 대상에서 런타임에 정답 SHA를 생성하지 않는다. 검토한 함수는
REVIEWED_FLUX_REFERENCE.txt에 별도 데이터로 보존한다.

## 검증 결과

수정 전 주석-only callback=1. 수정 후 주석-only callback=0.
신규 test_flux_source_contract.py 정상5개: 기준 함수/주석/함수 docstring/CRLF/들여쓰기.
모두 통과하고 callback 정확히1회.

차단12개: 주석-only, docstring-only, 미사용 문자열, ElectricField 식 변경,
PotentialEdgeFlux 식 변경, equation edge_model 변경, 모델 생성 호출 변경,
추가 top-level 코드, 미지원 함수 구조, syntax 오류, 비문자 입력, 소스 확인 불가.
모두 callback0회. 빈/nonempty type_params 합성 검사도 기대대로 동작했다.

reference 함수는 실제 엔진 대신 Python spy만 연결해 실행했다.
관측한 두 모델 정의와 PotentialEquation의 연결이 검토 내용과 일치했다.
이는 native 함수 호출이 아니라 소스 reference의 Python-level 확인이다.

설치 파일에서 ast.get_source_segment로 읽은 실제 함수도 상수 지문과 일치했다.
실제 설치 패키지를 import하거나 해당 함수를 호출하지 않았다.

실행한4개 파일 모두 RC=0:
- test_flux_source_contract.py
- test_review_followup.py
- test_contract.py
- test_resource_proposal.py

## 보존 / 한계

PLAN.md, raw/remote-run-33/summary.json, run.log는 기준 HEAD와 원시 바이트 동일.
이전 FOLLOWUP_CHANGES.patch의 SHA도 그대로다.
production tcad/, tests/, tcad_2d_stagewise.py diff0.
Python 파일 AST parse/LF 검사 통과. git diff --check RC=0. HEAD 그대로, staged0.

AST 검사는 해당 helper 몸체만 확인한다. 외부 CreateEdgeModel/equation helper,
module globals, monkeypatch, native 엔진 내부의 동일성은 증명하지 않는다.
실제 원격 wheel의 AST 대응도 원격 재실행 시 확인해야 한다.
원격 profile의 입력 목록에 새 계약 파일 포함 여부는 원격 승인 단계에서 검토해야 한다.
현재 profile/workflow는 바꾸지 않았다.

운영 자원 watchdog 미구현, 전체 analyze 경로의 충분한 양성 witness 미충족은 그대로다.
원격 재실행/PN 계산/gate 해제를 승인하지 않는다.

## Change diff — 이전 미커밋 보완과 이번 변경 분리

이번 추가 변경:
- run_e6na.py:22,65 require_flux_source가 substring 대신 require_reviewed_source를 호출.
- flux_source_contract.py:31 require_reviewed_source, 고정 지문/canonical parser 신규.
- REVIEWED_FLUX_REFERENCE.txt: 검토된 함수 reference 데이터 신규.
- test_flux_source_contract.py: callback/AST/spy 정상 및 반례 신규.
- test_review_followup.py:90 기존 가짜 정상 문자열을 검토된 reference로 교체.
- .gitattributes: 이번 patch의 바이트 보존 속성만 추가.

핵심 before/after:
```diff
-    expected = ('(Potential@n0-Potential@n1)*EdgeInverseLength', 'Permittivity * ElectricField')
-    if not all(expression in source for expression in expected):
-        raise ValueError('OFFICIAL_FLUX_SOURCE_MISMATCH')
+    require_reviewed_source(source)
```

이번 턴 코드/시험/속성의 전체 unified diff: FLUX_GUARD_CHANGES.patch(218줄).
SHA-256: 9097fccaefd64fb32ecd37c43460d588ef04fdcfb8bb8273194d9e05cea19b25.
이전 REPORT_REVIEW_FOLLOWUP.md와 patch는 역사로 보존하며 덮어쓰지 않는다.
