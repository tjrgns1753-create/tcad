# E6N-R 완료: 실제 필드의 영역·바이어스·전위 기준 표시

## 판정과 물리적 의미

현재 성공한 2단자 측정의 실제 영역·두 접점 전압·선택 필드 단위가 화면에
나타난다. Potential은 원시 API 값을 보존하며 접점 인가전압으로 이동하지 않는다.
원시 Potential의 기준과 접점 인가전압이 다를 수 있다는 한국어 설명을 추가했다.
PN·MOS·임의 공정 정확성 또는 새 capability 승인은 아니다.

공식 근거: [DEVSIM simple_physics](https://github.com/devsim/devsim/blob/main/python_packages/simple_physics.py).
Si n형 ohmic contact 식은 Potential = bias + V_t log(n_eq/n_i)이다.
설치 2.11.0 helper도 import 없이 읽어 같은 식을 확인했다.
실제 원격 helper 함수 source SHA는
9e46882b1a0c4643ebb25652bd8cc025650ce77e3a3f9b89b019be567060a46c.
이는 특정 Si/Boltzmann/ohmic 모델의 기준이며 다른 구조로 일반화하지 않는다.

## 시작과 수정 전 재현

시작 tracked clean, HEAD 64d59bd, branch claude/remote-runner.
PLAN 단독 커밋 99a957e. Serena 도구 미제공, 직접 읽기 fallback.
실제 GUI draw 함수의 AST를 엔진 없이 호출해 기존 설명에 region,
left/right 전압, 원시 Potential 기준 설명이 전부 없는 것을 재현했다.
합성 자료의 숫자는 물리 결과로 주장하지 않는다.

## 수정 내용 및 국소 unit

node_fields.py에 _field_bias_point를 추출해 표시·저장의 같은 검증 규칙을
공유한다. Q의 두 접점 완전성·단위·수렴·region 검사 의미는 불변이다.
field_caption은 snapshot 자신의 결과에서 모든 접점 전압을 읽는다.
GUI는 caption 검증을 먼저 하므로 누락/불일치 기록이면 점도 표시하지 않는다.
legend를 표면 위 bottom anchor로 배치한다. 숫자·위치·색 변환은 변경하지 않았다.

순수 caption / capture / export / contacts 4개 로컬 unit rc=0.
caption은 3개 layer마다 영역·두 접점·단위·보간 없음과 Potential 전용 설명을
검사하며, 누락/region 불일치/empty/nonfinite/단일 접점 결과는 map 0개다.
기존 capture unit에는 새 정상 결과 fixture만 추가했고 assertion을 완화하지 않았다.
로컬 엔진·Tk import 0회, 물리 solve 0회.

## 원격 실측과 독립 검증

[Actions run 37973087515](https://github.com/tjrgns1753-create/tcad/actions/runs/37973087515),
실행 SHA 87bc92277eb7219276bbf8f5345749559e00110f, artifact remote-run-66.
GitHub-hosted Windows에서 기존 uniform ACTIVE Si / +1mV / 73 노드 사용.
caption / pure_caption / pure_export / contacts / snapshot / hover / readout /
gate_control 8개 모두 COMPLETED, rc=0, cleanup_ok=True.

- 실제 측정 3 solve. 단순 표시·저장 때문에 추가 solve하지 않았다.
- 원격 별도 current/gate 대조군에도 실제 solve가 있다. 원격 전체 0회가 아니다.
- 실제 접점 전압: Si_xmin=0 V, Si_xmax=0.001 V.
- 0V ground의 세 노드 원시 Potential: 각각 0.3576447899345236 V.
- 실제 V_t/n_i/NetDoping과 공식 접점 식으로 계산한 기대값도 정확히 동일,
  최대 오차 0.0 V (사전 보조 기준 1e-9 V).
- 이 식 일치는 접점 경계의 구현 일관성이지 PN의 독립 정확성 증명이 아니다.
- 3개 field layer 모두 73 actual node와 올바른 한국어 caption을 실제 Tk에서 확인.
- live public API 전체 배열과 snapshot 일치, 마지막 device 목록 비어 있음.
- 요청 전압 수정 시 오래된 map은 삭제됨.
- 전체 export JSON이 Q/P 고정 원시 결과와 동일. 파일 SHA:
  8111c300184eccc680938178e6112fc6e8152e2b4789cc1cdfa79d935df1056f.

독립 verify_artifact.py는 15개 입력을 실행 git blob과, 13개 원시 파일을
summary의 크기·SHA와 대조했다. ground 식을 JSON에서 다시 계산했고
전체 73개 배열과 접점·단위·출처를 이전 자료와 비교했다.
일부 노드만 골라 PASS하지 않는다. 원본 mesh는 artifact에 없고 SHA만 보존된다.

## 전체 semantic diff

production 및 기존 unit fixture 변경 전부이며 아래 300줄 미만이다.
신규 unit/원격 검사/profile/request/본 감사 파일은 별도 Git 커밋에서 확인한다.

```diff
diff --git a/tcad/characterization/node_fields.py b/tcad/characterization/node_fields.py
index 239dfa6..667aac5 100644
--- a/tcad/characterization/node_fields.py
+++ b/tcad/characterization/node_fields.py
@@ -75,21 +75,11 @@ def field_samples(fields, layer):
     return tuple((x, y, v, color(v)) for (x, y), v in zip(fields.xy_um, values)), lo, hi


-def save_node_field_evidence(fields, result, context, path):
-    """Single atomic JSON replacement of actual fields plus bias/source evidence.
-
-    Caller must compare context against the current wafer before invoking.
-    GUI_SESSION_ONLY provenance is not a serialized canonical state/checkpoint.
-    """
-    from dataclasses import asdict
-    import json
-    import os
-    from pathlib import Path
-    import tempfile
+def _field_bias_point(fields, result):
+    """Shared evidence boundary for displaying/saving the same 2-terminal result."""
     from tcad.characterization.interface import validate_bias_point
-    from tcad.characterization.source_context import source_evidence
     validate_node_fields(fields)
-    if len(result.points) != 1 or result.region != fields.region:
+    if result is None or len(result.points) != 1 or result.region != fields.region:
         raise ValueError("Field export needs its own single-bias region result.")
     point = result.points[0]
     validate_bias_point(point)
@@ -102,6 +92,35 @@ def save_node_field_evidence(fields, result, context, path):
     if (result.metadata.get("current_unit") != "A/cm" or result.metadata.get("device_dimension") != 2 or
             result.metadata.get("current_normalization") != "per_out_of_plane_depth"):
         raise ValueError("Field export is limited to established 2D current units.")
+    return point
+
+
+def field_caption(fields, result, layer):
+    """Describe original solved values; never rebase Potential to a contact bias."""
+    point = _field_bias_point(fields, result)
+    samples, lo, hi = field_samples(fields, layer)
+    bias = "; ".join(f"{contact}={float(value):+.6g} V" for contact, value in point.voltages.items())
+    text = (f"영역 {fields.region} | {len(samples)} 실제 노드 (actual node samples) | {bias}\n"
+            f"{layer}: 선형색 파랑={lo:.4e}, 빨강={hi:.4e} {FIELD_UNITS[layer]}; "
+            "보간 없음 (No interpolation).")
+    if layer == "potential":
+        text += "\nDEVSIM 원시 Potential; 접점 인가전압과 전위 기준이 다를 수 있음."
+    return text
+
+
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
+    from tcad.characterization.source_context import source_evidence
+    point = _field_bias_point(fields, result)
     payload = {"schema": 1, "sampling": "ACTUAL_NODES_NO_INTERPOLATION", "node_count": len(fields.xy_um),
                "units": {"xy_um": "um", **FIELD_UNITS}, "snapshot": asdict(fields),
                "measurement": {"name": result.name, "region": result.region, "sweep_contact": result.sweep_contact,
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index f4cc1b6..f1f3f1f 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -8902,7 +8902,7 @@ class TCADApplication(tk.Tk):
     def _draw_measurement_field(self, layer, x0, x1, surface_y):
         """Display actual solved node samples only, on the current wafer."""
         from tcad.characterization.source_context import source_context_matches
-        from tcad.characterization.node_fields import field_samples, FIELD_UNITS
+        from tcad.characterization.node_fields import field_samples, field_caption
         try:
             settings = (float(self.meas_voltage_var.get()), self.meas_axis_var.get(), self.meas_source_pin.get())
             if (self._viewing_step_index is not None or
@@ -8910,18 +8910,18 @@ class TCADApplication(tk.Tk):
                     not source_context_matches(getattr(self, "_measurement_fields_context", None),
                                                self.last_final_mesh, self.wafer_state, self.electrode_pins)):
                 raise ValueError("No matching current-wafer measurement; remeasure to obtain node fields.")
-            samples, lo, hi = field_samples(getattr(self, "_measurement_fields", None), layer)
+            fields = getattr(self, "_measurement_fields", None)
+            text = field_caption(fields, getattr(self, "_measurement_fields_result", None), layer)
+            samples, _, _ = field_samples(fields, layer)
             if not self._viewer_scale:
                 raise ValueError("No current mesh coordinate transform.")
             cx0, xmin, xs, sy, ys = self._viewer_scale
             for x, y, value, color in samples:
                 cx, cy = cx0 + (x-xmin)*xs, sy-y*ys
                 self.canvas.create_oval(cx-2, cy-2, cx+2, cy+2, fill=color, outline=color, tags="solved_field_node")
-            text = (f"{layer}: {len(samples)} actual node samples; linear blue={lo:.4e}, red={hi:.4e} {FIELD_UNITS[layer]}. "
-                    "No interpolation; selected measurement bias only.")
         except (ValueError, TypeError, OverflowError) as exc:
             text = f"Field unavailable: {exc}"
-        self.canvas.create_text((x0+x1)/2, surface_y-35, text=text, fill=Tokens.FG_MUTED,
+        self.canvas.create_text((x0+x1)/2, surface_y-12, text=text, anchor="s", fill=Tokens.FG_MUTED,
                                 font=(Tokens.FONT_UI, 9), width=x1-x0-40, tags="solved_field_note")

     def _measurement_field_hover_note(self, event):
diff --git a/tests/unit/test_node_fields_mock.py b/tests/unit/test_node_fields_mock.py
index 1ce8844..2fce483 100644
--- a/tests/unit/test_node_fields_mock.py
+++ b/tests/unit/test_node_fields_mock.py
@@ -12,6 +12,7 @@ def deny(event,args):
 sys.addaudithook(deny)
 from tcad.characterization.node_fields import capture_node_fields,field_samples,MAX_CAPTURE_NODES
 from tcad.characterization.source_context import capture_source_context
+from tcad.characterization.interface import BiasPoint, CharacterizationResult, current_unit_metadata
 class API:
     def __init__(self):
         self.a={'x':[0,1e-4], 'y':[0,-1e-4], 'Potential':[-.2,.3], 'Electrons':[1e16,2e16], 'Holes':[1e4,0]}
@@ -43,6 +44,8 @@ with tempfile.TemporaryDirectory() as d:
     state=object(); settings=[.001,'x','max']; nodes=[]; notes=[]
     app=S(last_final_mesh=p,wafer_state=state,electrode_pins=[],_viewing_step_index=None,
           _measurement_fields=fields,_measurement_fields_context=capture_source_context(p,state,[]),
+          _measurement_fields_result=CharacterizationResult('synthetic','deleted','Si','a',
+              [BiasPoint({'a':.001,'b':0},{'a':1e-6,'b':-1e-6})],current_unit_metadata(2)),
           _measurement_fields_settings=tuple(settings),_viewer_scale=(0,0,1,0,1),
           meas_voltage_var=S(get=lambda:settings[0]),meas_axis_var=S(get=lambda:settings[1]),meas_source_pin=S(get=lambda:settings[2]),
           canvas=S(create_oval=lambda *a,**k:nodes.append((a,k)),create_text=lambda *a,**k:notes.append(k['text'])))

```

## 경계와 한계

물리 equation·engine API 내부·dopant·geometry·공정·gate는 변경하지 않았다.
표시 영어 anchor 문구는 기존 assertion 호환을 위해 괄호 안에 유지하되
사용자 설명의 기본 언어는 한국어다.
포화/고주입/PN 전체 수렴을 이 uniform case로 승인하지 않는다.
GUI_SESSION_ONLY 출처는 완전한 canonical 재시작 checkpoint가 아니다.
전체 회귀는 실행하지 않았고 국소 대조군만 실행했다.
코드 git diff --check rc=0. main 변경 없음.

