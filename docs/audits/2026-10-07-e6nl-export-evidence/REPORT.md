# E6N-L 완료: DC 단위와 CSV evidence companion

## 1. 판정과 물리적 범위

DC_UNIT_AND_EXPORT_EVIDENCE_PRESERVED.
기존 GUI DC wrapper는 BiasPoint를 새 CharacterizationResult로 포장하면서
단위 metadata를 빠뜨렸다. 이 결과의 CSV는 unit_unknown이고 GUI DC 로그는
전류 숫자만 표시했다. 실제 AST 반례에서 current_unit_metadata/source_evidence
기록 부재를 수정 전에 확인했다:
REPRODUCED: DC GUI wrapper drops unit/source metadata; engine imports 0.

공식 DEVSIM get_dimension()과 기존 current_unit_metadata()/format_current()
함수를 재사용했다. 전류 값, 부호, 방정식, gate, solver 조건은 그대로다.
2D 전류는 A/cm이며 실제 소자의 총 전류로 바꾸거나 depth를 가정하지 않는다.
source 일치는 물리 정확성 승인이 아니다. PN/MOSFET 일반 승인은 하지 않는다.

## 2. 시작 상태·계획·커밋

시작 HEAD a0eb234f05ed799a89288afdbd67888869b93666, tracked clean.
기존 untracked 항목은 보존했다. Serena 미노출로 rg/직접 읽기를 사용했다.
PLAN 단독 커밋 2e13ee2.
구현 c0ea25a18ddac4ef4f1da5aa1cd65917df54be28.
원시 CSV/JSON 보존 보완 84eb856f19db6e635d28845dfec13e7b2748138a.
로컬은 파일/AST/순수 JSON·CSV 검사만. 엔진/Tk 및 실제 DD는 원격만.

## 3. 실제 변경 파일·심볼

- tcad_2d_stagewise.py:
  run_dc_operating_point에서 장치 삭제 전에 공식 get_dimension 확인,
  생성되는 결과에 unit metadata/source evidence/검증 범위 보존.
  DC log/notify는 기존 format_current로 단위를 표시.
  _on_export_result_clicked는 기존 출처 검사를 유지하고 CSV+JSON bundle을
  저장한다. 실패하면 성공 로그를 내지 않고 불완전 pair를 경고한다.
- tcad/characterization/io.py:
  save_csv UTF-8 유지, save_json에 converged 보존 및 NaN/Inf JSON 금지.
  save_measurement_bundle은 기존 save_csv/save_json을 재사용한다.
  빈/미수렴/비유한 point 및 sweep voltage 누락을 거부하고 metadata도
  JSON preflight한다. temporary 파일에 생성한 뒤 대상 파일을 교체한다.
  새 companion 이름은 <선택한 CSV 경로>.metadata.json이다.
- tcad/characterization/source_context.py:
  source_evidence는 mesh hash/pin 정보만 저장한다. Python id나 canonical
  객체를 portable record로 위장하지 않고 GUI_SESSION_ONLY로 명시한다.
- 신규 unit 및 감사 스크립트/profile/request. 기존 테스트 assertion을
  완화하지 않았다. 엔진 내부/물리 모델/공정 state 전이는 무변경이다.

## 4. 저장 계약과 한계

CSV 수치/열 구조를 유지한다. JSON은 전체 접점 voltages/currents/converged,
unit/current normalization, source/검증 범위, CSV SHA-256을 보존한다.
Gate 전압을 보존하되 계산하지 않은 gate current를 0으로 발명하지 않는다.
전류 unit이 확립되지 않은 일반 결과는 기존대로 unit_unknown이며 A로 추정하지 않는다.

두 최종 os.replace 호출은 두 파일 filesystem transaction이 아니다.
두 번째 교체에서 I/O 문제가 생기면 pair가 불완전할 수 있으며 GUI가 경고한다.
소비자는 companion csv_sha256을 확인해야 한다. hash는 pair의 일치 검사이지
전자서명·물리 정확성 인증이 아니다. canonical state 전체를 export하지
않으므로 이 pair만으로 동일 도핑 상태를 재구성할 수는 없다.

## 5. 실행 기록

첫 원격 run 37565268757 / source c0ea25a / artifact remote-run-59:
5개 검사 통과. 다음 실행에서는 원시 CSV/JSON을 artifact에 남기도록
감사 스크립트만 보완했다. 두 실행은 순차 수행했고 중복 실행하지 않았다.

최종 https://github.com/tjrgns1753-create/tcad/actions/runs/37565421867
source 84eb856f19db6e635d28845dfec13e7b2748138a / artifact remote-run-60.
job 1분 3초, supervised 검사 합계 약 10.55초.

| 단계 | rc | duration(s) |
| --- | --- | --- |
| export | 0 | 3.015 |
| bundle | 0 | 0.500 |
| units | 0 | 4.516 |
| entry_gate | 0 | 1.000 |
| existing_gui | 0 | 1.515 |

모두 COMPLETED 및 cleanup_ok=true.
로컬 existing units test는 matplotlib 미설치로 중단됐다. 로컬 통과라고
보고하지 않고 pinned matplotlib가 설치된 원격 통과로 확인했다.
새 pure bundle 반례 및 기존 source-context pure 테스트는 로컬 통과했다.
io.py의 혼합 줄바꿈을 실제 LF로 정규화한 후 clean diff check도 통과했다.

## 6. 증거 범위 구분

export의 ±1e-6 DC 값과 mesh_sha256 token은 FakeDevsim/Recorder 및 stable
테스트 코드 파일을 사용한 mock이다. GUI export 배선의 증거이지 실제
MOSFET 계산이 아니다. RAW_SCOPE.md에 이를 명시했다.
실제 원시 CSV 및 companion을 raw/outputs/e6nl_out에 보존했다.
GUI mock DC는 device dimension 2 반환, 단위 A/cm 보존, 전체 gate voltage,
converged, source token 및 CSV hash 일치를 검사했다.

실제 uniform DD 대조군은 별도의 gui_unit_contract.json이다.
전류 ±0.0001600000000002224 A/cm는 기존 원시 reference와 동일하며
기존 I=sigma(H/L)V 해석식·단위·부호 검사도 그대로 통과했다.
CHEMICAL/UNKNOWN은 기존처럼 0 doping write/0 solve/숫자 출력 0.
기존 DC/CLI canonical gate mock의 정상/차단 대조군도 통과했다.
새 실제 MOSFET solve나 일반 PN 승인은 없다.

## 7. 독립 검증과 파일 무결성

verify_artifact.py는 고정 SHA/run ID와 8개 source input의 git blob 및
checkout hash, 11개 원시 output/log의 bytes 길이/SHA-256을 확인한다.
CSV/JSON companion 자체도 재파싱하여 current unit, 전체 bias, converged,
source token, CSV hash, 수치/부호를 직접 비교한다.
결과 pass=true, source_inputs=8, raw_files=11, steps=5, engine_imports=0.
source LF/CRLF 차이는 명시적 후보만 비교하고 원시 output은 변형하지 않았다.

raw/raw_first/CHANGE.patch는 -text -diff로 보존했다.
민감 이름/개인 경로/토큰 패턴 검색 0건.
git diff --check/staged diff --check 통과.
기존 원본 증거 및 물리 gate는 변경하지 않았다.
전체 회귀, main 병합 없음.

## 8. 다음 후보

GUI의 current-wafer Potential/Electrons/Holes 보기에는 실제 node field
자료가 없다는 안내가 있다. 다음 구현 후보는 공식 API로 현재 계산에서
얻은 node field를 결과에 보존하는 경로다. 지원되는 실제 계산에 한정하고
기존 PN/산화 gate를 우회하거나 고정 reference를 현재 웨이퍼처럼 보이지 않는다.
이번 stage는 이 기능을 구현하거나 승인하지 않았다.

## 9. 전체 production semantic diff

CHANGE.patch 원문 보존. 본문 빈 context 줄의 공백만 문서 검사용으로 제거했다.

```diff
diff --git a/tcad/characterization/io.py b/tcad/characterization/io.py
index f166509..fe6e449 100644
--- a/tcad/characterization/io.py
+++ b/tcad/characterization/io.py
@@ -25,7 +25,7 @@ def save_csv(result: CharacterizationResult, path: str) -> str:
         {c for point in result.points for c in point.currents}
     )

-    with open(path, "w", newline="") as f:
+    with open(path, "w", newline="", encoding="utf-8") as f:
         writer = csv.writer(f)
         # A result that carries an established unit (2D DevSim: "A/cm") names it in the header; a result without one is labelled
         # unit_unknown -- never assumed to be A.
@@ -51,14 +51,52 @@ def save_json(result: CharacterizationResult, path: str) -> str:
         "sweep_contact": result.sweep_contact,
         "metadata": result.metadata,
         "points": [
-            {"voltages": p.voltages, "currents": p.currents}
+            {"voltages": p.voltages, "currents": p.currents, "converged": p.converged}
             for p in result.points
         ],
     }
-    Path(path).write_text(json.dumps(payload, indent=2))
+    Path(path).write_text(json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8")
     return str(path)


+def save_measurement_bundle(result: CharacterizationResult, path: str) -> str:
+    """CSV plus full result JSON and CSV hash. No new physics or unit inference.
+
+    Invalid evidence is rejected before replacing either existing file. The
+    two final os.replace calls are NOT a two-file transaction; consumers must
+    check the companion's csv_sha256 before treating the pair as evidence.
+    """
+    from dataclasses import replace
+    import hashlib
+    import os
+    import tempfile
+    from tcad.characterization.interface import validate_bias_point
+    if not result.points:
+        raise ValueError("Cannot export an empty measurement.")
+    for point in result.points:
+        validate_bias_point(point)
+        if result.sweep_contact not in point.voltages:
+            raise ValueError("Measurement is missing its sweep voltage.")
+    json.dumps(result.metadata, allow_nan=False)
+    target = Path(path)
+    companion = Path(str(target) + ".metadata.json")
+    staged = []
+    try:
+        for _ in range(2):
+            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".measurement_", suffix=".tmp", delete=False) as f:
+                staged.append(Path(f.name))
+        save_csv(result, str(staged[0]))
+        digest = hashlib.sha256(staged[0].read_bytes()).hexdigest()
+        metadata = {**result.metadata, "export_evidence": {"schema": 1, "csv_sha256": digest}}
+        save_json(replace(result, metadata=metadata), str(staged[1]))
+        os.replace(staged[0], target)
+        os.replace(staged[1], companion)
+    finally:
+        for temporary in staged:
+            temporary.unlink(missing_ok=True)
+    return str(companion)
+
+
 def save_cv_csv(result: CharacterizationResult, path: str) -> str:
     """Write a C-V sweep's metadata (capacitance_F / capacitance_voltages_V,
     see tcad.characterization.cv_sweep.run_mos_cv_sweep) to CSV.
diff --git a/tcad/characterization/source_context.py b/tcad/characterization/source_context.py
index ba9bf4e..5389550 100644
--- a/tcad/characterization/source_context.py
+++ b/tcad/characterization/source_context.py
@@ -34,3 +34,11 @@ def source_context_matches(context, mesh_path, state, pins):
     return (current is not None and
             context.state is current.state and context.mesh_sha256==current.mesh_sha256 and
             context.pins==current.pins)
+
+def source_evidence(context):
+    """Portable subset only. Never serialize a Python id as canonical proof."""
+    if not isinstance(context, SourceContext):
+        raise ValueError("Source context is missing.")
+    return {"mesh_sha256": context.mesh_sha256, "canonical_record": "GUI_SESSION_ONLY",
+            "pins": [{"name": p[0], "role": p[1], "x_um": p[2], "y_um": p[3], "target_region": p[4]}
+                     for p in context.pins]}
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index e164378..f9df5dd 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -6113,12 +6113,18 @@ class TCADApplication(tk.Tk):
                                "No CSV was exported; compute a new result on the current device.")
             return
         from tkinter import filedialog
-        from tcad.characterization.io import save_csv
+        from tcad.characterization.io import save_measurement_bundle
         path = filedialog.asksaveasfilename(defaultextension=".csv")
         if not path:
             return
-        save_csv(self.last_electrode_result, path)
-        self._log(f"\nResult exported to {path}\n")
+        try:
+            companion = save_measurement_bundle(self.last_electrode_result, path)
+        except Exception as exc:
+            self._notify_error("Export", f"Measurement evidence export failed: {exc}. "
+                               "Do not treat an incomplete CSV/JSON pair as verified evidence.")
+            return
+        self._log(f"\nResult exported to {path}; evidence companion: {companion}. "
+                  "Source match is not a general physical-accuracy approval.\n")

     def add_electrode_pin(self, name, role, x_um, y_um, target_region=None):
         """Programmatic pin add (used by the GUI's own ADD PIN button
@@ -6422,6 +6428,7 @@ class TCADApplication(tk.Tk):
                                 ((body_contact,) if body_contact else ()))
             if not source_context_matches(source_context, self.last_final_mesh, self.wafer_state, self.electrode_pins):
                 raise ValueError("Wafer source changed during DC solve; no current result is retained.")
+            dimension = module.get_dimension(device=imported.device)
         except UnsupportedDopingState as exc:
             # Tier 1-1: blocked by the central canonical-state gate
             # before any doping write or solve -- not a solve failure.
@@ -6444,27 +6451,33 @@ class TCADApplication(tk.Tk):
             self.last_electrode_import = None
             self._electrode_import_context = None

-        from tcad.characterization.interface import CharacterizationResult
+        from tcad.characterization.interface import CharacterizationResult, current_unit_metadata, format_current
+        from tcad.characterization.source_context import source_evidence
         self.last_electrode_result = CharacterizationResult(
             name="dc_operating_point", device=imported.device, region="Si",
             sweep_contact=drain_contact, points=[op_point],
             metadata={
                 "drain_voltage": drain_voltage, "gate_voltage": gate_voltage,
                 "body_voltage": body_voltage,
+                **current_unit_metadata(dimension),
+                "source_evidence": source_evidence(source_context),
+                "verification_scope": "INPUT_SOURCE_MATCH_ONLY_NOT_GENERAL_PHYSICS_APPROVAL",
             },
         )
         self._electrode_result_context = source_context
+        displayed_currents = {name: format_current(value, self.last_electrode_result.metadata)
+                              for name, value in op_point.currents.items()}

         self._log(
             f"\n================================\n"
             f"DC OPERATING POINT\n"
             f"================================\n"
             f"Vd={drain_voltage:+.4f}V Vg={gate_voltage:+.4f}V Vb={body_voltage:+.4f}V\n"
-            f"currents={op_point.currents}\n"
+            f"currents={displayed_currents}\n"
         )
         self._notify_info(
             "Electrode",
-            f"DC operating point solved.\n\ncurrents={op_point.currents}",
+            f"DC operating point solved.\n\ncurrents={displayed_currents}",
         )
         return op_point
```
