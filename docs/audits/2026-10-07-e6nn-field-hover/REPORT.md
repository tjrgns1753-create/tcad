# E6N-N 실제 노드 hover·reset

## 판정

새 물리 모델이나 solve 없이 이미 검증된 실제 노드 배열을 GUI 마우스 handler에
연결했다. 노드와 3픽셀 이내일 때 가장 가까운 **표시 노드** 좌표·값·단위를
표시한다. 마우스 좌표의 보간 값이 아니다. 멀리 있는 좌표·이력·오래된 출처·
측정 설정 변경·부분 표시에서는 수치 없음. reset은 배열·source·settings를 해제.

## 사전 고정 / 실행 위치

PLAN b2f168e. 로컬 합성 helper/AST와 기존 doping hover 테스트 PASS(엔진/Tk0).
실제 계산/Tk는 원격만 실행. run https://github.com/tjrgns1753-create/tcad/actions/runs/37570833575
source dbcce97443dc33e3371418510c17c8cd2c41d1cf, artifact remote-run-62.
hover/pure/snapshot/doping_hover/gate_control 5개 COMPLETED/RC0/cleanup true.
실제 uniform ACTIVE 저항 +1mV, 기존 3 solve 그대로, 추가 solve 없음.

## 실제 값 대조

고정 node index 0, 좌표 (-1,-0.5)um:
Potential 0.3576447899345236 V,
Electrons 1.000000000001e16 cm^-3,
Holes 9999.99999999 cm^-3.
Tk _on_canvas_motion 결과가 배열의 .6e 표현과 같고 ‘보간 아님’ 포함.
노드 밖의 마우스·설정 변경은 수치 미표시, reset 후 노드/참조/장치 누수 0.
준페르미/질량작용 등 독립 검증을 새로 주장하지 않는다. PN·MOS gate 무변경.

## 독립 증거 확인

verify_artifact.py: 고정 run/SHA, 10개 input checkout SHA, output/log 원시 9파일
byte hash, 5개 단계, 3개 값·좌표·단위·한국어 readout 대조 PASS. 원시 정규화 없음.
기존 전류 단위·CHEMICAL/UNKNOWN 차단 대조군 PASS. 전체 회귀 미실행.

## 제한

큰 메쉬 표시 cap과 현재 2-terminal 측정 지원 범위는 이전 배치와 같다.
hover는 nearest displayed node 선택이며 정확한 연속장 평가/적분/PN 검증이 아니다.

## 실제 production diff

```diff
diff --git a/tcad/characterization/node_fields.py b/tcad/characterization/node_fields.py
index 87571de..4a13189 100644
--- a/tcad/characterization/node_fields.py
+++ b/tcad/characterization/node_fields.py
@@ -57,3 +57,18 @@ def field_samples(fields, layer):
         t = (v-lo)/(hi-lo) if hi > lo else .5
         return f"#{round(255*t):02x}40{round(255*(1-t)):02x}"
     return tuple((x, y, v, color(v)) for (x, y), v in zip(fields.xy_um, values)), lo, hi
+
+
+def node_near_pixel(fields, layer, transform, px, py, radius=3.0):
+    """Nearest displayed node inside a UI hit radius; never an interpolated value."""
+    samples, _, _ = field_samples(fields, layer)
+    cx0, xmin, xs, sy, ys = transform
+    if not all(math.isfinite(v) for v in (*transform, px, py, radius)) or xs <= 0 or ys <= 0 or radius <= 0:
+        raise ValueError("Invalid screen coordinate transform.")
+    nearest = None
+    best = radius * radius
+    for x, y, value, _ in samples:
+        distance = (cx0+(x-xmin)*xs-px)**2 + (sy-y*ys-py)**2
+        if distance <= best:
+            nearest, best = (x, y, value), distance
+    return nearest
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index f8aa09a..7e1c5af 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -1461,6 +1461,7 @@ class TCADApplication(tk.Tk):
         y_um = (surface_y - event.y) / y_scale
         readout = f"X {x_um:+8.3f} µm   Y {y_um:+8.3f} µm"
         readout += self._doping_unsupported_hover_note(x_um, y_um)
+        readout += getattr(self, "_measurement_field_hover_note", lambda event: "")(event)
         self.coord_var.set(readout)

     def _doping_unsupported_hover_note(self, x_um: float, y_um: float = 0.0) -> str:
@@ -8913,6 +8914,30 @@ class TCADApplication(tk.Tk):
         self.canvas.create_text((x0+x1)/2, surface_y-35, text=text, fill=Tokens.FG_MUTED,
                                 font=(Tokens.FONT_UI, 9), width=x1-x0-40, tags="solved_field_note")

+    def _measurement_field_hover_note(self, event):
+        """Read a nearby displayed node, not the field at the cursor coordinate."""
+        from tcad.characterization.node_fields import FIELD_NAMES, FIELD_UNITS, node_near_pixel
+        from tcad.characterization.source_context import source_context_matches
+        layer = self.viewer_layer_var.get()
+        if layer not in FIELD_NAMES or self._viewing_step_index is not None:
+            return ""
+        try:
+            fields = getattr(self, "_measurement_fields", None)
+            if fields is None or len(self.canvas.find_withtag("solved_field_node")) != len(fields.xy_um):
+                return ""
+            settings = (float(self.meas_voltage_var.get()), self.meas_axis_var.get(), self.meas_source_pin.get())
+            if (settings != getattr(self, "_measurement_fields_settings", None) or
+                    not source_context_matches(getattr(self, "_measurement_fields_context", None),
+                                               self.last_final_mesh, self.wafer_state, self.electrode_pins)):
+                return ""
+            node = node_near_pixel(fields, layer, self._viewer_scale, event.x, event.y)
+            if node is None:
+                return ""
+            x, y, value = node
+            return f"   [가까운 표시 노드 ({x:+.4f}, {y:+.4f}) µm: {value:.6e} {FIELD_UNITS[layer]}; 보간 아님]"
+        except (ValueError, TypeError, OverflowError):
+            return ""
+
     # --------------------------------------------------------
     # STAGES
     # --------------------------------------------------------
@@ -9052,6 +9077,10 @@ class TCADApplication(tk.Tk):

     def reset(self):

+        self._measurement_fields = None
+        self._measurement_fields_context = None
+        self._measurement_fields_settings = None
+
         # A device left over from a RESOLVE click that never reached DC
         # OPERATING POINT would otherwise stay registered in DevSim and
         # poison the next, unrelated solve -- delete it before clearing
```

