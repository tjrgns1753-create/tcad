# E6N-O 노드 필드 저장·요청 설정 편집 시 지도 무효화

## 판정

지원된 성공한 2-terminal 측정의 모든 노드 배열과 해당 bias/contact/current/unit/
source를 단일 JSON으로 저장한다. 현재 source·설정·history를 저장 dialog 전후에
확인한다. 새 측정 시도와 reset에서 결과 복사본도 해제. 전압/axis/source 편집은
추가 solve 없이 redraw해 이전 지도 미표시. 일반 물리 승인을 내리지 않는다.

## 사전 고정 및 실제 실행

PLAN 34af1df → 편집 즉시 무효화 명시 7b02a8c(실제 결과 전).
로컬 순수 저장/hover/snapshot 3개 PASS, 엔진/Tk import 0.
원격 source ae9c7aa1d13b9feac2e636dba685e93637a583c1,
https://github.com/tjrgns1753-create/tcad/actions/runs/37571485166
artifact remote-run-63. export/pure/hover/snapshot/gate_control 5개 RC0/COMPLETED/
cleanup true. 실제 uniform ACTIVE Si 저항 +1mV, 3 solve 그대로. engine 내부 변경0.

## 실제 저장 결과

raw/outputs/e6no_out/실제노드.json:
file SHA256 8111c300184eccc680938178e6112fc6e8152e2b4789cc1cdfa79d935df1056f
input mesh SHA256 ad1ad8a16d43fd2e0b57653258d9f6e92aff02154112df0fc732c95993eb5805

73개 xy/Potential/Electrons/Holes 배열 전체가 E6N-M live-API 대조 증거와 동일.
실제 두 접점 voltage/current 보존, unit A/cm, potential V, carrier cm^-3, xy um.
metadata의 차원2·단위깊이 정규화 유지. 결과는 성공 직후 deepcopy하여 장치 삭제와
후속 result 변경에서 분리한다. JSON은 restart/checkpoint가 아니다.

GUI source 변경은 dialog 0회, bias 편집은 manual redraw 없이 노드0개.
실패한 재측정은 field와 result 없음, export dialog 없음. device 누수0.

## 거짓 성공 방지

합성 NaN/Inf/길이/음수 캐리어/미수렴/빈 point/잘못된 region/unit은 저장 거부,
기존 파일 byte 동일. serialize 후 임시 파일→os.replace 단일 교체, 임시 파일 정리.
source context는 GUI_SESSION_ONLY이지 전체 canonical 물리 상태를 직렬화한 것이
아니다. 보존된 배열을 바탕으로 새 물리/PN/MOS 승인을 발명하지 않는다.

## 독립 검증

verify_artifact.py: 고정 run/SHA, source11개 checkout hash, raw output/log10파일
byte/hash, 모든 단계, 실제 JSON hash·unit·bias·73개 전체 배열 대조 PASS.
원시 파일 정규화 없음. original fixture VTU 자체는 artifact에 포함하지 않았으며,
mesh SHA는 원격에서 현재 input bytes와 대조한 결과를 보존한 것이다.
기존 CHEMICAL/UNKNOWN write/solve0 및 전류 단위 대조군 PASS. 전체 회귀 미실행.

## 남은 표시 문제

이번 실행 후 자체 검토에서 redraw가 마지막 coord/hover readout을 지우지 않는
경로를 발견했다. 지도 자체는 무효화되지만 마지막 hover 숫자는 다음 mouse event
전까지 남을 수 있다. 다음 좁은 보완에서 redraw readout 해제를 검증한다.

## 실제 production diff

```diff
diff --git a/tcad/characterization/node_fields.py b/tcad/characterization/node_fields.py
index 4a13189..f00480e 100644
--- a/tcad/characterization/node_fields.py
+++ b/tcad/characterization/node_fields.py
@@ -17,6 +17,20 @@ class NodeFields:
     hole: tuple


+def validate_node_fields(fields):
+    """Evidence validation, not a new physical model or mesh approval."""
+    if not isinstance(fields, NodeFields) or not fields.region or not 0 < len(fields.xy_um) <= MAX_CAPTURE_NODES:
+        raise ValueError("Invalid field snapshot or capture resource limit.")
+    for key in FIELD_NAMES:
+        values = getattr(fields, key)
+        if len(values) != len(fields.xy_um) or not all(math.isfinite(v) for v in values):
+            raise ValueError("Field array length/non-finite evidence error.")
+        if key != "potential" and any(v < 0 for v in values):
+            raise ValueError("Negative carrier concentration.")
+    if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in fields.xy_um):
+        raise ValueError("Invalid node coordinates.")
+
+
 def capture_node_fields(module, device, region, length_scale_to_cm):
     """Caller must validate the successful bias point before calling.

@@ -42,7 +56,9 @@ def capture_node_fields(module, device, region, length_scale_to_cm):
     xy = tuple((a / scale, b / scale) for a, b in zip(x, arrays[1]))
     if not all(math.isfinite(v) for pair in xy for v in pair):
         raise ValueError("Converted coordinates are non-finite.")
-    return NodeFields(region, xy, *arrays[2:])
+    fields = NodeFields(region, xy, *arrays[2:])
+    validate_node_fields(fields)
+    return fields


 def field_samples(fields, layer):
@@ -59,6 +75,49 @@ def field_samples(fields, layer):
     return tuple((x, y, v, color(v)) for (x, y), v in zip(fields.xy_um, values)), lo, hi


+def save_node_field_evidence(fields, result, context, path):
+    """Single atomic JSON replacement of actual fields plus bias/source evidence.
+
+    Caller must compare context against the current wafer before invoking.
+    GUI_SESSION_ONLY provenance is not a serialized canonical state/checkpoint.
+    """
+    from dataclasses import asdict
+    import json
+    import os
+    from pathlib import Path
+    import tempfile
+    from tcad.characterization.interface import validate_bias_point
+    from tcad.characterization.source_context import source_evidence
+    validate_node_fields(fields)
+    if len(result.points) != 1 or result.region != fields.region:
+        raise ValueError("Field export needs its own single-bias region result.")
+    point = result.points[0]
+    validate_bias_point(point)
+    if result.sweep_contact not in point.voltages:
+        raise ValueError("Field result lacks its sweep voltage.")
+    if (result.metadata.get("current_unit") != "A/cm" or result.metadata.get("device_dimension") != 2 or
+            result.metadata.get("current_normalization") != "per_out_of_plane_depth"):
+        raise ValueError("Field export is limited to established 2D current units.")
+    payload = {"schema": 1, "sampling": "ACTUAL_NODES_NO_INTERPOLATION", "node_count": len(fields.xy_um),
+               "units": {"xy_um": "um", **FIELD_UNITS}, "snapshot": asdict(fields),
+               "measurement": {"name": result.name, "region": result.region, "sweep_contact": result.sweep_contact,
+                   "metadata": result.metadata, "voltages": point.voltages, "currents": point.currents, "converged": point.converged},
+               "source_evidence": source_evidence(context), "physics_scope": "SUPPORTED_MEASUREMENT_NOT_GENERAL_TCAD_APPROVAL"}
+    data = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
+    target = Path(path)
+    temporary = None
+    try:
+        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", dir=target.parent,
+                                         prefix=".node_fields_", suffix=".tmp", delete=False) as stream:
+            temporary = Path(stream.name)
+            stream.write(data)
+        os.replace(temporary, target)
+    finally:
+        if temporary is not None:
+            temporary.unlink(missing_ok=True)
+    return str(target)
+
+
 def node_near_pixel(fields, layer, transform, px, py, radius=3.0):
     """Nearest displayed node inside a UI hit radius; never an interpolated value."""
     samples, _, _ = field_samples(fields, layer)
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index 7e1c5af..3b0e0bb 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -1360,11 +1360,9 @@ class TCADApplication(tk.Tk):

     #: Visualization layers for the center viewer. "geometry" and
     #: "doping" read data this GUI already has on hand (the real mesh /
-    #: self.last_doped_result). "potential"/"electron"/"hole" need
-    #: node-level DevSim field data the measurement worker does not
-    #: serialize back today (only terminal currents) -- the toggle exists
-    #: so the surface is complete, but shows an honest placeholder rather
-    #: than fabricated field data until that plumbing exists.
+    #: self.last_doped_result). "potential"/"electron"/"hole" show real
+    #: solved node samples retained by the supported two-terminal measurement.
+    #: Missing/stale/over-budget fields remain explicitly unavailable.
     _VIEWER_LAYERS = ("geometry", "doping", "potential", "electron", "hole")
     _VIEWER_LAYER_LABELS = {
         "geometry": "GEOMETRY", "doping": "DOPING", "potential": "POTENTIAL",
@@ -5621,6 +5619,10 @@ class TCADApplication(tk.Tk):
         self.meas_voltage_var = self._field(
             frame, "Source voltage (V)", 0.3,
         )
+        # Editing requested bias/contacts must hide an older computed map
+        # immediately, not only after clicking MEASURE or moving the cursor.
+        for variable in (self.meas_voltage_var, self.meas_axis_var, self.meas_source_pin):
+            variable.trace_add("write", lambda *_: self.redraw())

         self.measure_button = ttk.Button(
             frame,
@@ -5633,6 +5635,8 @@ class TCADApplication(tk.Tk):
             padx=12,
             pady=(12, 3),
         )
+        ttk.Button(frame, text="실제 노드 필드 저장 (JSON)",
+                   command=self._on_export_node_fields_clicked).pack(fill="x", padx=12, pady=3)

         ttk.Separator(frame).pack(fill="x", pady=8)
         ttk.Label(frame, text="별도 기준 문제: 현재 웨이퍼와 무관한 고정 1D PN.\n"
@@ -5773,6 +5777,7 @@ class TCADApplication(tk.Tk):
         # Any new attempt invalidates the previous field, including bad input.
         self._measurement_fields = None
         self._measurement_fields_context = None
+        self._measurement_fields_result = None
         getattr(self, "redraw", lambda: None)()
         import math
         try:
@@ -5979,6 +5984,8 @@ class TCADApplication(tk.Tk):
             from tcad.characterization.node_fields import capture_node_fields
             try:
                 fields = capture_node_fields(module, imported.device, region, length_scale_to_cm)
+                from copy import deepcopy
+                field_result = deepcopy(result)
             except Exception as exc:
                 # Field export failure does not invalidate an already-validated
                 # terminal current. It never leaves an older field in place.
@@ -5987,6 +5994,7 @@ class TCADApplication(tk.Tk):
                 if source_context_matches(field_context, self.last_final_mesh, self.wafer_state, self.electrode_pins):
                     self._measurement_fields = fields
                     self._measurement_fields_context = field_context
+                    self._measurement_fields_result = field_result
                     self._measurement_fields_settings = (voltage, axis, self.meas_source_pin.get())
         except UnsupportedDopingState as exc:

@@ -8938,6 +8946,39 @@ class TCADApplication(tk.Tk):
         except (ValueError, TypeError, OverflowError):
             return ""

+    def _on_export_node_fields_clicked(self):
+        """Export only the successful field's own bias and current wafer source."""
+        from tcad.characterization.source_context import source_context_matches
+        from tcad.characterization.node_fields import save_node_field_evidence
+        def matches():
+            try:
+                return (self._viewing_step_index is None and
+                    (float(self.meas_voltage_var.get()), self.meas_axis_var.get(), self.meas_source_pin.get()) ==
+                        getattr(self, "_measurement_fields_settings", None) and
+                    getattr(self, "_measurement_fields", None) is not None and
+                    getattr(self, "_measurement_fields_result", None) is not None and
+                    source_context_matches(getattr(self, "_measurement_fields_context", None),
+                                           self.last_final_mesh, self.wafer_state, self.electrode_pins))
+            except (ValueError, TypeError, OverflowError):
+                return False
+        if not matches():
+            self._notify_error("필드 저장", "현재 웨이퍼와 일치하는 성공한 노드 측정 결과가 없습니다. 파일을 저장하지 않습니다.")
+            return
+        path = filedialog.asksaveasfilename(title="실제 노드 필드 저장", defaultextension=".json",
+                                          filetypes=[("Node field evidence", "*.json")])
+        if not path:
+            return
+        if not matches():
+            self._notify_error("필드 저장", "파일 선택 중 웨이퍼 또는 측정 설정이 바뀌었습니다. 저장하지 않습니다.")
+            return
+        try:
+            save_node_field_evidence(self._measurement_fields, self._measurement_fields_result,
+                                     self._measurement_fields_context, path)
+        except Exception as exc:
+            self._notify_error("필드 저장", f"노드 필드 증거 저장 실패: {exc}")
+            return
+        self._log(f"\n실제 노드 필드 저장: {path} (보간 없음; 일반 TCAD 물리 승인 파일 아님)\n")
+
     # --------------------------------------------------------
     # STAGES
     # --------------------------------------------------------
@@ -9080,6 +9121,7 @@ class TCADApplication(tk.Tk):
         self._measurement_fields = None
         self._measurement_fields_context = None
         self._measurement_fields_settings = None
+        self._measurement_fields_result = None

         # A device left over from a RESOLVE click that never reached DC
         # OPERATING POINT would otherwise stay registered in DevSim and
```

