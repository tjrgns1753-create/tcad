# E6N-K 완료: 접점 장치·DC CSV의 출처 일치 검사

## 1. 판정 및 물리적 의미

ELECTRODE_SOURCE_CONTEXT_CHECKED.
해석한 geometry/contact와 이후 적용되는 canonical doping이 서로 다른
웨이퍼에 속하거나, 이전 전류가 현재 웨이퍼의 결과로 내보내지지 않도록 했다.
물리 방정식·모델·엔진·허용오차·기존 gate는 변경하지 않았다.
검사 통과는 source 일치를 뜻하며 일반 PN/MOSFET 정확성 승인이 아니다.
공정 실행 순서를 강제하지 않는다. 변경 뒤 접점을 다시 해석해야 한다는
안내는 장치 입력 일치 조건이며 웨이퍼의 물리적 certainty를 잃었다고
선언하는 정책이 아니다. 기존 canonical 상태는 변경하지 않는다.

## 2. 시작 상태·수정 전 반례

시작 HEAD 7e24248c748be1df2f1ab1a4b9128569d4964a6e,
브랜치 claude/remote-runner, tracked clean. 기존 untracked 항목은 건드리지 않았다.
Serena가 도구에 노출되지 않아 rg/직접 읽기를 사용했다.

run_dc_operating_point는 last_electrode_import가 어느 mesh/state/pin에서
생겼는지 검사하지 않았다. CSV exporter도 저장된 result의 source를
확인하지 않았다. 실제 exporter 메서드를 AST 추출해 result만 있고 source
기록이 없는 반례에서 파일선택 대화상자 도달을 수정 전에 재현했다:
REPRODUCED: exporter opens dialog with no source evidence; imports 0.
이번에 실제 오래된 MOSFET에서 틀린 전류가 계산됐다고 주장하지는 않는다.

PLAN 단독 커밋 eab5397. 구현 첫 커밋 93867aebdbe21fec8713264c6f603c96facd01e2.
최종 검증 소스 fc296edbb8e62cf3544b882b0a876cea5d4a1a53.

## 3. 구현 내용·변경 심볼

- tcad/characterization/source_context.py:
  SourceContext, capture_source_context, source_context_matches.
  파일 내용 SHA-256(1MB streaming block), canonical 객체 reference,
  pin의 name/role/x/y/target_region을 기록한다.
  state reference를 보유해 Python id 재사용 문제를 피한다.
  source 기록이 없으면 파일 hash 작업 전에 즉시 불일치로 반환한다.
- tcad_2d_stagewise.py:
  초기화/cleanup/reset/DC 재시도에서 context 수명 정리.
  resolve_electrode_pins 시작에서 과거 device/result 정리, import 전 source
  캡처 및 import 뒤 재확인. DC의 doping write/solve 전에 source 비교,
  solve 결과 보존 전에도 source 비교. export는 source 검사 뒤에만 CSV
  대화상자를 연다.
- tests/unit/test_electrode_source_context_mock.py:
  실제 GUI 메서드 추출, source 누락·mesh 덮어쓰기·상태 객체 교체·pin 좌표/
  역할 변경·동일 source의 순수 반례. 엔진/Tk import 금지.
- tests/unit/test_measurement_entry_point_gate_mock.py:
  기존 FakeDevsim fixture에 stable-file source token을 설정했다.
  실제 mesh/장치 증거가 아닌 mock token임을 주석으로 명시.
  기존 canonical 차단·정상 대조군 assertion은 유지했다.
- 감사 스크립트 및 원격 profile/request. 기존 엔진 API 그대로 사용한다.
  새 source helper는 물리 remesher/solver가 아니라 GUI provenance adapter다.

## 4. 실행 실패와 정정 기록

첫 run 37486331211 / source 93867ae / artifact remote-run-57:
context 검사는 pin placement에서 실패, 나머지 4개는 통과.
fixture는 y=-0.25의 boundary node에 pin을 뒀지만, 기존 point-contact
API는 radius 0.1um 이내 경계 변 MIDPOINT를 선택한다. 해당 coarse edge
중점과는 0.125um 떨어져 contact를 만들 수 없었다.
production 규칙/반경을 완화하지 않고 실제 중점 y=-0.375에 fixture를
배치했다. 이 좌표 정정은 측정 결과를 맞추는 변경이 아니라 기존 API의
고정 geometry 계약을 맞춘 것이다. raw_failure에 실패 기록을 보존했다.

최종 소스는 reset/잘못된 DC 재시도 때 보유한 canonical reference를
해제하도록 보완했다. 동일 source 검사가 빠진 source를 비싼 파일 읽기 없이
거부하는 최적화도 포함한다.

## 5. 최종 원격 실측

https://github.com/tjrgns1753-create/tcad/actions/runs/37486908105
source fc296edbb8e62cf3544b882b0a876cea5d4a1a53 / remote-run-58.
실제 Tk/ViennaPS·DEVSIM import 및 uniform DD 계산은 원격 Windows만.
로컬은 pure Python/AST와 원시 결과 검증만 수행했다.

| 단계 | rc | duration(s) |
| --- | --- | --- |
| context | 0 | 3.015 |
| source | 0 | 0.500 |
| validity | 0 | 0.500 |
| entry_gate | 0 | 1.016 |
| existing_gui | 0 | 1.500 |

5개 모두 COMPLETED 및 cleanup_ok=true, 검사 합계 약 6.53초.

실제 contact import 뒤 state/pin/mesh_bytes/missing_context 4개 반례:
각각 solves=0, doping_writes=0, devices_remaining=0.
state 반례는 동일 수치 레시피에서 새 canonical object를 만든 경우다.
mesh_bytes 반례는 geometry가 바뀌지 않는 EOF newline 변경이다.
따라서 이 검사는 geometry 동등성 판정이 아니라 정확한 입력 source
일치 검사이며 이런 보수적 재해석 요구도 의도적으로 포함한다.

동일 source CSV control은 합성 BiasPoint이며 실제 MOSFET solve가 아니다.
동일 source는 CSV 2줄 생성, state 교체 뒤에는 파일 대화상자 호출 없이 차단.
reset에서 import/result context가 모두 제거되는 것도 확인했다.

기존 실제 uniform DD 정상 control은 기존 전류 ±0.0001600000000002224 A/cm,
부호·unit·원시 reference 및 I=sigma(H/L)V 해석식 검사 그대로 통과했다.
CHEMICAL/UNKNOWN의 기존 0 write/0 solve 차단도 유지했다.
DC/CLI 기존 canonical gate mock의 supported/unsupported 대조군도 통과.
이 대조군을 실제 MOSFET 물리 승인으로 확대하지 않는다.

## 6. 독립 검증·무결성

verify_artifact.py:
고정 source SHA/run ID, 7개 git blob/checkout source hash,
9개 원시 output/log의 bytes 길이와 SHA-256,
5개 exit/cleanup, 4개 실제 import 반례 및 정상 control 재대조.
pass=true, source_inputs=7, raw_files=9, steps=5, engine_imports=0.

Source checkout의 LF/CRLF는 명시적 후보만 비교한다. 출력은 normalization
없이 그대로 비교했다. raw/raw_failure/CHANGE.patch는 -text -diff로 보존.
민감 이름/개인 경로/토큰 검색 0건.
git diff --check 및 staged diff --check 통과.
전체 회귀, main 병합, gate 해제 및 다른 원본 증거 수정 없음.

## 7. 한계와 다음 단계

immutable canonical state 전이를 전제로 한다. 동일 객체의 내부를 강제로
변조하는 unsupported 행위나 외부 파일 변경 후 다시 원래 bytes로 되돌리는
이력은 감지하지 않는다. state가 같은 수치를 갖더라도 새 객체이면 보수적으로
새 resolve를 요구한다. 과거 device를 매 공정 순간 즉시 없애는 구조가 아니라
사용/재해석/reset 경계에서 검증·정리한다.

CSV에 독립적으로 검증 가능한 source metadata를 함께 기록하는 것은
이번 범위 밖이다. 현재 검사 대상은 GUI 내 source 귀속이다.
다음 후보는 export된 결과 자체에 source/units/검증 범위가 충분히 남는지다.
GUI의 과거 log는 역사 기록으로 유지한다.
실제 결과의 물리 타당성은 별도 보존·수렴·기준해 검사가 계속 필요하다.

## 8. 실제 semantic diff

production 2개와 기존 fixture 보완의 전체 diff다.
정확한 patch는 CHANGE.patch에 보존한다. 본문 빈 context 줄의 공백만
문서 whitespace 검사 목적상 제거했다.

```diff
diff --git a/tcad/characterization/source_context.py b/tcad/characterization/source_context.py
new file mode 100644
index 0000000..ba9bf4e
--- /dev/null
+++ b/tcad/characterization/source_context.py
@@ -0,0 +1,36 @@
+"""GUI device/result provenance only; no engine import or physical inference."""
+from dataclasses import dataclass
+import hashlib
+from pathlib import Path
+
+@dataclass(frozen=True, eq=False)
+class SourceContext:
+    mesh_sha256: str
+    state: object
+    pins: tuple
+
+def capture_source_context(mesh_path, state, pins):
+    """Keep the immutable canonical object and exact input mesh/pin signature.
+
+    Holding the state reference prevents id reuse. Unreadable/missing evidence
+    is not an identity transition and returns None. No mesh coordinates move.
+    """
+    if mesh_path is None:
+        return None
+    try:
+        digest=hashlib.sha256()
+        with Path(mesh_path).open('rb') as stream:
+            for block in iter(lambda:stream.read(1024*1024), b''):
+                digest.update(block)
+        signature=tuple((p.name,p.role,p.x_um,p.y_um,p.target_region) for p in pins)
+    except (OSError, TypeError, AttributeError, ValueError):
+        return None
+    return SourceContext(digest.hexdigest(), state, signature)
+
+def source_context_matches(context, mesh_path, state, pins):
+    if not isinstance(context,SourceContext):
+        return False
+    current=capture_source_context(mesh_path,state,pins)
+    return (current is not None and
+            context.state is current.state and context.mesh_sha256==current.mesh_sha256 and
+            context.pins==current.pins)
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index 71bb35d..e164378 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -868,6 +868,8 @@ class TCADApplication(tk.Tk):
         self.last_electrode_import = None
         self._electrode_contact_regions = {}
         self.last_electrode_result = None
+        self._electrode_import_context = None
+        self._electrode_result_context = None

         # Each category panel's LabelFrame, registered as it is built,
         # so the category selector can show exactly one at a time (see
@@ -6102,6 +6104,14 @@ class TCADApplication(tk.Tk):
         if getattr(self, "last_electrode_result", None) is None:
             self._notify_info("Export", "No result to export yet.")
             return
+        from tcad.characterization.source_context import source_context_matches
+        if not source_context_matches(getattr(self, "_electrode_result_context", None),
+                                      self.last_final_mesh, self.wafer_state, self.electrode_pins):
+            self.last_electrode_result = None
+            self._electrode_result_context = None
+            self._notify_error("Export", "Current wafer/doping/pins do not match the DC result source. "
+                               "No CSV was exported; compute a new result on the current device.")
+            return
         from tkinter import filedialog
         from tcad.characterization.io import save_csv
         path = filedialog.asksaveasfilename(defaultextension=".csv")
@@ -6140,6 +6150,7 @@ class TCADApplication(tk.Tk):
         so a leaked device from an abandoned RESOLVE (no DC-OP click
         ever reached) cannot poison a later, unrelated solve -- see
         CLAUDE.md's own "leaked DevSim device" trap."""
+        self._electrode_import_context = None
         if self.last_electrode_import is None:
             return
         from tcad.device.devsim import backend as devsim_backend
@@ -6168,6 +6179,11 @@ class TCADApplication(tk.Tk):
         mesh's own min-x instead -- the same single conversion every
         other caller uses.
         """
+        self.last_electrode_result = None
+        self._electrode_result_context = None
+        self._cleanup_electrode_device()
+        from tcad.characterization.source_context import capture_source_context, source_context_matches
+        source_context = capture_source_context(self.last_final_mesh, self.wafer_state, self.electrode_pins)
         if not self.electrode_pins:
             self._log("\nRESOLVE PINS: no pins placed yet -- nothing to resolve.\n")
             return None
@@ -6178,7 +6194,9 @@ class TCADApplication(tk.Tk):
         # A previous RESOLVE click's device (if the user never reached
         # DC OPERATING POINT, or clicked RESOLVE again) would otherwise
         # stay registered in DevSim and poison the next solve.
-        self._cleanup_electrode_device()
+        if source_context is None:
+            self._notify_error("Electrode", "Current mesh source cannot be read; pins were not resolved.")
+            return None

         from tcad.mesh.viennaps_adapter import build_process_result
         from tcad.device.devsim.contact_probe import (
@@ -6226,6 +6244,11 @@ class TCADApplication(tk.Tk):
             return None

         self.last_electrode_import = imported
+        if not source_context_matches(source_context, self.last_final_mesh, self.wafer_state, self.electrode_pins):
+            self._cleanup_electrode_device()
+            self._notify_error("Electrode", "Wafer source changed during pin resolution; no device was kept.")
+            return None
+        self._electrode_import_context = source_context
         # Which real MaterialRegion each contact actually landed on --
         # read by run_dc_operating_point() to tell a contact that is
         # genuinely on Si/SiO2 apart from one that resolved onto a
@@ -6246,6 +6269,7 @@ class TCADApplication(tk.Tk):
         contact after its Pin's own `name` field)."""
         # A failed new attempt must not leave the previous CSV result available.
         self.last_electrode_result = None
+        self._electrode_result_context = None
         import math
         try:
             if any(not math.isfinite(float(v)) for v in (drain_voltage, gate_voltage, body_voltage)):
@@ -6257,6 +6281,14 @@ class TCADApplication(tk.Tk):
             self._log("\nDC OPERATING POINT: pins not resolved yet -- nothing to solve.\n")
             return None

+        from tcad.characterization.source_context import source_context_matches
+        source_context = getattr(self, "_electrode_import_context", None)
+        if not source_context_matches(source_context, self.last_final_mesh, self.wafer_state, self.electrode_pins):
+            self._cleanup_electrode_device()
+            self._notify_error("Electrode", "Resolved device source no longer matches current wafer/doping/pins. "
+                               "No doping write or solve was run; resolve pins again on the current wafer.")
+            return None
+
         imported = self.last_electrode_import
         # import_process_result() SKIPS an interface_region_pairs entry
         # whose two regions are missing or share no mesh edges (e.g. a
@@ -6388,6 +6420,8 @@ class TCADApplication(tk.Tk):
             # The ideal oxide gate has voltage evidence, not DD current evidence.
             validate_bias_point(op_point, (source_contact, drain_contact) +
                                 ((body_contact,) if body_contact else ()))
+            if not source_context_matches(source_context, self.last_final_mesh, self.wafer_state, self.electrode_pins):
+                raise ValueError("Wafer source changed during DC solve; no current result is retained.")
         except UnsupportedDopingState as exc:
             # Tier 1-1: blocked by the central canonical-state gate
             # before any doping write or solve -- not a solve failure.
@@ -6408,6 +6442,7 @@ class TCADApplication(tk.Tk):
             except Exception:
                 pass
             self.last_electrode_import = None
+            self._electrode_import_context = None

         from tcad.characterization.interface import CharacterizationResult
         self.last_electrode_result = CharacterizationResult(
@@ -6418,6 +6453,7 @@ class TCADApplication(tk.Tk):
                 "body_voltage": body_voltage,
             },
         )
+        self._electrode_result_context = source_context

         self._log(
             f"\n================================\n"
@@ -6434,6 +6470,7 @@ class TCADApplication(tk.Tk):

     def _on_dc_operating_point_clicked(self):
         self.last_electrode_result = None
+        self._electrode_result_context = None
         try:
             vd = float(self.dc_drain_v_var.get())
             vg = float(self.dc_gate_v_var.get())
@@ -8985,6 +9022,7 @@ class TCADApplication(tk.Tk):
         self.electrode_pins = []
         self._electrode_contact_regions = {}
         self.last_electrode_result = None
+        self._electrode_result_context = None
         if hasattr(self, "electrode_listbox"):
             self.electrode_listbox.delete(0, "end")

diff --git a/tests/unit/test_measurement_entry_point_gate_mock.py b/tests/unit/test_measurement_entry_point_gate_mock.py
index c421636..8ecbe6d 100644
--- a/tests/unit/test_measurement_entry_point_gate_mock.py
+++ b/tests/unit/test_measurement_entry_point_gate_mock.py
@@ -154,6 +154,11 @@ def _dc_operating_point(app, state, nodes):
     app.last_electrode_import = SimpleNamespace(
         device="dc_dev", mesh="dc_mesh", contacts=["Source", "Drain", "Gate"],
         interfaces=["Si_SiO2_interface"])
+    # This whole fixture uses FakeDevsim, not an actual mesh. A stable file is
+    # only its source-context token; no physical geometry claim is made here.
+    from tcad.characterization.source_context import capture_source_context
+    app.last_final_mesh = __file__
+    app._electrode_import_context = capture_source_context(__file__, state, app.electrode_pins)
     log_before = app.log.get("1.0", "end-1c")
     restores = [_patched(dcop, "solve_mosfet_dc_operating_point", recorder),
                 _patched(backend, "require_devsim", lambda: fake)]
```
