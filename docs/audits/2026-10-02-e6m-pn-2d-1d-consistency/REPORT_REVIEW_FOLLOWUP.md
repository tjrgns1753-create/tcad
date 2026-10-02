# E6M 재검토 후 보완 보고
## 판정과 범위
시작 HEAD `cdcb830ff07ef5e8f4938c111eaa18be546de6e7`, 브랜치 `claude/remote-runner`.
추적 파일의 시작 변경·staged 변경은 0이었다. 기존 untracked 증거는 보존했다.
관련 지침을 읽고, 감사 코드의 모순을 차단하는 것이 실제 물리 상태를 숨기지 않는 TCAD 방향인지 확인했다.
새 물리 모델이 아니라 증거 계약을 보완한 작업이다. RC=0이나 합성 PASS를 PN 물리 승인으로 바꾸지 않는다.
엔진 import·실제 mesh import·실제 solve·전체 회귀·원격 물리 계산은 모두 0회다.

## 1. 수정 전/후 반례
| 항목 | 수정 전 | 수정 후 |
|---|---|---|
| 기존 canonical unresolved=1, 새 forward unresolved=0 | 무결성 및 G1~G9 PASS | G2 FAIL, G4~G9 차단 |
| 서로 일치하고 완전한 canonical 기록 | 모든 범주 PASS | 모든 범주 PASS |
| PLAN 불일치/누락 | 실행 진입에 사전 SHA 비교 없음 | 엔진 준비 이전 PLAN_PREFLIGHT_BLOCKED |
| 엔진 solve 예외 | 성공 카운터 0뿐, 호출 시도 미기록 | attempts=1, successes=0, solve_failures=1 |
| solve 성공 후 snapshot 예외 | 실패 단계 구분 불가 | attempts=1, successes=1, snapshot_failures=1 |
| 정상 solve 및 snapshot | 성공 카운터 1 | attempts=1, successes=1, 실패 카운터 0 |

canonical 이전 판정기는 시작 커밋의 git blob을 직접 읽어 재현했다.
수치는 `followup_result.json`, 재현 코드는 `followup_evidence.py`다.
PLAN과 observer 테스트는 actual run entry 및 actual Obs에 합성 trap을 연결했다.
실제 엔진을 mock 값으로 대체해 물리 PASS를 주장하는 테스트가 아니다.

## 2. 변경 파일·심볼·영향
- `scripts/judge_e6m.py:require_plan`(63행): 실제 고정 SHA와 LF 정규화 PLAN을 대조한다.
  OSError·해시 불일치를 명시적 차단으로 변환한다. validate의 사후 검사도 같은 helper를 사용한다.
- `judge`(legacy 확인 199행·상호 대조 203행):
  기존 forward audit 자체를 완전·resolved 조건으로 검사한다.
  새 forward record가 함께 있으면 세 count의 일치도 요구한다.
  어느 한쪽이 unresolved/mismatch면 G2가 실패하고 종속 판정이 차단된다.
  역방향 과거 미기록은 그대로 NOT_RECORDED다.
- `judge`(235행): 새 호출 시도/실패 필드가 있는 증거는 완전성·성공 카운터 대응을 검사한다.
  과거 증거에는 새 필드를 생성하지 않는다.
- `tests/integration/test_pn_2d_1d_consistency_real.py:Obs.install`(51행):
  호출 직전 attempts 증가, 반환 후 기존 solves 증가, engine 예외와 snapshot 예외를 별도 기록한다.
  기존 solves는 성공한 solve 의미를 그대로 유지한다.
- 같은 파일 `run_level`(175·182·221행):
  production gate probe가 시도한 solve도 0회여야 한다.
  각 device에 attempts/failures/snapshot_failures/call_log를 추가 저장한다.
- 같은 파일 `run`(236행): 첫 실행 조건이 require_plan이다.
  backend import/require_devsim 및 후속 기하·도핑·sweep 전에 검사한다.
- 기존 `test_e6m_judge_mock.py`: legacy count 모순과 호출 카운터 모순 반례 추가.
- 신규 `test_e6m_execution_contract_mock.py`: 실제 run entry의 PLAN 차단 및 실제 Obs의 세 경로 검증.
- `PLAN_E6N_DRAFT.md`: 실패 후보와 기하 지원 후보를 구분하고 다음 실행 승인 경계를 유지한다.
- 신규 기하 memo·기하 probe·기존 증거 repro·JSON은 감사 자료다.

## 3. 실행 전 PLAN 차단
누락 및 다른 PLAN에서 backend import=0, backend prepare=0, mesh callback=0, run_level callback=0.
따라서 이 테스트 경로의 도핑 쓰기·sweep·solve는 0회다.
정상 LF와 CRLF PLAN은 같은 고정 SHA로 통과해 합성 backend trap에 도달한다.
유효한 PLAN인데 모든 실행을 막는 거짓 성공이 아님을 대조군으로 확인했다.
실제 예상 SHA는 기존 PLAN의 `5aeb9dc28bf79f82404d728f9507c6a8208c531cc9bff32829cbf46e58e5410f`다.

## 4. 테스트·원본 재판정
실행한 테스트 파일 세 개는 모두 RC=0이다.
- test_e6m_judge_mock.py
- test_e6m_execution_contract_mock.py
- test_e6l_correction_mock.py

기존 E6M 원본의 판정은 시작 커밋 대비 변하지 않았다:
EVIDENCE_INTEGRITY/G1/G3 PASS, G2 NOT_EVALUATED, G4~G9 BLOCKED_GATE_OR_AUDIT_DOPING.
당시 forward canonical은 RECORDED_VALID, reverse는 NOT_RECORDED다.
원본 도핑·전기장·좌표를 오류라고 재분류하지 않았다.
E6M JSON/NPZ, E6K JSON/NPZ 및 원본 PLAN의 5개 바이트가 시작 커밋 blob과 동일하며 SHA도 동일하다.
전체 SHA는 `followup_result.json:original_hashes_unchanged`에 있다.
기존 log·E6K/E6L 판정 문서·기존 PLAN·physics tolerance는 수정하지 않았다.

## 5. E6N 기하 후보 — 기하만 승인
원래 세 y line 후보는 모든 등급에서 TRANSITION_ASPECT로 실패함을 재현했다.
현재 source _strip_depths와 template 조건에서 y 행 수를 계산했다.
규칙은 계산 전에 `GEOMETRY_DESIGN_RULE.md`로 고정했다.
그 SHA는 `e51caf5218ba725b99a918c16501e725c62ae87fa389ad28f6ef29c06ebce1c0`다.

w≥(H/ny)/2^(d+1)에서 허용 base-row 높이를 유도하고 최소 2의 거듭제곱 ny를 선택했다.
domain, x 좌표, 접합 위치·폭, 도핑·접점·물리 파라미터는 변하지 않았다.

| 후보 | 초기 y 행 | 노드 | 삼각형 | exact 둔각/퇴화/hanging node |
|---|---:|---:|---:|---|
| N0 | 16 | 8037 | 15264 | 0 / 0 / 0 |
| N1 | 32 | 31173 | 60736 | 0 / 0 / 0 |
| N2 | 64 | 122761 | 242304 | 0 / 0 / 0 |

세 후보 모두 exact 면적·경계·conformity 검사를 통과했다. 큰 후보도 hanging node 검사를 생략하지 않았다.
요소 수는 할당 전에 산정했고, 실제 수와 일치했다. 각 400000 상한·총 1200000 상한 안이다.
실제 총 삼각형은 318304다. 기존 E6G 빌더를 직접 호출했으며 새 remesher는 없다.
재현: `e6n_geometry_preflight.py`, 수치: `e6n_geometry_result.json`.

미검증: DEVSIM NodeVolume, EdgeCouple/EdgeLength의 실제 조립, 이산 1D 비환원성, PN/DD/IV 수렴·정확도,
원격 runtime·메모리 비용. 기하 PASS를 이러한 승인으로 바꾸지 않는다.
특히 exact rational 후처리는 저장 float의 생성 반올림을 복원하지 않는다.
다음 단계는 PLAN 검토이며 이번 작업으로 원격 solve가 자동 승인되지 않는다.

## 6. Serena investigation
이 세션에는 Serena 호출 도구가 없어 rg/직접 읽기로 대체했다. active project는 도구로 검증할 수 없었다.
관련 서버/언어 서버 프로세스는 발견했지만 호출 가능 여부와 구분했다.
추가로 기존 run_all.py --mode holdout 프로세스가 있어 건드리지 않았다. 용도·실행 위치는 미확정이다.
조회한 symbols: require_canonical, guarded_audit, judge/validate, run/run_level, Obs.install/restore,
structured_grid_of, _strip_depths, structured_lateral_refine, check_conformity.
caller: 감사 run이 run_level/Obs/helper를 사용하고 합성 테스트가 같은 함수 경계를 호출한다.
E6G builder의 production caller는 mesh_import.py의 implant-window 분기다. 이 production caller는 변경하지 않았다.
우회 경로: 실행 전 PLAN 검사가 없던 run entry를 사전 검사로 막았다.
기존/새 canonical을 선택만 하던 판정 경로에 기록 일치 검사를 추가했다.
DEVSIM/ViennaPS 공식 API·엔진 내부 변경, production gate 완화는 없다.
별도 real backend 검증은 이번 배치에서 실행하지 않았다.

## 7. Change diff
전체 unabridged zero-context 패치: `CHANGE_DIFF_FOLLOWUP.patch`.
SHA-256: `3bd4fc0c16923457ebc11538dacfb86ab27236223f6b079d3225331718443394`.
패치는 코드·테스트·PLAN·감사 증거를 포함하며 이 보고서와 패치 자체는 자기 참조 때문에 제외한다.
아래는 모든 hunk header와 변경 코드다. JSON은 발췌이며 전체는 패치 및 원시 JSON 파일을 참조한다.
시작 working-tree tracked diff가 0이어서 모든 표시 hunk는 이번 배치의 변경이다.

### docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/GEOMETRY_DESIGN_RULE.md

```diff
diff --git a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/GEOMETRY_DESIGN_RULE.md b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/GEOMETRY_DESIGN_RULE.md
new file mode 100644
index 0000000..f0a3cb2
--- /dev/null
+++ b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/GEOMETRY_DESIGN_RULE.md
@@ -0,0 +1,20 @@
+# E6N 기하 재설계 규칙 — 결과 확인 전 고정
+
+domain·도핑·접점·온도·수명·이동도는 기존 E6M 그대로다.
+centers=[0], half_widths=[0.1]µm도 유지하고 기존 E6G 빌더만 사용한다.
+바꾸는 것은 초기 y 격자의 행 수뿐이다. 원래 2행은 전이 폭에 비해 너무 높다.
+
+기존 _strip_depths가 생성하는 각 한쪽 전이 strip의 width=w, depth=d를 읽는다.
+기존 빌더 조건 w≥(H/ny)/2^(d+1)에서
+허용 base-row 높이 b=min(2*w*2^d)를 정확 Fraction 산술로 유도한다.
+H=0.1µm를 유지하면서 H/ny≤b인 가장 작은 2의 거듭제곱 ny를 선택한다.
+실제 생성 좌표는 다시 기존 빌더의 exact aspect 검사에 통과해야 한다.
+이 규칙은 PN solve 결과나 기대 전류를 사용하지 않는다.
+
+세 등급 모두 같은 규칙을 사용한다. 요소 수는 할당 전에 strip별 template 수를 합산한다.
+각 후보 400000 삼각형, 세 후보 합계 1200000을 상한으로 한다.
+초과·지원 불가면 자동으로 폭이나 physics를 바꾸지 않고 중단한다.
+모든 후보의 둔각·퇴화·hanging node·면적·경계 검사는 생략하지 않는다.
+
+이 단계는 순수 기하 검사다. DEVSIM/ViennaPS import와 solve를 실행하지 않는다.
+전이 stencil의 실제 조립 가중치는 아직 없으므로 1D 이산 환원이 깨졌다고 승인하지 않는다.

```

### docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/PLAN_E6N_DRAFT.md

```diff
diff --git a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/PLAN_E6N_DRAFT.md b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/PLAN_E6N_DRAFT.md
index 49cca22..7f43495 100644
--- a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/PLAN_E6N_DRAFT.md
+++ b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/PLAN_E6N_DRAFT.md
@@ -2 +2 @@
-상태: 검토용 초안. 이번 배치에서 mesh 생성·엔진 import·solve를 실행하지 않는다.
+상태: 검토용 초안. 이번 보완 배치에서는 순수 기하 생성·검사만 실행했다. 엔진 import·solve는 0회다.
@@ -24,2 +24,17 @@ production caller와 지원 범위는 E6G 그대로 유지한다.
-후보 N0/N1/N2는 E6K L0/L1/L2의 저장 x 좌표와 E6M의 세 y line을 초기 입력으로 사용한다.
-같은 요청 centers=[0.0], half_widths=[0.1]µm을 빌더에 전달하는 단일 ring 후보로 시작한다.
+원래 E6K L0/L1/L2의 저장 x 좌표와 E6M의 세 y line을 사용하는 후보는
+세 등급 모두 TRANSITION_ASPECT로 실패했다. 이 후보는 폐기하며 원격으로 실행하지 않는다.
+새 후보 N0/N1/N2는 같은 x 좌표·domain·centers=[0.0], half_widths=[0.1]µm을 유지한다.
+초기 y 행 수만 기존 빌더의 실제 aspect 조건에서 산정한다.
+한쪽 전이 strip의 폭 w·깊이 d에서 허용 base-row 높이 b=min(2*w*2^d)를 구하고,
+H/ny≤b인 최소 2의 거듭제곱 ny를 선택한다. PN 결과를 사용한 튜닝이 아니다.
+규칙은 기하 실행 전에 GEOMETRY_DESIGN_RULE.md로 고정했다.
+
+| 후보 | 초기 y 행 | 최대 초기 행 높이 | 노드 | 삼각형 | 기하 판정 |
+|---|---:|---:|---:|---:|---|
+| N0 | 16 | 6.25nm | 8037 | 15264 | GEOMETRY_PREFLIGHT_PASS_ONLY |
+| N1 | 32 | 3.125nm | 31173 | 60736 | GEOMETRY_PREFLIGHT_PASS_ONLY |
+| N2 | 64 | 1.5625nm | 122761 | 242304 | GEOMETRY_PREFLIGHT_PASS_ONLY |
+
+실측 합계는 318304 삼각형이다. 각 후보의 exact 둔각·퇴화·hanging node는 모두 0,
+면적과 직사각형 경계는 정확 일치다. 재현 코드/수치는 e6n_geometry_preflight.py와
+e6n_geometry_result.json에 보존한다. DEVSIM import·NodeVolume·조립·PN 수렴은 미검증이다.
@@ -28,2 +43 @@ production caller와 지원 범위는 E6G 그대로 유지한다.
-현재 E6M near-junction 비등방성 때문에 TRANSITION_ASPECT가 날 가능성이 있다.
-세 후보의 기하 preflight가 통과하기 전에는 실행 가능·비용 확정이라고 주장하지 않는다.
+기하 지원은 확인했지만 전체 solve 시간과 메모리 비용은 아직 실측하지 않았다.
@@ -33 +47 @@ production caller와 지원 범위는 E6G 그대로 유지한다.
-이번 초안에서 새 y 격자나 폭을 자동 선택하는 튜닝은 허용하지 않는다.
+위의 사전 고정된 기하 산정 외에 결과에 맞춘 y 격자·폭 변경은 허용하지 않는다.
@@ -42,0 +57,2 @@ NodeVolume을 실제로 저장하고 E6M의 반복 row stencil과 어떻게 달
+이는 저장된 수치에 대한 후처리 산술 오차를 없애는 것뿐이며, 엔진의 기하·계수 생성 과정에서
+이미 생긴 반올림 오차를 복원하지 않는다. 미세한 비영 차이만으로 강한 비환원성을 승인하지 않는다.

```

### docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_preflight.py

```diff
diff --git a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_preflight.py b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_preflight.py
new file mode 100644
index 0000000..89592ef
--- /dev/null
+++ b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_preflight.py
@@ -0,0 +1,98 @@
+"""Pure geometry only: reuse E6G builder, no backend imports or solves."""
+import hashlib
+import importlib.util
+import json
+import sys
+from fractions import Fraction
+from pathlib import Path
+from unittest.mock import patch
+
+import numpy as np
+
+ROOT = Path.cwd()
+AUDIT = ROOT / "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency"
+sys.path.insert(0, str(AUDIT / "scripts"))
+import e6m_metrics as M
+
+
+def load(name, path):
+    spec = importlib.util.spec_from_file_location(name, path)
+    module = importlib.util.module_from_spec(spec)
+    spec.loader.exec_module(module)
+    return module
+
+
+def main():
+    R = load("e6g_pure_builder", ROOT / "tcad/device/devsim/mesh_refine.py")
+    C = load("e6h_exact_geometry", ROOT / "docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/scripts/conformity_e6h.py")
+    old = np.load(AUDIT / "data/remote_run_36904995835/remote-run-32/outputs/e6m_out/arrays.npz")
+    ref = np.load(ROOT / "docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out/states.npz")
+    out = {"design_rule_sha256": hashlib.sha256((Path(__file__).parent / "GEOMETRY_DESIGN_RULE.md").read_bytes()).hexdigest(),
+           "request": {"centers_um": [0.0], "half_widths_um": [0.1]}, "levels": {}}
+    for lv in M.LEVELS:
+        p, t = old[lv + "__points_um"], old[lv + "__triangles"]
+        tags = np.zeros(len(t), dtype=np.int32)
+        rec = out["levels"][lv] = {}
+        try:
+            R.structured_lateral_refine(p, t, tags, [0.0], [0.1])
+        except (R.StructuredRemeshAborted, R.StructuredRemeshUnsupported) as exc:
+            rec["original_candidate"] = {"reason": exc.reason, "detail": str(exc)}
+        else:
+            raise AssertionError("the formerly blocked input unexpectedly succeeded")
+        xs, ys, _, _ = R.structured_grid_of(p, t, tags)
+        leaves = R._strip_depths(xs, [0.0], [0.1], 400000)
+        bounds, template_count, transitions = [], 0, []
+        for k, (a, b, d, _) in enumerate(leaves):
+            fl = k > 0 and leaves[k - 1][2] == d + 1
+            fr = k + 1 < len(leaves) and leaves[k + 1][2] == d + 1
+            template_count += (4 if fl and fr else 3 if fl or fr else 2) * 2**d
+            if fl != fr:
+                bounds.append(2 * (Fraction(b) - Fraction(a)) * 2**d)
+                transitions.append({"x_min_um": a, "x_max_um": b, "depth": d})
+        assert bounds, "a non-transition candidate is outside this experiment"
+        bound = min(bounds)
+        ny = 1
+        height = Fraction(float(M.H_UM))
+        while height / ny > bound:
+            ny *= 2
+        rec.update(base_rows=ny, base_row_height_um=float(height / ny), exact_aspect_base_height_bound_um=float(bound),
+                   planned_triangles=ny * template_count, transition_strips=transitions)
+        if ny * template_count > 400000:
+            rec["candidate_status"] = "RESOURCE_CAP"
+            continue
+        x1 = M.e6k_snapshot(ref, lv, "rev", 0.0)["x"]
+        with patch.object(M, "Y_LINES_UM", np.linspace(-M.H_UM, 0.0, ny + 1).tolist()):
+            pp, tt = M.build_mesh(x1)
+        assert np.array_equal(np.unique(pp[:, 0]), xs), "x geometry changed"
+        try:
+            pp, tt, gg, report = R.structured_lateral_refine(pp, tt, np.zeros(len(tt), dtype=np.int32), [0.0], [0.1])
+        except (R.StructuredRemeshAborted, R.StructuredRemeshUnsupported) as exc:
+            rec["candidate_status"] = exc.reason
+            rec["detail"] = str(exc)
+            continue
+        coords = C._dyadic_ints(pp[:, :2].reshape(-1).tolist())
+        xy = list(zip(coords[0::2], coords[1::2]))
+        obtuse = 0
+        for tri in tt.tolist():
+            q = [xy[i] for i in tri]
+            for i in range(3):
+                a, b, c = q[i], q[(i + 1) % 3], q[(i + 2) % 3]
+                obtuse += (b[0] - a[0]) * (c[0] - a[0]) + (b[1] - a[1]) * (c[1] - a[1]) < 0
+        exact = C.check_conformity(pp, tt)
+        rec.update(nodes=len(pp), triangles=len(tt), exact_obtuse_angles=obtuse, conformity=exact,
+                   numeric_geometry=M.geometry_checks(pp, tt), builder_report=report)
+        assert len(tt) == rec["planned_triangles"]
+        assert np.array_equal(np.unique(gg), [0])
+        assert np.min(pp[:, 0]) == -20.0 and np.max(pp[:, 0]) == 20.0
+        assert np.min(pp[:, 1]) == -0.1 and np.max(pp[:, 1]) == 0.0
+        assert exact["pass"] and obtuse == 0
+        rec["candidate_status"] = "GEOMETRY_PREFLIGHT_PASS_ONLY"
+        print(lv, ny, len(pp), len(tt), "geometry PASS", flush=True)
+    out["engine_imports"] = len([n for n in sys.modules if n in ("devsim", "viennaps")])
+    out["real_solves"] = 0
+    assert out["engine_imports"] == 0
+    print(json.dumps(out, indent=2, default=str))
+
+
+if __name__ == "__main__":
+    main()

```

### docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_result.json

```diff
diff --git a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_result.json b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_result.json
@@ -0,0 +1,216 @@
+{
+  "design_rule_sha256": "e51caf5218ba725b99a918c16501e725c62ae87fa389ad28f6ef29c06ebce1c0",
+  "request": {
+    "centers_um": [
+      0.0
+    ],
+    "half_widths_um": [
+      0.1
... 원시 JSON 전체는 패치 및 별도 파일 참조 ...
```

### docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/followup_evidence.py

```diff
diff --git a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/followup_evidence.py b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/followup_evidence.py
new file mode 100644
index 0000000..dff105f
--- /dev/null
+++ b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/followup_evidence.py
@@ -0,0 +1,60 @@
+"""Read-only before/after canonical repro and original evidence comparison."""
+import copy
+import hashlib
+import json
+import runpy
+import subprocess
+import sys
+import types
+from pathlib import Path
+
+import numpy as np
+
+ROOT = Path.cwd()
+REL = "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency"
+BASE = "cdcb830ff07ef5e8f4938c111eaa18be546de6e7"
+sys.path.insert(0, str(ROOT / REL / "scripts"))
+import judge_e6m as J
+
+
+def compact(result):
+    return {k: v["verdict"] for k, v in result.items() if isinstance(v, dict) and "verdict" in v}
+
+
+def main():
+    old = types.ModuleType("judge_before_followup")
+    old.__file__ = str(ROOT / REL / "scripts/judge_e6m.py")
+    src = subprocess.check_output(["git", "show", BASE + ":" + REL + "/scripts/judge_e6m.py"]).decode("utf-8")
+    exec(compile(src, old.__file__, "exec"), old.__dict__)
+    test = runpy.run_path(str(ROOT / "tests/unit/test_e6m_judge_mock.py"))
+    r = copy.deepcopy(test["RAW"])
+    r["levels"]["L2"]["audit_doping"]["canonical_unresolved"] = 1
+    args = (r, test["ARR"], test["E6K_JSON"], test["E6K_NPZ"], test["E6J"])
+    before = compact(old.judge(*args, expected_plan_sha256="0" * 64))
+    after = compact(J.judge(*args, expected_plan_sha256="0" * 64))
+    assert all(v == "PASS" for v in before.values())
+    assert after[J.CATEGORIES[1]] == "FAIL" and after[J.CATEGORIES[5]] == "BLOCKED_GATE_OR_AUDIT_DOPING"
+    control = compact(J.judge(test["RAW"], *args[1:], expected_plan_sha256="0" * 64))
+    assert all(v == "PASS" for v in control.values())
+    data = ROOT / REL / "data/remote_run_36904995835/remote-run-32/outputs/e6m_out"
+    original_raw = json.loads((data / "pn_2d_consistency.json").read_text())
+    original_arrays = np.load(data / "arrays.npz")
+    args = (original_raw, original_arrays, test["E6K_JSON"], test["E6K_NPZ"], test["E6J"])
+    previous, current = compact(old.judge(*args)), J.judge(*args)
+    assert previous == compact(current), "original evidence verdicts changed"
+    stored = json.loads((ROOT / REL / "rejudge_support_result.json").read_text())
+    hashes = {}
+    for rel, digest in stored["hashes"].items():
+        data = (ROOT / rel).read_bytes()
+        assert hashlib.sha256(data).hexdigest() == digest
+        assert data == subprocess.check_output(["git", "show", BASE + ":" + rel])
+        hashes[rel] = digest
+    assert not any(n in sys.modules for n in ("devsim", "viennaps"))
+    print(json.dumps({"base_sha": BASE, "conflict_before": before, "conflict_after": after,
+                      "consistent_control": control, "original_before": previous, "original_after": compact(current),
+                      "canonical_evidence": current["canonical_evidence"], "original_hashes_unchanged": hashes,
+                      "engine_imports": 0, "real_solves": 0}, indent=2))
+
+
+if __name__ == "__main__":
+    main()

```

### docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/followup_result.json

```diff
diff --git a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/followup_result.json b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/followup_result.json
@@ -0,0 +1,80 @@
+{
+  "base_sha": "cdcb830ff07ef5e8f4938c111eaa18be546de6e7",
+  "conflict_before": {
+    "EVIDENCE_INTEGRITY": "PASS",
+    "G1_GEOMETRY_AND_IMPORT": "PASS",
+    "G2_PRODUCTION_GATE_HELD_AND_AUDIT_DOPING": "PASS",
+    "G3_UNIT": "PASS",
+    "G4_CONVERGENCE_AND_CONSERVATION": "PASS",
... 원시 JSON 전체는 패치 및 별도 파일 참조 ...
```

### docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py

```diff
diff --git a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py
index b60a8ba..d3c1df6 100644
--- a/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py
+++ b/docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts/judge_e6m.py
@@ -15 +15 @@ import judge_e6l as E6L  # noqa: E402  (strict validation of the preserved 1D ev
-VERSION = "e6m-judge-2"
+VERSION = "e6m-judge-3"
@@ -62,0 +63,12 @@ def deep_equal(a, b, path, problems):
+def require_plan(plan_path=None):
+    """Verify the independently pinned PLAN before backend preparation."""
+    path = HERE.parent / "PLAN.md" if plan_path is None else Path(plan_path)
+    try:
+        digest = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
+    except OSError as exc:
+        raise ValueError("PLAN_PREFLIGHT_BLOCKED: PLAN missing or unreadable") from exc
+    if digest != PINNED_PLAN_SHA256:
+        raise ValueError("PLAN_PREFLIGHT_BLOCKED: PLAN differs from the pre-solve pinned SHA")
+    return digest
+
+
@@ -73,2 +85,4 @@ def validate(raw, npz, e6k_json, e6k_npz, e6j=None, *, expected_plan_sha256=None
-        local_sha = hashlib.sha256((HERE.parent / "PLAN.md").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
-        need(local_sha == PINNED_PLAN_SHA256, "local PLAN differs from the pre-solve pinned PLAN")
+        try:
+            require_plan()
+        except ValueError as exc:
+            need(False, str(exc))
@@ -180,0 +195,10 @@ def judge(raw, npz, e6k_json, e6k_npz, e6j=None, *, expected_plan_sha256=None):
+        counts = ("canonical_checked", "canonical_unresolved", "canonical_mismatch")
+        try:
+            M.require_canonical(ad, int(len(npz[M.akey(lv, "fwd", "x")])))
+        except ValueError:
+            g2.append(_b(f"{lv}: legacy forward canonical audit complete and resolved", False, ad))
+        forward = L["devices"]["fwd"]
+        if "canonical_audit" in forward:
+            newer = forward["canonical_audit"]
+            g2.append(_b(f"{lv}: legacy and device forward canonical counts agree",
+                         isinstance(newer, dict) and all(newer.get(k) == ad[k] for k in counts), newer))
@@ -182 +206,3 @@ def judge(raw, npz, e6k_json, e6k_npz, e6j=None, *, expected_plan_sha256=None):
-                  gt["raised"] is True and gt["resolution"] == "UNSUPPORTED_BY_MODEL" and gt["reason_code"] == GATE_REASON and gt["doping_writes"] == 0 and gt["solves"] == 0, gt),
+                  gt["raised"] is True and gt["resolution"] == "UNSUPPORTED_BY_MODEL" and gt["reason_code"] == GATE_REASON
+                  and gt["doping_writes"] == 0 and gt["solves"] == 0
+                  and ("solve_attempts" not in gt or is_count(gt["solve_attempts"]) and gt["solve_attempts"] == 0), gt),
@@ -206 +232,7 @@ def judge(raw, npz, e6k_json, e6k_npz, e6j=None, *, expected_plan_sha256=None):
-                   _b(f"{lv}_{d}: physical parameters equal the E6K reference", all(same(dev["params"][k], rp[REF_OF[k]]) for k in PARAMS))]
+                  _b(f"{lv}_{d}: physical parameters equal the E6K reference", all(same(dev["params"][k], rp[REF_OF[k]]) for k in PARAMS))]
+            attempt_keys = ("solve_attempts", "solve_failures", "snapshot_failures")
+            if any(k in dev for k in attempt_keys):
+                g4.append(_b(f"{lv}_{d}: all attempted solves succeeded and snapshots were recorded",
+                             all(is_count(dev.get(k)) for k in attempt_keys)
+                             and dev["solve_attempts"] == dev["solves"]
+                             and dev["solve_failures"] == dev["snapshot_failures"] == 0))

```

### tests/integration/test_pn_2d_1d_consistency_real.py

```diff
diff --git a/tests/integration/test_pn_2d_1d_consistency_real.py b/tests/integration/test_pn_2d_1d_consistency_real.py
index cbedc04..8755938 100644
--- a/tests/integration/test_pn_2d_1d_consistency_real.py
+++ b/tests/integration/test_pn_2d_1d_consistency_real.py
@@ -6 +5,0 @@ usage: test_pn_2d_1d_consistency_real.py [out_dir]   (writes pn_2d_consistency.j
-import hashlib
@@ -44,0 +44 @@ class Obs:
+        self.solve_attempts, self.solve_failures, self.snapshot_failures, self.call_log = 0, 0, 0, []
@@ -52 +52,9 @@ class Obs:
-            r = o["solve"](*a, **k)
+            self.solve_attempts += 1
+            call = {"attempt": self.solve_attempts, "status": "started"}
+            self.call_log.append(call)
+            try:
+                r = o["solve"](*a, **k)
+            except Exception:
+                self.solve_failures += 1
+                call["status"] = "solve_failed"
+                raise
@@ -54 +62,8 @@ class Obs:
-            self.snaps.append(self.snapshot())
+            call["status"] = "solve_succeeded"
+            try:
+                self.snaps.append(self.snapshot())
+            except Exception:
+                self.snapshot_failures += 1
+                call["snapshot_status"] = "failed"
+                raise
+            call["snapshot_status"] = "recorded"
@@ -159 +174,2 @@ def run_level(dv, lv, x_cm, arr):
-                    rec["gate"].update({"doping_writes": len(gobs.writes), "solves": gobs.solves})
+                    rec["gate"].update({"doping_writes": len(gobs.writes), "solves": gobs.solves,
+                                        "solve_attempts": gobs.solve_attempts})
@@ -165 +181,2 @@ def run_level(dv, lv, x_cm, arr):
-                    and rec["gate"]["doping_writes"] == 0 and rec["gate"]["solves"] == 0 and rec["audit_doping"]["canonical_mismatch"] == 0):
+                    and rec["gate"]["doping_writes"] == 0 and rec["gate"]["solves"] == 0
+                    and rec["gate"].get("solve_attempts", 0) == 0 and rec["audit_doping"]["canonical_mismatch"] == 0):
@@ -203,0 +221,2 @@ def run_level(dv, lv, x_cm, arr):
+                dev.update(solve_attempts=obs.solve_attempts, solve_failures=obs.solve_failures,
+                           snapshot_failures=obs.snapshot_failures, solve_call_log=obs.call_log)
@@ -217,0 +237 @@ def run(out_dir):
+    plan_sha = J.require_plan(AUDIT / "PLAN.md")
@@ -221,2 +241 @@ def run(out_dir):
-    plan = (AUDIT / "PLAN.md").read_bytes().replace(b"\r\n", b"\n")
-    raw = {"plan_sha256": hashlib.sha256(plan).hexdigest(), "H_um": M.H_UM, "judge_version": J.VERSION, "levels": {}}
+    raw = {"plan_sha256": plan_sha, "H_um": M.H_UM, "judge_version": J.VERSION, "levels": {}}

```

### tests/unit/test_e6m_execution_contract_mock.py

```diff
diff --git a/tests/unit/test_e6m_execution_contract_mock.py b/tests/unit/test_e6m_execution_contract_mock.py
new file mode 100644
index 0000000..99957ff
--- /dev/null
+++ b/tests/unit/test_e6m_execution_contract_mock.py
@@ -0,0 +1,93 @@
+"""Exercise the actual E6M run entry and observer without backend imports."""
+import builtins
+import runpy
+import sys
+from pathlib import Path
+from types import SimpleNamespace
+from unittest.mock import Mock, patch
+
+ROOT = Path(__file__).resolve().parents[2]
+sys.path.insert(0, str(ROOT / "docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/scripts"))
+import judge_e6m as J
+
+
+class BackendReached(RuntimeError):
+    pass
+
+
+def main():
+    runner = runpy.run_path(str(ROOT / "tests/integration/test_pn_2d_1d_consistency_real.py"))
+    run, Obs = runner["run"], runner["Obs"]
+    real_import = builtins.__import__
+    plan = (J.HERE.parent / "PLAN.md").read_bytes().replace(b"\r\n", b"\n")
+    for kind in ("different", "missing", "valid_lf", "valid_crlf"):
+        events = []
+
+        def backend():
+            events.append("backend_prepare")
+            raise BackendReached("synthetic stop before any engine")
+
+        def importer(name, *args, **kwargs):
+            if name == "tcad.device.devsim":
+                events.append("backend_import")
+                return SimpleNamespace(backend=SimpleNamespace(require_devsim=backend))
+            if name.split(".")[0] in ("devsim", "viennaps"):
+                raise AssertionError("an actual engine import was attempted")
+            return real_import(name, *args, **kwargs)
+
+        opts = {"side_effect": FileNotFoundError("synthetic missing PLAN")} if kind == "missing" else {
+            "return_value": b"changed plan" if kind == "different" else plan if kind == "valid_lf" else plan.replace(b"\n", b"\r\n")}
+        mesh, level = Mock(), Mock()
+        with patch.object(Path, "read_bytes", **opts), patch("builtins.__import__", side_effect=importer), \
+                patch.dict(run.__globals__, write_mesh=mesh, run_level=level):
+            try:
+                run(None)
+            except ValueError as exc:
+                assert kind in ("missing", "different") and "PLAN_PREFLIGHT_BLOCKED" in str(exc)
+            except BackendReached:
+                assert kind in ("valid_lf", "valid_crlf")
+            else:
+                raise AssertionError("run entry escaped the engine-free trap")
+        assert events == ([] if kind in ("missing", "different") else ["backend_import", "backend_prepare"]), events
+        mesh.assert_not_called()
+        level.assert_not_called()
+        print("PLAN", kind, "backend/mesh/write/sweep/solve blocked before engine" if not events else "valid preflight reached synthetic backend")
+
+    for failure in (None, "solve", "snapshot"):
+        engine_calls = []
+
+        def fake_solve(*args, **kwargs):
+            engine_calls.append("solve")
+            if failure == "solve":
+                raise RuntimeError("synthetic solve failure")
+            return "returned"
+
+        def snapshot():
+            if failure == "snapshot":
+                raise RuntimeError("synthetic snapshot failure")
+            return {"synthetic": True}
+
+        dv = SimpleNamespace(solve=fake_solve, node_model=lambda **k: None, set_node_values=lambda **k: None)
+        obs = Obs(dv, "synthetic")
+        obs.snapshot = snapshot
+        obs.install()
+        try:
+            result = dv.solve()
+            assert failure is None and result == "returned"
+        except RuntimeError:
+            assert failure in ("solve", "snapshot")
+        finally:
+            obs.restore()
+        expected = (1, int(failure != "solve"), int(failure == "solve"), int(failure == "snapshot"))
+        actual = (obs.solve_attempts, obs.solves, obs.solve_failures, obs.snapshot_failures)
+        assert actual == expected, (failure, actual, expected)
+        assert engine_calls == ["solve"] and dv.solve is fake_solve
+        assert len(obs.call_log) == 1 and len(obs.snaps) == int(failure is None)
+        assert obs.call_log[0]["status"] == ("solve_failed" if failure == "solve" else "solve_succeeded")
+        print("OBSERVER", failure or "success", "attempts/successes/solve_failures/snapshot_failures", actual)
+    assert not any(name in sys.modules for name in ("devsim", "viennaps"))
+    print("E6M EXECUTION CONTRACT PASS; engine imports=0, real solves=0")
+
+
+if __name__ == "__main__":
+    main()

```

### tests/unit/test_e6m_judge_mock.py

```diff
diff --git a/tests/unit/test_e6m_judge_mock.py b/tests/unit/test_e6m_judge_mock.py
index 7a3d7c8..93f6fd9 100644
--- a/tests/unit/test_e6m_judge_mock.py
+++ b/tests/unit/test_e6m_judge_mock.py
@@ -104,0 +105,9 @@ def hardened_cases():
+    for field, value in (("canonical_unresolved", 1), ("canonical_mismatch", 1), ("canonical_checked", 0)):
+        case(lambda r, a, field=field, value=value: r["levels"]["L2"]["audit_doping"].__setitem__(field, value),
+             False, {gate: "FAIL", J.CATEGORIES[5]: "BLOCKED_GATE_OR_AUDIT_DOPING"}, "contradictory legacy canonical audit")
+    for field, value in (("solve_attempts", 9), ("solve_failures", 1), ("snapshot_failures", 1)):
+        def mutate_counts(r, a, field=field, value=value):
+            dev = r["levels"]["L2"]["devices"]["fwd"]
+            dev.update(solve_attempts=dev["solves"], solve_failures=0, snapshot_failures=0)
+            dev[field] = value
+        case(mutate_counts, False, {J.CATEGORIES[3]: "FAIL"}, "attempt/success evidence inconsistent")
```
