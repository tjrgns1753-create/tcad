# E6N-M 실제 측정 노드 필드 보존·표시

## 판정과 물리 범위

지원되는 현재 웨이퍼의 단일 전압 측정에서 실제 DEVSIM Potential, Electrons,
Holes를 장치 삭제 전에 복사하고 GUI에 노드 점 지도로 표시했다. 보간·연속장·
삼각형 평균은 구현하지 않았다. 공식 조회 API만 사용했고 solve·방정식·gate는
변경하지 않았다. 공식 API 사용 예: https://github.com/devsim/devsim_3dmos/blob/main/ieee/mos90.py

이 검증은 기존 uniform ACTIVE Si 저항 입력(2um × 0.5um, donor 1e16 cm^-3,
+1mV)에 한정한다. PN·MOSFET·모든 공정 순서의 물리적 승인이 아니다.

## 사전 기준과 실행 위치

PLAN 커밋 0986997. 로컬 엔진/Tk import 없이 반례·배열 검증 2개 PASS.
실제 DEVSIM/Tk 검증은 GitHub Windows만 사용했다.
run https://github.com/tjrgns1753-create/tcad/actions/runs/37570252227
실행 SHA 1b03e34fd3a80eb830ceec1c97124bf5c61ec18e, artifact remote-run-61.
5개 단계 COMPLETED/RC0/cleanup true: fields 3.016s, pure .5s, validity .5s,
entry_gate 1s, uniform_control 1.516s. 캡처 추가 solve 없음(실제 측정 3회 그대로).

## 실제 결과

- 73개 노드 x/y와 세 필드가 삭제 전 공식 조회 API 값과 동일했다.
- 세 레이어 모두 73개 노드 점. 좌표 cm→um은 기존 import scale의 역변환뿐.
- 균일 저항 전위 선형해 상대오차 5.551115123125783e-14.
- 캐리어 finite/positive, 캡처는 device 삭제 후에도 보존, device 누수 0.
- 전압 선택 변경은 이전 필드 미표시. NaN 재측정 시 이전 필드 제거.
- 기존 전류 단위와 CHEMICAL/UNKNOWN solve/write0 대조군 그대로 PASS.

합성 반례: 모델 누락, 길이 차이, NaN, 음수 캐리어, 캡처 상한, state/mesh/bias/
history 출처 불일치 차단. 실제 음수 캐리어 발생을 관측했다는 뜻은 아니다.

## 기준 문구 정정

check_gui.py의 'Existing uniform resistor criterion' 주석은 정확하지 않다.
기존 E6I TOL_PSI_LINEAR는 1e-2이고 이번 스크립트는 1e-6의 더 엄격한 보조
배열 검사를 사용했다. 기존 production 수렴 기준이나 물리 승인 기준을 수정하지
않았다. 실제 오차는 둘 다 만족한다. 결과에 맞춰 기준을 완화하지 않았다.

## 증거 독립 대조

verify_artifact.py로 고정 run/SHA, 9개 소스 input, 원시 output/log 9파일의
byte 크기·SHA256과 5개 단계, 73개 배열 길이·finite·양수·전위 선형식 재계산
검증 PASS. input checkout LF/CRLF 경우만 구분; 원시 증거는 정규화하지 않음.
원시 파일은 raw/에 그대로 보존했다.

## 한계와 다음 단계

캡처 20,000노드, 표시 2,000노드 초과는 명시적 미표시. 전체 표본을 골라 줄이지
않는다. DC 전극 패널 및 과거 step field 보존·node hover는 아직 이 배치 범위 밖.
필드 캡처 실패는 유효한 전류 결과까지 버리지 않고 field unavailable로 분리한다.
mesh hash·canonical 객체·전극 핀·측정 설정 provenance만 확인하며, 독립적인
물리 모델 승인이라고 표시하지 않는다. 일반 메쉬·공정·PN/DD gate 유지.

## 실제 production diff

```diff
diff --git a/tcad/characterization/node_fields.py b/tcad/characterization/node_fields.py
new file mode 100644
index 0000000..87571de
--- /dev/null
+++ b/tcad/characterization/node_fields.py
@@ -0,0 +1,59 @@
+"""Copy already-solved DEVSIM node values; no engine import or interpolation."""
+from dataclasses import dataclass
+import math
+
+FIELD_NAMES = {"potential": "Potential", "electron": "Electrons", "hole": "Holes"}
+FIELD_UNITS = {"potential": "V", "electron": "cm^-3", "hole": "cm^-3"}
+MAX_CAPTURE_NODES = 20_000
+MAX_DISPLAY_NODES = 2_000
+
+
+@dataclass(frozen=True)
+class NodeFields:
+    region: str
+    xy_um: tuple
+    potential: tuple
+    electron: tuple
+    hole: tuple
+
+
+def capture_node_fields(module, device, region, length_scale_to_cm):
+    """Caller must validate the successful bias point before calling.
+
+    Public API only; copies into immutable tuples independent of device lifetime.
+    Absence/invalidity is not zero and never triggers a new solve.
+    """
+    scale = float(length_scale_to_cm)
+    if not math.isfinite(scale) or scale <= 0:
+        raise ValueError("Invalid node-coordinate length scale.")
+    names = set(module.get_node_model_list(device=device, region=region))
+    if not {"x", "y", *FIELD_NAMES.values()} <= names:
+        raise ValueError("Required solved node fields are missing.")
+    read = lambda name: tuple(float(v) for v in module.get_node_model_values(
+        device=device, region=region, name=name))
+    x = read("x")
+    if not 0 < len(x) <= MAX_CAPTURE_NODES:
+        raise ValueError("Node field capture resource limit or empty region.")
+    arrays = [x, read("y"), *(read(name) for name in FIELD_NAMES.values())]
+    if any(len(a) != len(x) or not all(math.isfinite(v) for v in a) for a in arrays):
+        raise ValueError("Node field arrays differ in length or contain non-finite values.")
+    if any(v < 0 for a in arrays[3:] for v in a):
+        raise ValueError("Negative carrier concentration is not displayable.")
+    xy = tuple((a / scale, b / scale) for a, b in zip(x, arrays[1]))
+    if not all(math.isfinite(v) for pair in xy for v in pair):
+        raise ValueError("Converted coordinates are non-finite.")
+    return NodeFields(region, xy, *arrays[2:])
+
+
+def field_samples(fields, layer):
+    """All actual nodes, linear blue/red range. No decimation or interpolation."""
+    if not isinstance(fields, NodeFields) or layer not in FIELD_NAMES:
+        raise ValueError("No solved field snapshot.")
+    if len(fields.xy_um) > MAX_DISPLAY_NODES:
+        raise ValueError("Node display resource limit; no partial map shown.")
+    values = getattr(fields, layer)
+    lo, hi = min(values), max(values)
+    def color(v):
+        t = (v-lo)/(hi-lo) if hi > lo else .5
+        return f"#{round(255*t):02x}40{round(255*(1-t)):02x}"
+    return tuple((x, y, v, color(v)) for (x, y), v in zip(fields.xy_um, values)), lo, hi
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index f9df5dd..f8aa09a 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -5769,6 +5769,10 @@ class TCADApplication(tk.Tk):
             return None

     def run_measurement(self):
+        # Any new attempt invalidates the previous field, including bad input.
+        self._measurement_fields = None
+        self._measurement_fields_context = None
+        getattr(self, "redraw", lambda: None)()
         import math
         try:
             voltage = float(self.meas_voltage_var.get())
@@ -5828,6 +5832,9 @@ class TCADApplication(tk.Tk):
         region = doped_result.doping.regions[0].region
         kind = doped_result.doping.kind

+        from tcad.characterization.source_context import capture_source_context, source_context_matches
+        field_context = capture_source_context(self.last_final_mesh, self.wafer_state, self.electrode_pins)
+
         from tcad.device.devsim.mesh_import import import_process_result
         from tcad.device.devsim.mesh_conservation import MeshAreaConservationError
         from tcad.device.devsim.doping_mapping import apply_doping, UnsupportedDopingState
@@ -5968,6 +5975,18 @@ class TCADApplication(tk.Tk):
             if len(result.points) != 1:
                 raise ValueError("Measurement must return exactly one bias point.")
             validate_bias_point(result.points[0], (source_contact, gnd_contact))
+            from tcad.characterization.node_fields import capture_node_fields
+            try:
+                fields = capture_node_fields(module, imported.device, region, length_scale_to_cm)
+            except Exception as exc:
+                # Field export failure does not invalidate an already-validated
+                # terminal current. It never leaves an older field in place.
+                self._log(f"Node fields unavailable: {exc}\n")
+            else:
+                if source_context_matches(field_context, self.last_final_mesh, self.wafer_state, self.electrode_pins):
+                    self._measurement_fields = fields
+                    self._measurement_fields_context = field_context
+                    self._measurement_fields_settings = (voltage, axis, self.meas_source_pin.get())
         except UnsupportedDopingState as exc:

             # Tier 1-1: the central canonical-state gate refused this
@@ -6018,6 +6037,7 @@ class TCADApplication(tk.Tk):
         point = result.points[0]
         source_i = point.currents[source_contact]
         gnd_i = point.currents[gnd_contact]
+        self.redraw()

         self.history.append(
             f"Measurement: {source_contact}={voltage}V"
@@ -8864,28 +8884,34 @@ class TCADApplication(tk.Tk):
                         text="UV EXPOSURE", fill="#2e86de",
                     )

-        # POTENTIAL / ELECTRON / HOLE layers need per-node DevSim field
-        # data (Potential/Electrons/Holes), which run_measurement's
-        # worker does not serialize back to the GUI today -- only
-        # terminal currents (see run_measurement / _make_measurement_panel).
-        # Rather than silently ignoring the layer switch or fabricating
-        # a fake field map, say plainly that the data isn't there yet.
-        # This is the one honest limitation flagged in the redesign plan.
         selected_layer = self.viewer_layer_var.get()
         if selected_layer in ("potential", "electron", "hole"):
-            T = Tokens
-            canvas.create_rectangle(
-                x0, surface_y - 20, x1, surface_y + 20,
-                fill=T.BG_1, outline=T.LINE_STRONG,
-            )
-            canvas.create_text(
-                (x0 + x1) / 2, surface_y,
-                text=f"{self._VIEWER_LAYER_LABELS[selected_layer]} field data not "
-                     "available — device measurement does not export per-node "
-                     "field values yet (terminal currents only).",
-                fill=T.FG_MUTED, font=(T.FONT_UI, 9), justify="center",
-                width=x1 - x0 - 40,
-            )
+            self._draw_measurement_field(selected_layer, x0, x1, surface_y)
+
+    def _draw_measurement_field(self, layer, x0, x1, surface_y):
+        """Display actual solved node samples only, on the current wafer."""
+        from tcad.characterization.source_context import source_context_matches
+        from tcad.characterization.node_fields import field_samples, FIELD_UNITS
+        try:
+            settings = (float(self.meas_voltage_var.get()), self.meas_axis_var.get(), self.meas_source_pin.get())
+            if (self._viewing_step_index is not None or
+                    settings != getattr(self, "_measurement_fields_settings", None) or
+                    not source_context_matches(getattr(self, "_measurement_fields_context", None),
+                                               self.last_final_mesh, self.wafer_state, self.electrode_pins)):
+                raise ValueError("No matching current-wafer measurement; remeasure to obtain node fields.")
+            samples, lo, hi = field_samples(getattr(self, "_measurement_fields", None), layer)
+            if not self._viewer_scale:
+                raise ValueError("No current mesh coordinate transform.")
+            cx0, xmin, xs, sy, ys = self._viewer_scale
+            for x, y, value, color in samples:
+                cx, cy = cx0 + (x-xmin)*xs, sy-y*ys
+                self.canvas.create_oval(cx-2, cy-2, cx+2, cy+2, fill=color, outline=color, tags="solved_field_node")
+            text = (f"{layer}: {len(samples)} actual node samples; linear blue={lo:.4e}, red={hi:.4e} {FIELD_UNITS[layer]}. "
+                    "No interpolation; selected measurement bias only.")
+        except (ValueError, TypeError, OverflowError) as exc:
+            text = f"Field unavailable: {exc}"
+        self.canvas.create_text((x0+x1)/2, surface_y-35, text=text, fill=Tokens.FG_MUTED,
+                                font=(Tokens.FONT_UI, 9), width=x1-x0-40, tags="solved_field_note")

     # --------------------------------------------------------
     # STAGES
```

