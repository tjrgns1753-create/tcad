# E6N-C 완료 보고: PN 감사의 거짓 정상 종료 차단과 원시 증거 재검토

## 1. 결론

검증 실패·미평가를 정상 종료로 전달하는 실행 계약 결함을 고쳤다.
새 107개 종료 반례, 기존 관련 테스트 3개, GitHub Windows 재검증,
다운로드 artifact 독립 대조를 완료했다. 새 물리 solve는 0회다.
이것은 PN 물리 승인이나 production 측정 허용이 아니다.

이번 재검증 작업은 PASS/RC=0이나, 그 작업이 검토한 과거 PN 감사는
NOT_EVALUATED/차단이며 보완된 실행 계약에서는 RC=1이다.
두 종료 코드의 대상이 다름을 반드시 구분한다.

## 2. 시작 상태와 영향 조사

시작 HEAD: 1e625da4948de63682ee9c7e6e5ec77520b598d3.
브랜치: claude/remote-runner. 추적 변경 없음. 기존 untracked는 보존했다.
Serena MCP는 이 세션에 노출되지 않아 rg/직접 읽기로 대체했다.

- 대상: judge_e6m.completion_exit_code(신규), PN 감사 run()의 마지막 반환.
- 호출: 실제 PN 감사 실행 파일 -> run_e6m.py subprocess -> 원격 프로필.
- 기존 판정기는 G1~G9를 나눠 반환하며 종속 범주를 차단한다.
- 실제 run()은 이를 출력하고 무조건 return 0 했다.
- 원격 드라이버는 자식 RC로 성공을 판단하므로 거짓 정상 종료가 전달된다.
- production PN sweep, canonical state, 도핑 write, 엔진 방정식, gate는 그대로다.
- 다른 감사 실행기의 종료 계약까지 해결했다고 주장하지 않는다.

## 3. 수정 전후와 정상 대조군

수정 전 무조건 return 0은 직접 소스/AST로 확인했다.
기존 원시 증거의 최신 판정은 G2 NOT_EVALUATED, G4~G9 차단이다.
기존 엔진 실행을 재현한 것은 아니다. 42회 solve는 과거 기록이다.

수정 후 같은 verdict의 completion_exit_code는 1이다.
완전 합성 PASS는 0이고, 각 G 범주의 FAIL/NOT_EVALUATED/차단/누락,
빈 checks/문자열 True/숫자 1/False/누락 boolean, 무결성 실패는 1이다.
합성 검사 107개가 통과했다. 이것은 물리 실험 107개가 아니다.

관련 검사:
- test_e6m_completion_exit_mock.py PASS
- test_e6m_judge_mock.py PASS
- test_e6m_execution_contract_mock.py PASS
- test_e6l_correction_mock.py PASS

## 4. 실제 원시 결과 재판정

| 범주 | 현재 판정 |
|---|---|
| 증거 무결성 | PASS |
| G1 기하/import | PASS |
| G2 gate/canonical 감사 | NOT_EVALUATED |
| G3 단위 | PASS |
| G4~G9 종속 물리 비교 | BLOCKED_GATE_OR_AUDIT_DOPING |

L0/L1/L2의 forward canonical 기록은 RECORDED_VALID.
세 reverse 기록은 NOT_RECORDED. 소급 생성하지 않았다.
옛 JSON의 전 범주 PASS를 원본에서 삭제하거나 고치지 않고,
새 재판정 파일에 현재 의미를 분리해 남겼다.

## 5. 원시 수치와 물리적 해석

아래는 차단된 감사의 사후 진단 수치이며 승인값이 아니다.

| 측정량 | 원시 데이터 재계산 |
|---|---|
| 최악 terminal KCL 상대 불일치 | 7.18271329684699e-5 (0.00718%) |
| 최대 동일 엔진 2D/1D 전류 상대 차이 | 3.199381193735343e-10 |
| 최대 y 전위 분산 | 2.220446049250313e-16 V |
| +0.6V 전류 L1/L2 상대 차이 | 5.277494783517904e-5 (0.00528%) |
| -1V 전류 L1/L2 상대 차이 | 4.7957054075647384e-5 (0.00480%) |
| -1V 접합 전계 L1/L2 상대 차이 | 0.004681732219974291 (0.468%) |

L2 J(+0.5V)=0.0038950895183886766 A/cm²,
J(+0.6V)=0.11820589992006583 A/cm²,
J(-1V)=-5.926495063083291e-7 A/cm².
원래 2D terminal 값은 A/cm이고 높이 1e-5cm로 나눈 진단이다.
실제 3D 장치의 총 전류 A로 혼동하지 않는다.

평형 L2 같은 접합 edge 평균끼리 비교하면:
PB 112173.85539036409 V/cm,
DEVSIM 112136.3558328944 V/cm, 차이 약 37.50 V/cm.
연속 중심값/edge 평균/공핍 근사 중심값은 서로 다른 측정량이다.
공핍 근사와의 차이를 바로 엔진 버그라고 판정하지 않는다.

x만 변하는 도핑, 전체 높이 접점, y 절연 경계는 1D 환원이 가능한
물리 대조군이다. y 변화가 없다는 것 자체는 오류가 아니다.
그러나 동일 엔진의 1D와 2D가 같다는 것은 독립 실험 검증이 아니고,
사용자가 만든 임의 2D 공정 구조의 PN 정확성을 승인하지 않는다.
E6N-B의 독립 2D manufactured Poisson 수렴과도 증거 역할이 다르다.

공식 DEVSIM 수송 helper는 SG형 전류식을 공개한다:
https://github.com/devsim/devsim/blob/main/python_packages/simple_dd.py
SG 방법의 연속/이산 구조 보존에 대한 연구:
https://arxiv.org/abs/2002.10133
두 출처는 구성식/방법론 근거이지 이 프로젝트의 제작 결과 인증이 아니다.
이번에는 구성식을 새로 구현하거나 설치 엔진을 수정하지 않았다.

## 6. 원격 실행과 독립 검증

PLAN 단독 커밋 8d7abdc, 구현 커밋 a556d65.
run: https://github.com/tjrgns1753-create/tcad/actions/runs/37422271669
실행 SHA a556d65615d8dad62c36323daccadedb0263a3d2.
GitHub-hosted Windows, Python 3.11.9, 검사 실행 18.112초.
엔진은 설치돼 있지만 프로필에서 NOT_IMPORTED. import 차단 hook 사용.
artifact remote-run-39의 원본은 raw/에 그대로 보존했다.

result.json SHA:
204532ccd9e3e05799dbca7ffb8b2a20d9621ff89f23c9544436d429057d39ee
run.log SHA:
29c1ed1d03376aacac27205f1c1ac0703bb853427a1217098888e2f61fa9f50a

독립 verifier는 출력/로그 크기와 해시, 외부 고정 실행 SHA,
미승인 상태, 원본 해시를 확인한다. pn_approved/gate_released/새 solve/
엔진 import/종료 코드/원본 불변 여부의 6개 위조 반례를 차단했다.

## 7. 발견한 줄바꿈 이동성 한계

NPZ 두 개는 로컬/원격 BYTE_IDENTICAL.
JSON 세 개와 옛 PLAN은 EXACT_CHECKOUT_CRLF_VARIANT_ONLY.
로컬 LF를 CRLF로 바꾼 바이트의 SHA가 원격 보고 해시와 정확히 같다.
해시 차이를 숨기거나 전체 원본이 바이트 동일하다고 주장하지 않는다.
실행 전후 각 환경 안에서는 원본이 불변이다.
원본은 재작성하지 않았다. 새 artifact에는 -text를 적용해 보존한다.

## 8. 승인 범위와 남은 작업

승인: 감사 결과 미완료/실패가 정상 성공으로 전달되는 결함 수정.
미승인: PN/DD 일반 검증, 공정 후 도핑 전달, production gate 해제.
다음 물리 작업은 기존 구조화 전이 메쉬에서 canonical forward/reverse를
각 fresh device에 기록하는 PN bias 파일럿이다. 이전 누락 기록을 새로
만드는 것이 아니라 새 실행으로만 확보한다. 비용/기준은 결과 전에 고정한다.
1D 환원 불가능성을 PN 실행의 필수조건으로 삼지 않는다. 실제 2D 문제
검증과 y 불변 대조군은 별도의 증거로 다룬다.

## 9. 무변경과 정적 검사

tcad/, tcad_2d_stagewise.py, 엔진 내부와 gate 변경 0.
기존 E6M/E6K raw 및 PLAN diff 0. 전체 회귀/main 병합 없음.
일반 git diff --check RC=0.
새 엔진 import/solve 0. 이전 42회 solve 기록의 의미 변경 없음.
추적 working tree는 최종 증거 커밋 후 별도로 확인한다.

## 10. 실제 semantic diff

아래는 a556d65의 구현 전체 unified diff다. 원본 증거와 보고서 자체는 제외했다.
독립 artifact verifier는 이후 추가된 읽기 전용 도구이며 소스 전체를
verify_artifact.py에서 확인할 수 있다.

```diff
diff --git a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py
index d3c1df6..1a6f89f 100644
--- a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py
+++ b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py
@@ -166,6 +166,29 @@ def _b(name, cond, value=None):
     return {"name": name, "value": value, "pass": bool(cond)}


+def completion_exit_code(verdicts):
+    """Exit status for this limited audit, never a production physics approval.
+
+    Missing, blocked or unevaluated evidence must not become a green job.
+    Keep separate category verdicts; this only determines process success.
+    """
+    if not isinstance(verdicts, dict):
+        return 1
+    integrity = verdicts.get("EVIDENCE_INTEGRITY")
+    if (not isinstance(integrity, dict) or integrity.get("verdict") != "PASS"
+            or integrity.get("problems") != []):
+        return 1
+    for name in CATEGORIES:
+        record = verdicts.get(name)
+        if not isinstance(record, dict) or record.get("verdict") != "PASS":
+            return 1
+        checks = record.get("checks")
+        if (not isinstance(checks, list) or not checks
+                or any(not isinstance(c, dict) or c.get("pass") is not True for c in checks)):
+            return 1
+    return 0
+
+
 def judge(raw, npz, e6k_json, e6k_npz, e6j=None, *, expected_plan_sha256=None):
     problems, S, c1 = validate(raw, npz, e6k_json, e6k_npz, e6j, expected_plan_sha256=expected_plan_sha256)
     res = {"judge_version": VERSION, "EVIDENCE_INTEGRITY": {"verdict": "PASS" if not problems else "EVIDENCE_INTEGRITY_FAIL", "problems": problems}}
diff --git a/docs/audits/2026-10-06-e6nc-pn-completion-contract/revalidate.py b/docs/audits/2026-10-06-e6nc-pn-completion-contract/revalidate.py
new file mode 100644
index 0000000..705d942
--- /dev/null
+++ b/docs/audits/2026-10-06-e6nc-pn-completion-contract/revalidate.py
@@ -0,0 +1,96 @@
+"""원본 PN 증거 재검토와 종료 계약 시험. 엔진 import/solve 없음."""
+import ast
+import hashlib
+import json
+import os
+from pathlib import Path
+import runpy
+import sys
+
+HERE = Path(__file__).resolve().parent
+ROOT = HERE.parents[2]
+PLAN_SHA = '836dfbaff593b8b20ad702f0bbffa6c941770581cd67715e912f29476aa1e2e0'
+BASE = ROOT / 'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency'
+DATA = BASE / 'data/remote_run_36904995835/remote-run-32/outputs/e6m_out'
+REF = ROOT / 'docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out'
+UNIT = ROOT / 'docs/audits/2026-10-01-batch7h-e6j-current-unit-and-pn-plan/data/remote_run_36759423132/remote-run-24/outputs/e6j_out/gui_unit_contract.json'
+TESTS = ('test_e6m_completion_exit_mock.py', 'test_e6m_judge_mock.py',
+         'test_e6m_execution_contract_mock.py', 'test_e6l_correction_mock.py')
+
+
+def no_engine(event, args):
+    if event == 'import' and args[0].split('.')[0] in ('devsim', 'viennaps', 'viennals'):
+        raise RuntimeError('ENGINE_IMPORT_FORBIDDEN')
+
+
+def main():
+    sys.addaudithook(no_engine)
+    if hashlib.sha256((HERE / 'PLAN.md').read_bytes().replace(b'\r\n', b'\n')).hexdigest() != PLAN_SHA:
+        raise ValueError('PLAN_HASH_MISMATCH')
+    if '--local' not in sys.argv and (os.name != 'nt' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'):
+        raise ValueError('REMOTE_WINDOWS_REQUIRED')
+    sys.path.insert(0, str(ROOT))
+    sys.path.insert(0, str(BASE / 'scripts'))
+    import numpy as np
+    import judge_e6m as J
+    import e6m_metrics as M
+    preserved = (DATA / 'pn_2d_consistency.json', DATA / 'arrays.npz', REF / 'pn_1d_diagnostic.json', REF / 'states.npz',
+                 BASE / 'PLAN.md', UNIT)
+    hashes = lambda: {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in preserved}
+    before = hashes()
+    tests = []
+    for name in TESTS:
+        path = ROOT / 'tests/unit' / name
+        old_argv = sys.argv
+        try:
+            sys.argv = [str(path)]
+            try:
+                runpy.run_path(str(path), run_name='__main__')
+            except SystemExit as exc:
+                if exc.code not in (0, None):
+                    raise
+        finally:
+            sys.argv = old_argv
+        tests.append({'test': name, 'status': 'PASS'})
+    raw = json.loads((DATA / 'pn_2d_consistency.json').read_text(encoding='utf-8'))
+    ref = json.loads((REF / 'pn_1d_diagnostic.json').read_text(encoding='utf-8'))
+    unit = json.loads(UNIT.read_text(encoding='utf-8'))
+    with np.load(DATA / 'arrays.npz', allow_pickle=False) as arrays, np.load(REF / 'states.npz', allow_pickle=False) as ref_arrays:
+        verdicts = J.judge(raw, arrays, ref, ref_arrays, unit)
+        metrics = M.compute(raw, arrays, ref, ref_arrays)
+    rc = J.completion_exit_code(verdicts)
+    if rc != 1 or verdicts['G2_PRODUCTION_GATE_HELD_AND_AUDIT_DOPING']['verdict'] != 'NOT_EVALUATED':
+        raise AssertionError('PRESERVED_INCOMPLETE_EVIDENCE_MUST_NOT_GREEN')
+    old_verdicts = {k: v['verdict'] for k, v in raw['verdicts'].items() if isinstance(v, dict) and 'verdict' in v}
+    statuses = {k: v['verdict'] for k, v in verdicts.items() if isinstance(v, dict) and 'verdict' in v}
+    source = ROOT / 'tests/integration/test_pn_2d_1d_consistency_real.py'
+    ast.parse(source.read_text(encoding='utf-8'))
+    after = hashes()
+    if before != after or {'devsim', 'viennaps', 'viennals'}.intersection(sys.modules):
+        raise AssertionError('RAW_CHANGED_OR_ENGINE_IMPORTED')
+    cur = metrics['levels']['L2']['currents']
+    diagnostics = {
+        'current_density_L2_A_per_cm2': {k: v['J_2d_A_per_cm2'] for k, v in cur.items()},
+        'max_kcl_relative': max(v['kcl_rel'] for L in metrics['levels'].values() for v in L['currents'].values()),
+        'max_current_relative_2d_vs_1d': max(v['rel_diff'] for L in metrics['levels'].values() for v in L['currents'].values()),
+        'max_y_potential_spread_V': max(p['psi_y_spread_V'] for L in metrics['levels'].values() for p in L['profiles'].values()),
+        'mesh_sensitivity': metrics['mesh_sensitivity'],
+        'equilibrium': metrics['equilibrium_diagnostics_not_judged'],
+    }
+    report = dict(status='PASS', source_sha=os.environ.get('GITHUB_SHA'), plan_sha=PLAN_SHA,
+                  tests=tests, original_recorded_verdicts=old_verdicts, current_verdicts=statuses,
+                  revalidated_audit_exit_code=rc, canonical_evidence=verdicts['canonical_evidence'],
+                  raw_hashes=before, raw_hashes_unchanged=True, diagnostics_not_approved=diagnostics,
+                  recorded_historical_solves=raw['total_solves'], engine_imports=0, new_solves=0,
+                  pn_approved=False, gate_released=False)
+    if '--local' not in sys.argv:
+        out = ROOT / 'e6nc_out'
+        out.mkdir(exist_ok=False)
+        (out / 'result.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
+    print(json.dumps(report, indent=2))
+    # This revalidation checks that incomplete evidence is rejected, not that PN passed.
+    return 0
+
+
+if __name__ == '__main__':
+    raise SystemExit(main())
diff --git a/remote/profiles.py b/remote/profiles.py
index 1fc7cac..ba395c5 100644
--- a/remote/profiles.py
+++ b/remote/profiles.py
@@ -11,6 +11,24 @@ remote/request.json that selects it. See remote/README.md.

 # Every profile runs as:  <venv python> <entry> <args...>   (no shell)
 PROFILES = {
+    "e6nc_pn_completion_revalidation": {
+        "description": "Engine-free PN evidence revalidation and rejection of incomplete audit success; no physical solve.",
+        "entry": "docs/audits/2026-10-06-e6nc-pn-completion-contract/revalidate.py",
+        "args": [], "params": {}, "timeout_s": 120, "engine_info": False,
+        "inputs": [
+            "docs/audits/2026-10-06-e6nc-pn-completion-contract/PLAN.md",
+            "docs/audits/2026-10-06-e6nc-pn-completion-contract/revalidate.py",
+            "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py",
+            "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/e6m_metrics.py",
+            "tests/integration/test_pn_2d_1d_consistency_real.py",
+            "tests/unit/test_e6m_completion_exit_mock.py",
+            "tests/unit/test_e6m_judge_mock.py",
+            "tests/unit/test_e6m_execution_contract_mock.py",
+            "tests/unit/test_e6l_correction_mock.py"
+        ],
+        "outputs": [{"glob": "e6nc_out/**/*", "max_mb": 10}],
+        "regenerate": "Recheck stored evidence only; incomplete historical PN is not approved.",
+    },
     "e6nb_native_2d_control": {
         "description": "Fixed native positive/negative controls and four manufactured 2D Poisson solves; not PN physics.",
         "entry": "docs/audits/2026-10-06-e6nb-native-2d-control/run_control.py",
diff --git a/remote/request.json b/remote/request.json
index 5a1111d..00288b1 100644
--- a/remote/request.json
+++ b/remote/request.json
@@ -1,7 +1,7 @@
 {
  "schema": 1,
- "request_id": "e6nb-native-2d-control-002",
- "profile": "e6nb_native_2d_control",
+ "request_id": "e6nc-pn-completion-001",
+ "profile": "e6nc_pn_completion_revalidation",
  "params": {},
- "note": "Fixed analytical native positive control then manufactured 2D Poisson convergence; four scalar solves, not PN/DD."
+ "note": "Engine-free stored PN evidence revalidation; historical incomplete audit must not become green. No new solve."
 }
diff --git a/tests/integration/test_pn_2d_1d_consistency_real.py b/tests/integration/test_pn_2d_1d_consistency_real.py
index 8755938..c8de934 100644
--- a/tests/integration/test_pn_2d_1d_consistency_real.py
+++ b/tests/integration/test_pn_2d_1d_consistency_real.py
@@ -260,7 +260,7 @@ def run(out_dir):
         if isinstance(v, dict) and "verdict" in v:
             print(k, v["verdict"], [c["name"] for c in v.get("checks", []) if not c["pass"]][:5], v.get("problems", [])[:3])
     print("total solves:", raw["total_solves"], "leaked devices:", raw["leaked_devices"])
-    return 0
+    return J.completion_exit_code(verdict)


 if __name__ == "__main__":
diff --git a/tests/unit/test_e6m_completion_exit_mock.py b/tests/unit/test_e6m_completion_exit_mock.py
new file mode 100644
index 0000000..50bb359
--- /dev/null
+++ b/tests/unit/test_e6m_completion_exit_mock.py
@@ -0,0 +1,53 @@
+"""엔진 없이 PN 감사의 실패/미평가가 정상 종료되지 않는지 검증한다."""
+import ast
+import copy
+from pathlib import Path
+import sys
+
+ROOT = Path(__file__).resolve().parents[2]
+sys.path.insert(0, str(ROOT / 'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts'))
+import judge_e6m as J
+
+
+def run():
+    valid = {'EVIDENCE_INTEGRITY': {'verdict': 'PASS', 'problems': []}}
+    valid.update({k: {'verdict': 'PASS', 'checks': [{'pass': True}]} for k in J.CATEGORIES})
+    assert J.completion_exit_code(valid) == 0
+    count = 1
+    for name in J.CATEGORIES:
+        for status in ('FAIL', 'NOT_EVALUATED', 'BLOCKED_GATE_OR_AUDIT_DOPING', 'EVIDENCE_INTEGRITY_FAIL'):
+            v = copy.deepcopy(valid)
+            v[name]['verdict'] = status
+            assert J.completion_exit_code(v) == 1, (name, status)
+            count += 1
+        v = copy.deepcopy(valid)
+        del v[name]
+        assert J.completion_exit_code(v) == 1
+        count += 1
+        for checks in ([], None, [{'pass': 1}], [{'pass': 'True'}], [{'pass': False}], [{}]):
+            v = copy.deepcopy(valid)
+            v[name]['checks'] = checks
+            assert J.completion_exit_code(v) == 1
+            count += 1
+    for record in (None, {}, {'verdict': 'PASS'}, {'verdict': 'PASS', 'problems': ['missing']},
+                   {'verdict': 'FAIL', 'problems': []}):
+        v = copy.deepcopy(valid)
+        v['EVIDENCE_INTEGRITY'] = record
+        assert J.completion_exit_code(v) == 1
+        count += 1
+    assert J.completion_exit_code(None) == 1
+    count += 1
+    source = ROOT / 'tests/integration/test_pn_2d_1d_consistency_real.py'
+    tree = ast.parse(source.read_text(encoding='utf-8'))
+    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
+    returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
+    assert len(returns) == 1
+    assert ast.unparse(returns[0].value) == 'J.completion_exit_code(verdict)'
+    count += 1
+    assert not {'devsim', 'viennaps', 'viennals'}.intersection(sys.modules)
+    print(f'PASS: {count} completion-contract cases; engine imports=0; solves=0')
+    return count
+
+
+if __name__ == '__main__':
+    run()

```
