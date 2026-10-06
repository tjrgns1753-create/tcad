# E6N-J 완료: 측정 입력·출력 유효성 및 DC 실패 재시도

## 1. 판정과 물리적 범위

MEASUREMENT_EVIDENCE_BOUNDARY_CHECKED.
NaN/Inf 및 미수렴 결과를 유효한 전류로 표시하지 않는 경계 수정이다.
수치가 유한하거나 solver가 반환했다는 사실만으로 물리적으로 옳다고
판정하지 않는다. PN·MOSFET·산화 지원 또는 gate 해제의 근거가 아니다.

물리 코드와 구성방정식은 변경하지 않았다. 기존 uniform DD 대조군의
전류는 동일한 기하/재료/도핑/바이어스에서 기존 원시값 및 기존
I = sigma (H/L) V 해석식 검사와 비교했다. 이 한 대조군의 통과를
임의 공정 순서나 일반 접합 검증으로 확대하지 않는다.

## 2. 수정 전 실측과 원인

시작 HEAD 41f6831d6264ebc059c9ce7cc72eea1dd65e95fe, tracked clean.
Serena 도구가 노출되지 않아 rg/직접 읽기로 조사했다.
순수 AST 추출한 실제 run_dc_operating_point에 이전 결과를 넣고
last_electrode_import=None으로 재시도하면 반환값은 None인데 이전
last_electrode_result는 유지되는 반례를 수정 전 재현했다.
출력: REPRODUCED: failed DC retry keeps previous export result; engine imports 0.

전압 입력은 float만 검사해 NaN/Inf가 통과했고, 결과는 finite/converged
검사 없이 성공 텍스트로 포맷되었다. 실제 엔진이 이번에 NaN을
반환했다는 주장은 하지 않는다. 반환값 손상 실험은 의도적 오류 주입이다.

## 3. 변경 파일·역할

- tcad/characterization/interface.py: validate_bias_point. 유한값, 수렴,
  빈 evidence, 필수 전류/전압 접점 검증. 음수 전류 및 0은 허용.
- tcad_2d_stagewise.py: run_measurement의 전압 검사 위치를 엔진 준비 전으로
  이동. 단일 결과 및 필수 접점 검사 후에만 출력. DC 시작 및 GUI 숫자
  파싱 시작에서 이전 export 결과 제거. DC 결과 검사.
- tests/unit/test_measurement_validity_mock.py: 엔진 없는 실제 메서드 추출,
  실패 재시도·invalid voltage·invalid point·정상 부호·gate 전류 미발명 검사.
- tests/unit/test_measurement_entry_point_gate_mock.py: 기존 전류만 있던
  SimpleNamespace fixture를 실제 BiasPoint 형식으로 보완. assertion 완화 없음.
- 감사 스크립트, profile/request 및 PLAN. 엔진 내부/방정식/gate 수정 없음.

DC는 이상적 oxide gate의 전압은 기록하되 DD gate current는 원래
생산자가 계산하지 않는다. 따라서 없는 gate current를 0으로 발명하거나
그 누락으로 정상 DC 결과를 거부하지 않는다. 요구하는 DD 전류 접점은
Source/Drain 및 지정된 Body다.

## 4. 사전 계획 및 실행 이력

PLAN 단독 고정 e4991a5, 첫 구현 422b3aeb92ae505e17fd67b779a06caa3ad3d547.
첫 원격 run 37465268440 / raw_first, 검사 4개 모두 통과.
이어 기존 DC 정상 mock의 실제 형식 보완과 실제 DD 반환 후 오류 주입을
추가했다. 이 보완 이유를 PLAN에 추가 기록했다.
최종 소스 2bab11c33d0df69a5e094a9ce973e62bcbe09dfa.
최종 run https://github.com/tjrgns1753-create/tcad/actions/runs/37465658115
artifact remote-run-56 / raw. 두 실행은 순차 실행이며 중복 계산 없음.
원격 전체 job 1분 9초, supervised 검사 합계 약 7.55초.
실제 엔진 import/solve/Tk는 GitHub-hosted Windows에서만 실행했다.
로컬은 AST/순수 검사/원시 hash 검증만 수행했다.

## 5. 실제 결과

| 최종 단계 | rc | 시간(s) |
| --- | --- | --- |
| gui | 0 | 3.516 |
| boundary | 0 | 0.500 |
| canonical_gate | 0 | 1.015 |
| entry_gate | 0 | 1.000 |
| existing_gui | 0 | 1.516 |

모든 단계 COMPLETED, cleanup_ok=true.

실제 Tk에서 nan/inf/-inf/bad 전압: backend 준비 시도 0.
이전 DC 결과 제거, 실패 재시도 이후 CSV 파일선택 호출 0.

실제 uniform DD 계산 후 의도적으로 반환값을 손상시킨 두 경우:
nan_current / not_converged 각각 solve 시도 3회 후 GUI 정상 측정 블록 0,
남은 device 0. 이것은 출력 경계 검증이며 solve 미실행 실험이 아니다.

정상 대조군:
I_source = +0.0001600000000002224 A/cm,
I_ground = -0.0001600000000002224 A/cm.
기존 원시값 동일, 기존 해석식 허용오차 및 단위/부호 검사 그대로 통과.
CHEMICAL/UNKNOWN은 기존대로 도핑 쓰기 0, solve 0, 숫자 출력 0.
GUI DC 및 CLI의 기존 canonical unsupported gate 대조군도 통과했다.
실제 MOSFET DC solve 검증을 새로 수행하지는 않았다.

## 6. 독립 검증·무결성

verify_artifact.py를 로컬 엔진 금지 audit hook과 함께 실행:
pass=true, source_inputs=7, raw_files=9, steps=5, engine_imports=0.
고정 소스 SHA 및 run ID, 7개 source input의 git blob/checkout 줄바꿈
계약, 9개 원시 출력/로그의 길이와 SHA-256을 대조했다.
source checkout의 LF/CRLF 차이는 명시적 변환 후보로만 대조했고
원시 출력은 정규화하지 않고 bytes 그대로 대조했다.
raw 및 raw_first는 .gitattributes -text -diff로 보존했다.
민감 경로/이름/토큰 패턴 검색 0건. 일반/clean git diff --check 통과.
처음 interface.py 혼합 줄바꿈으로 clean 검사 실패한 것을 실제 LF로
정규화한 후 통과했다. semantic diff에는 검사 함수 추가만 남았다.

## 7. 남은 한계·다음 후보

이번은 실패한 DC 재시도 직후 export 결과의 수명만 고쳤다.
웨이퍼 변경 뒤 과거 DC 결과의 상태 귀속/새 pin 해석 결과의 stale 여부는
별도 조사 대상이다. GUI의 이전 로그는 역사 기록이며 삭제하지 않았다.
잘못된 수치 evidence는 거부하지만 전류 보존/공간 수렴/물리 모델의
적합성을 일반 승인하지 않는다. 기존 PN·산화 gate는 유지한다.
전체 회귀, main 병합, 엔진 내부 수정, 물리 모델 추가 없음.

## 8. 실제 semantic diff

production 2개와 기존 DC fixture 수정의 전체 unified diff다.
정확한 patch는 CHANGE.patch에 보존하고, 본문 빈 context 줄의 공백은
문서 whitespace 검사 목적상 제거했다.

```diff
diff --git a/tcad/characterization/interface.py b/tcad/characterization/interface.py
index 268131c..e87a42b 100644
--- a/tcad/characterization/interface.py
+++ b/tcad/characterization/interface.py
@@ -103,6 +103,23 @@ class BiasPoint:
     converged: bool = True


+def validate_bias_point(point: BiasPoint, required_contacts=()) -> None:
+    """Reject invalid terminal evidence, without replacing values or approving physics.
+
+    This is a GUI result-boundary check, not a convergence/charge-conservation
+    proof. Negative finite currents and zero are both legitimate values.
+    """
+    import math
+    if point.converged is not True or not point.currents or not point.voltages:
+        raise ValueError("Measurement result is empty or not converged; no current is reported.")
+    for contact in required_contacts:
+        if contact not in point.currents or contact not in point.voltages:
+            raise ValueError(f"Measurement result is missing contact {contact!r}.")
+    for values in (point.voltages, point.currents):
+        if any(not math.isfinite(float(value)) for value in values.values()):
+            raise ValueError("Measurement result contains a non-finite value; no current is reported.")
+
+
 @dataclass
 class CharacterizationResult:
     """A generic terminal-characteristics sweep result.
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index d1d4773..71bb35d 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -5767,6 +5767,14 @@ class TCADApplication(tk.Tk):
             return None

     def run_measurement(self):
+        import math
+        try:
+            voltage = float(self.meas_voltage_var.get())
+            if not math.isfinite(voltage):
+                raise ValueError("non-finite voltage")
+        except (ValueError, TypeError, OverflowError):
+            self._notify_error("Measurement", "Source voltage must be finite and numeric. No solve was run.")
+            return

         if self.last_doped_result is None:
             # A statement of what is missing from the DEVICE, not an
@@ -5799,17 +5807,6 @@ class TCADApplication(tk.Tk):

         axis = self.meas_axis_var.get()

-        try:
-            voltage = float(self.meas_voltage_var.get())
-        except ValueError:
-
-            self._notify_error(
-                "Measurement recipe",
-                "Source voltage must be numeric.",
-            )
-
-            return
-
         doped_result = self.last_doped_result

         if self._doping_is_stale():
@@ -5832,7 +5829,7 @@ class TCADApplication(tk.Tk):
         from tcad.device.devsim.mesh_import import import_process_result
         from tcad.device.devsim.mesh_conservation import MeshAreaConservationError
         from tcad.device.devsim.doping_mapping import apply_doping, UnsupportedDopingState
-        from tcad.characterization.interface import current_unit_note, format_current
+        from tcad.characterization.interface import current_unit_note, format_current, validate_bias_point
         from tcad.characterization.pn_junction_iv_sweep import run_pn_junction_iv_sweep
         from tcad.characterization.robust_iv_sweep import (
             run_robust_pn_junction_iv_sweep,
@@ -5966,6 +5963,9 @@ class TCADApplication(tk.Tk):
                     fixed_contacts={gnd_contact: 0.0},
                 )

+            if len(result.points) != 1:
+                raise ValueError("Measurement must return exactly one bias point.")
+            validate_bias_point(result.points[0], (source_contact, gnd_contact))
         except UnsupportedDopingState as exc:

             # Tier 1-1: the central canonical-state gate refused this
@@ -6244,6 +6244,15 @@ class TCADApplication(tk.Tk):
         among the resolved contacts. Contact names are the Pin names
         themselves (point_contacts in resolve_electrode_pins names each
         contact after its Pin's own `name` field)."""
+        # A failed new attempt must not leave the previous CSV result available.
+        self.last_electrode_result = None
+        import math
+        try:
+            if any(not math.isfinite(float(v)) for v in (drain_voltage, gate_voltage, body_voltage)):
+                raise ValueError("non-finite voltage")
+        except (ValueError, TypeError, OverflowError):
+            self._notify_error("Electrode", "Drain/Gate/Body V must be finite and numeric. No solve was run.")
+            return None
         if self.last_electrode_import is None:
             self._log("\nDC OPERATING POINT: pins not resolved yet -- nothing to solve.\n")
             return None
@@ -6375,6 +6384,10 @@ class TCADApplication(tk.Tk):
                 drain_voltage=drain_voltage, gate_voltage=gate_voltage,
                 body_contact=body_contact, body_voltage=body_voltage,
             )
+            from tcad.characterization.interface import validate_bias_point
+            # The ideal oxide gate has voltage evidence, not DD current evidence.
+            validate_bias_point(op_point, (source_contact, drain_contact) +
+                                ((body_contact,) if body_contact else ()))
         except UnsupportedDopingState as exc:
             # Tier 1-1: blocked by the central canonical-state gate
             # before any doping write or solve -- not a solve failure.
@@ -6420,6 +6433,7 @@ class TCADApplication(tk.Tk):
         return op_point

     def _on_dc_operating_point_clicked(self):
+        self.last_electrode_result = None
         try:
             vd = float(self.dc_drain_v_var.get())
             vg = float(self.dc_gate_v_var.get())
diff --git a/tests/unit/test_measurement_entry_point_gate_mock.py b/tests/unit/test_measurement_entry_point_gate_mock.py
index a18d1e0..c421636 100644
--- a/tests/unit/test_measurement_entry_point_gate_mock.py
+++ b/tests/unit/test_measurement_entry_point_gate_mock.py
@@ -141,7 +141,10 @@ def _dc_operating_point(app, state, nodes):
     from tcad.mesh.pin import Pin

     fake = FakeDevsim(*zip(*nodes))
-    recorder = Recorder(SimpleNamespace(currents={"Source": -1.0e-6, "Drain": 1.0e-6, "Gate": 0.0}))
+    from tcad.characterization.interface import BiasPoint
+    recorder = Recorder(BiasPoint(
+        voltages={"Source": 0.0, "Drain": 0.1, "Gate": 1.0},
+        currents={"Source": -1.0e-6, "Drain": 1.0e-6}))
     app.wafer_state = state
     app.last_physics_status = None
     app.electrode_pins = [Pin(name="Source", role="Source", x_um=1.0, y_um=0.0),
```
