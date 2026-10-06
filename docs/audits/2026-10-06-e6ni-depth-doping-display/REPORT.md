# E6N-I: 실제 2D 좌표의 canonical 도핑 표시와 잘못된 농도 차단

## 결론

깊이 y를 무시하던 GUI 도핑 표시를 수정했다. 현재 mesh 삼각형 중심 (x,y)의
canonical 활성 net 도핑 부호를 표시하며 마우스 실제 y에서도 미지원 이유를 조회한다.
원격 실제 Tk/ViennaPS mesh 검사와 기존 DEVSIM 대조군, 총 7개 대상 검사를 통과했다.
이는 새 주입/확산 모델 또는 일반 PN 2D 검증이 아니며 기존 물리 gate를 해제하지 않는다.

## 물리적 대응 및 반례

순 도핑의 부호는 현재 활성 donor minus 활성 acceptor이다. 같은 x라도 깊이에 따라
두 값의 합이 달라질 수 있다. 이를 표면 y=0 값으로 기판 전체에 확장하는 것은 잘못이다.
사전 고정한 explicit 상태: Si (-5,5,-5,0) µm, donor 1e17 전체, acceptor 2e17
하부 y=[-5,-2.5]만 존재. 상부 net=+1e17, 하부 net=-1e17 cm^-3.
이 상태는 알려진 초기 도핑의 테스트 입력이지 실제 ion implantation 공정을 계산한 결과가 아니다.
donor+acceptor 공존 영역의 수송 승인도 아니다. 기존 보상 수송 gate는 유지된다.

수정 전 `_doping_color_segments`는 60개 x bucket을 전부 n색으로 반환했다.
같은 canonical 상태의 하부 실제 query는 -1e17였다. 로컬 AST 반례 및 원격의 고정된
이전 source `af3fafa` 함수로 둘 다 재현했다. 과거 소스를 checkout하거나 덮어쓰지 않았다.

## 추가 발견과 범위 보완

단순 부호 표시를 검사하다가 canonical `max(0.0, float(NaN))`이 0으로 처리되는
진짜 결함을 확인했다. 이를 무시하면 GUI와 측정 둘 다 잘못된 농도를 무도핑으로 받아들일 수 있다.
PLAN에 예외 범위를 기록하고 농도 값 유효성 검사만 추가했다.
비유한값 또는 음수 도펀트 농도는 세 concentration=None, UNSUPPORTED_BY_MODEL,
parameter=dopant_concentration_validity로 반환한다. 숫자 fallback이나 새 물리 식은 없다.
NetDoping 자체의 음수는 정상 p형이며 차단하지 않는다. 차단되는 음수는 개별 도펀트의 농도다.

## 실제 화면 검사 결과

실제 ViennaPS virgin mesh 400개 삼각형을 실제 Tk canvas에 표시했다.
각 canvas 삼각형을 역변환하여 원본 mesh의 같은 vertex와 대조하고, 중심 좌표에서
사전 explicit 입력의 해석적 부호/상태와 실제 색을 독립 비교했다.

| 상태 | n색 | p색 | 미상 | 알려진 0 |
|---|---:|---:|---:|---:|
| ACTIVE | 200 | 200 | 0 | 0 |
| 하부 CHEMICAL | 200 | 0 | 200 | 0 |
| 하부 UNKNOWN | 200 | 0 | 200 | 0 |
| 정확한 무도핑 | 0 | 0 | 0 | 400 |

최대 vertex 역변환 오차 8.881784197001252e-16 µm, 사전 기준 1e-7 µm 유지.
원본 mesh 바이트는 표시 전후 동일하다. 깊이 -4 µm에서는 unknown hover,
-1 µm에서는 지원 hover라는 실제 mouse-handler 대조를 통과했다.
과거 mesh 선택 시 현재 도핑 polygon 0개와 이력 도핑 미보존 문구를 확인했다.
정상 full refinement로 6400개 삼각형을 만들면 표시 상한 2000개를 넘으므로,
부분 채색을 전체처럼 보이지 않게 도핑 채색만 생략하고 그 이유를 표시한다.
기판 재료 형상, 공정 실행, solver gate는 그대로다.

## 잘못된 농도의 실제 전기 측정 차단

NaN/inf/음수 각각 기존 지원 uniform-resistor 입력의 canonical 농도만 잘못된 값으로
교체한 반례를 실제 GUI measurement 경로에 넣었다. 세 경우 모두:

- 호출 직전에 계수하고 호출 시 즉시 실패시키는 solve trap: 시도 0회.
- 기존 observer의 doping node_model/set_node_values 쓰기: 0회.
- `dopant_concentration_validity` 원인으로 UNSUPPORTED_BY_MODEL.
- 남아 있는 DEVSIM device 0개.

기존 정상 ACTIVE 전류 대조군은 별도 actual DD 경로에서 그대로 통과했다.
그 대조군의 최종 실행은 직접 3회 및 GUI 3회 solve다. CHEMICAL/UNKNOWN 차단도 유지된다.

## 원격 실행 및 실패 이력

시작 SHA af3fafad03c3b370dab5cfe843f7b36a66bce4ab, PLAN 단독 커밋 961e646.
구현 커밋 1676747, 농도 유효성 및 테스트 보완 커밋 481fe8a.

- 첫 run 37462459623: FAIL. canonical NaN 반례에서 unit 실패,
  실제 Tk 검사에는 polygon의 존재하지 않는 text option을 읽는 감사 코드 오류도 있었다.
  후자는 text 아이템만 조회하도록 고쳤다. 기준을 낮추거나 geometry를 변경하지 않았다.
  원본은 `raw_failure/`에 보존한다.
- [최종 run 37462960267](https://github.com/tjrgns1753-create/tcad/actions/runs/37462960267): PASS.
  실행 SHA `481fe8a07978ccbff95487ce9f856ca57d75561f`, 원본 `raw/`.
  대상 프로그램 11.752초(패키지 설치 제외), 실제 깊이 표시 검사 5.516초.
  해당 검사 표본 process-tree working-set 최대 145,813,504 bytes,
  0.5초 간격 표본이며 진짜 절대 최대 메모리라는 뜻은 아니다.

| 대상 | RC |
|---|---:|
| 실제 depth canvas | 0 |
| 실제 invalid measurement | 0 |
| 신규 pure/AST 계약 | 0 |
| 기존 canvas source 계약 | 0 |
| 구형 hover 호환 | 0 |
| 기존 canonical 측정 gate | 0 |
| 기존 GUI 전류 단위·ACTIVE DD·activation 차단 | 0 |

모든 자식은 COMPLETED, cleanup_ok=True. 전체 회귀는 아니다.
로컬 정확 inventory 및 no-resurrection 대조군도 통과했다.
원격 환경: GitHub-hosted Windows, Python 3.11.9, ViennaPS 4.6.2, DEVSIM 2.11.0.
부모 summary의 engine_info NOT_IMPORTED는 버전 조회 생략 표시이며 자식의 엔진 실행을 부정하지 않는다.
새 PN/산화 solve는 없고, 기존 uniform-resistor 대표 대조군만 실제 DD를 수행했다.

## Serena investigation 및 영향

Serena 도구가 세션에 없어서 rg/직접 읽기로 조사했다. 연결 성공을 주장하지 않는다.
target: `_draw_real_mesh_result`, `_doping_unsupported_hover_note`, `_on_canvas_motion`,
`WaferStateV2.net_doping_at`. 실제 draw caller는 redraw, hover caller는 mouse motion이다.
`_doping_color_segments`의 기존 integration test 및 `_material_surface_profile`의 테스트
계약 때문에 helper는 호환용으로 남겼으나 production 도핑 renderer는 호출하지 않는다.
현재 renderer는 last_doped_result의 마지막 profile 목록이 아니라 현재 canonical 상태를 읽는다.
예외/범위 밖/재료 불일치/다중 소유 cell은 전부 unknown 표시다. snap/mesh 이동은 하지 않는다.
이 display ownership은 DEVSIM node-mapping의 대체가 아니며 더 보수적이다.

## 무변경 및 한계

물리 방정식·모델 계수·정확 적분·상태 전달·엔진 내부·수송 gate 조건은 변경하지 않았다.
canonical의 숫자 유효성 검사는 변경했으므로 production 전체 무변경이라고 주장하지 않는다.
현재 표시 색은 삼각형 중심 표본의 부호이지 농도 크기 contour나 삼각형 내부 전체의
연속 해를 보증하지 않는다. 화면 legend에 이를 명시한다. 경계/가우시안 내부 변화의 해상도를
새로 승인하지 않는다. dense mesh의 표시 자원 상한도 명시하며 강제로 mesh를 거칠게 만들지 않는다.
과거 도핑 상태는 복원하지 않는다. 일반 2D PN/양의 시간 산화 미지원은 여전히 유지된다.
개인 이름·개인 경로·토큰 패턴 원시 JSON/log 스캔 0건. 원본 해시를 위해 원시 bytes는 수정하지 않았다.
전체 회귀/main 병합 없음. 임의 공정 순서의 모든 물리 현상이 완성됐다는 주장은 하지 않는다.

## 독립 재검사 및 Change diff

`verify_artifact.py`는 엔진 import 없이 full 실행 SHA, run ID, 12개 출력 + run.log
bytes/SHA-256, 모든 대상 종료 코드, raw 색 개수, 무효 농도 차단 및 정상 대조군을 재검사했다.
결과 PASS, 엔진 import 0회. `git diff --check`는 source 및 보완 보고서에서 0이다.
추가로 7개 source input을 고정 실행 SHA의 git blob과 대조했다. 로컬은 LF이고 원격 checkout은
CRLF이므로 raw input SHA를 로컬 bytes에 바로 대조하면 다르다. 같은 git blob에 CRLF 변환만
적용한 bytes는 원격 input 길이와 SHA-256에 7/7 정확 일치한다. 코드 차이가 아니다.
verifier에도 이 exact checkout 변형 검사(원본/LF/CRLF만 허용)를 추가했다.
원시 출력 bytes와 해시는 정규화하지 않고 그대로 대조한다. source bytes 자체가
checkout 간 동일하다는 주장은 하지 않는다. 실행 SHA와 보존 코드 내용은 동일하다.
이전 E6N-H 보고서의 인용 diff context 빈 줄 공백 오류도 제거했다. 원시 patch는 손대지 않았다.

실제 GUI/core/unit 전체 282줄 diff는 `CHANGE.patch`에 보존한다.
SHA-256: `1f88f1ad7a9003a49b1cca614fd7fa1ff2b0a7a296e4a5b612e9f6f3a822f6d5`.
아래는 같은 전체 diff이며 문서의 빈 context 줄에서 표시용 공백만 제거했다.
정확한 적용 가능한 bytes는 CHANGE.patch가 기준이다.

```diff
diff --git a/tcad/physics/wafer_state_v2.py b/tcad/physics/wafer_state_v2.py
index 61f6f5f..7fa39db 100644
--- a/tcad/physics/wafer_state_v2.py
+++ b/tcad/physics/wafer_state_v2.py
@@ -384,7 +384,24 @@ class WaferStateV2:
                     continue
                 if not _point_in(a.support_region_um, x_um, y_um):
                     continue
-                mag = max(0.0, float(a.concentration_at(x_um, y_um)))
+                import math
+                mag = float(a.concentration_at(x_um, y_um))
+                if not math.isfinite(mag) or mag < 0.0:
+                    return DopingQueryResult(
+                        donor_concentration=None, acceptor_concentration=None, net_doping=None,
+                        physics_status={
+                            "resolution": "UNSUPPORTED_BY_MODEL",
+                            "entries": [{
+                                "parameter": "dopant_concentration_validity",
+                                "material": owning.material,
+                                "resolution": "UNSUPPORTED_BY_MODEL",
+                                "note": f"attachment {a.attachment_id!r} returned a non-finite "
+                                        f"or negative dopant concentration at ({x_um}, {y_um}); "
+                                        "invalid concentration is not known zero",
+                            }],
+                            "notes": [],
+                        },
+                    )
                 if a.polarity == "donor":
                     donor += mag
                 else:
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index 4834124..d1d4773 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -1458,27 +1458,23 @@ class TCADApplication(tk.Tk):
         x_um = x_min + (event.x - x0) / x_scale
         y_um = (surface_y - event.y) / y_scale
         readout = f"X {x_um:+8.3f} µm   Y {y_um:+8.3f} µm"
-        readout += self._doping_unsupported_hover_note(x_um)
+        readout += self._doping_unsupported_hover_note(x_um, y_um)
         self.coord_var.set(readout)

-    def _doping_unsupported_hover_note(self, x_um: float) -> str:
-        """Empty normally; a real explanation appended to the
-        coordinate readout when hovering the doping overlay over an
-        UNSUPPORTED_BY_MODEL bucket -- so a user does not read the gray
-        hatch (_DOPING_UNSUPPORTED_MARKER, see _doping_color_segments())
-        as "doping is gone". Reuses net_doping_at()'s own real
-        physics_status note verbatim (the same computed fact the
-        overlay itself and _log_physics_status() already surface),
-        never a separately-worded approximation -- see
-        WaferState._polarity_sum()'s own note text, which already says
-        the dopant is preserved and excluded rather than zeroed.
+    def _doping_unsupported_hover_note(self, x_um: float, y_um: float = 0.0) -> str:
+        """Read canonical uncertainty at the cursor's actual (x,y).
+        Empty normally; the query's own unsupported note is displayed
+        instead of interpreting unknown as an absent dopant. Historical
+        geometry does not query the current wafer's doping.
         """
         if self.viewer_layer_var.get() != "doping" or self.wafer_state is None:
             return ""
+        if self._viewing_step_index is not None:
+            return "   [이력 도핑 미보존 — 현재 상태를 조회하지 않습니다.]"
         try:
-            result = self.wafer_state.net_doping_at(x_um)
+            result = self.wafer_state.net_doping_at(x_um, y_um)
         except Exception:
-            return ""
+            return "   [UNSUPPORTED: 이 좌표의 도핑 조회 실패]"
         if not result.physics_status:
             return ""
         notes = [e.get("note", "") for e in result.physics_status.get("entries", []) if e.get("note")]
@@ -7995,61 +7991,31 @@ class TCADApplication(tk.Tk):
             # the viewer's layer switch, _make_cross_section) -- GEOMETRY
             # shows the bare material fill, matching what each layer
             # name promises.
-            if self.viewer_layer_var.get() == "doping" and self.last_doped_result is not None and getattr(
-                self.last_doped_result, "doping", None
-            ) is not None:
-                for region_name in {r.region for r in self.last_doped_result.doping.regions}:
-                    region_tag = next(
-                        (t for t, n in material_names.items() if n == region_name),
-                        None,
-                    )
-                    if region_tag is None:
-                        continue
-                    profile = self._material_surface_profile(
-                        triangle_data, points, tags, region_tag, x_min, x_max,
-                    )
-                    if not profile:
-                        continue
-
-                    for x_lo_um, x_hi_um, color in self._doping_color_segments(
-                        region_name, x_min, x_max
-                    ):
-                        if x_hi_um <= x_lo_um:
-                            continue
-                        for seg_x_lo, seg_x_hi, seg_y_top, seg_y_bot in profile:
-                            # Intersect this surface bucket with the
-                            # doping color segment's own x-range (e.g.
-                            # step_junction only tints one side).
-                            lo = max(seg_x_lo, x_lo_um)
-                            hi = min(seg_x_hi, x_hi_um)
-                            if hi <= lo:
-                                continue
-                            cx_lo = x0 + (lo - x_min) * x_scale
-                            cx_hi = x0 + (hi - x_min) * x_scale
-                            cy_top = surface_y - seg_y_top * y_scale
-                            cy_bot = surface_y - seg_y_bot * y_scale
-                            # An UNSUPPORTED_BY_MODEL bucket (spec Sec6)
-                            # must never be blended into the normal n/p
-                            # blue/red convention -- rendered as a
-                            # distinct dim-gray hatch (sparser stipple
-                            # than the gray50 used for a real sign)
-                            # instead of passed as a literal Tk color. A
-                            # genuinely-zero bucket (final-review Fix 5)
-                            # is a DIFFERENT fact ("known, and zero" vs
-                            # "unknown") and gets its own distinct token
-                            # (FG_MUTED, not FG_DIM) and an even sparser
-                            # stipple so the three cases are all
-                            # visually distinguishable at a glance.
-                            if color == _DOPING_UNSUPPORTED_MARKER:
-                                fill, stipple = Tokens.FG_DIM, "gray25"
-                            elif color == _DOPING_ZERO_MARKER:
-                                fill, stipple = Tokens.FG_MUTED, "gray12"
-                            else:
-                                fill, stipple = color, "gray50"
-                            canvas.create_rectangle(
-                                cx_lo, cy_top, cx_hi, cy_bot,
-                                fill=fill, outline="", stipple=stipple,
-                            )
+            if self.viewer_layer_var.get() == "doping":
+                if self._viewing_step_index is not None:
+                    doping_note = "이력 도핑 미보존 — 현재 도핑을 과거 mesh에 표시하지 않습니다."
+                elif len(triangle_data) > _MAX_RENDERED_TRIANGLES:
+                    doping_note = f"도핑 채색 생략 — {len(triangle_data)}개 삼각형, 표시 상한 {_MAX_RENDERED_TRIANGLES}개."
+                else:
+                    # Display samples only: no surface-column extrusion, inventory
+                    # integration, invented interpolation or transport approval.
+                    for i, tri in enumerate(triangle_data):
+                        px = sum(float(points[n][0]) for n in tri) / 3.0
+                        py = sum(float(points[n][1]) for n in tri) / 3.0
+                        color = self._doping_color_at(px, py, material_names[tags[i]])
+                        if color == _DOPING_UNSUPPORTED_MARKER:
+                            fill, stipple = Tokens.FG_DIM, "gray25"
+                        elif color == _DOPING_ZERO_MARKER:
+                            fill, stipple = Tokens.FG_MUTED, "gray12"
+                        else:
+                            fill, stipple = color, "gray50"
+                        coords = [v for n in tri for v in to_canvas(n)]
+                        canvas.create_polygon(coords, fill=fill, outline="", stipple=stipple,
+                                              tags=("canonical_doping_sample",))
+                    doping_note = "도핑: 삼각형 중심의 활성 net 부호 표본 — n 파랑 / p 빨강 / 미상 회색; 농도 크기·셀 내부 분포 미표시."
+                canvas.create_text(x0 + 5, surface_y + 28, text=doping_note,
+                                   anchor="w", fill=Tokens.FG_DIM,
+                                   font=(Tokens.FONT_UI, 8))

             canvas.create_text(
                 x0 + 5, surface_y + 12,
@@ -8061,6 +8027,48 @@ class TCADApplication(tk.Tk):
         except Exception:
             return False

+    def _canvas_doping_query(self, x_um, y_um, material):
+        """Read one exact canonical owner; display only, no electrical gate bypass."""
+        import math
+        from tcad.physics.wafer_state_v2 import WaferStateV2, DopingQueryResult
+
+        def unknown(note):
+            return DopingQueryResult(None, None, None, {
+                "resolution": "UNSUPPORTED_BY_MODEL",
+                "entries": [{"note": note}],
+            })
+
+        state = self.wafer_state
+        if self._viewing_step_index is not None:
+            return unknown("이력 도핑 상태가 보존되지 않았습니다.")
+        if not isinstance(state, WaferStateV2):
+            return unknown("정확한 canonical 2D 도핑 상태가 없습니다.")
+        present = [c for c in state.cells if c.lifecycle not in ("REMOVED", "CONVERTED")]
+        if any(c.bounds_um is None for c in present):
+            return unknown("소유 재료의 정확한 geometry가 없습니다.")
+        found = [c for c in present if c.bounds_um[0] <= x_um <= c.bounds_um[1]
+                 and c.bounds_um[2] <= y_um <= c.bounds_um[3]]
+        # A display sample is not a DevSim node: do not snap or guess its owner.
+        if len(found) != 1 or found[0].material != material or found[0].lifecycle != "ACTIVE":
+            return unknown("이 표본 좌표와 mesh 재료에 유일한 ACTIVE 소유 cell이 없습니다.")
+        try:
+            result = state.net_doping_at(x_um, y_um, owning_cell=found[0])
+            values = (result.donor_concentration, result.acceptor_concentration, result.net_doping)
+            if result.physics_status is not None or any(v is None or not math.isfinite(v) for v in values):
+                return result if result.physics_status is not None else unknown("유한한 활성 도핑 값이 없습니다.")
+            return result
+        except Exception:
+            return unknown("canonical 도핑 표본 조회에 실패했습니다.")
+
+    def _doping_color_at(self, x_um, y_um, material):
+        """Sign at one mesh-centroid sample; not a concentration contour."""
+        result = self._canvas_doping_query(x_um, y_um, material)
+        if result.physics_status is not None or result.net_doping is None:
+            return _DOPING_UNSUPPORTED_MARKER
+        if result.net_doping == 0.0:
+            return _DOPING_ZERO_MARKER
+        return "#2f6fed" if result.net_doping > 0 else "#e0393e"
+
     def _doping_color_segments(self, region_name, x_min_um, x_max_um, n_buckets=60):
         """(x_lo_um, x_hi_um, color) segments covering [x_min_um,
         x_max_um], reading self.wafer_state.net_doping_at() (Task 2) --
diff --git a/tests/unit/test_gui_depth_doping_mock.py b/tests/unit/test_gui_depth_doping_mock.py
new file mode 100644
index 0000000..b8f47ad
--- /dev/null
+++ b/tests/unit/test_gui_depth_doping_mock.py
@@ -0,0 +1,68 @@
+"""실제 canonical 상태와 추출된 GUI 메서드 대조. 엔진/Tk import 없음."""
+import ast
+import sys
+from pathlib import Path
+from types import SimpleNamespace as S
+ROOT=Path(__file__).resolve().parents[2]
+sys.path.insert(0,str(ROOT))
+def deny(event,args):
+    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals'}:
+        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
+sys.addaudithook(deny)
+from tcad.physics.wafer_state_v2 import initialize_wafer_state,attach_dopant,uniform_inventory_integral
+source=(ROOT/'tcad_2d_stagewise.py').read_text(encoding='utf-8')
+tree=ast.parse(source)
+cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
+names={'_doping_color_segments','_canvas_doping_query','_doping_color_at','_doping_unsupported_hover_note','_on_canvas_motion'}
+ns={'_DOPING_UNSUPPORTED_MARKER':'UNKNOWN','_DOPING_ZERO_MARKER':'ZERO'}
+exec(compile(ast.fix_missing_locations(ast.Module(body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names],type_ignores=[])),'gui_depth','exec'),ns)
+
+def state(chemical='ACTIVE'):
+    s=initialize_wafer_state(cells=[('Si',(-1,1,-2,0),'si')])
+    for polarity,C,bounds,label in [('donor',1e17,(-1,1,-2,0),'ACTIVE'),('acceptor',2e17,(-1,1,-2,-1),chemical)]:
+        s=attach_dopant(s,species=None,polarity=polarity,chemical_state=label,
+            concentration_at=lambda x,y,C=C:C,inventory_integral=uniform_inventory_integral(C),
+            support_instance_id='si',support_region_um=bounds,model='explicit_uniform')
+    return s
+
+def main():
+    app=S(wafer_state=state(),_viewing_step_index=None,viewer_layer_var=S(get=lambda:'doping'))
+    for name,fn in ns.items():
+        if callable(fn) and name in names:
+            setattr(app,name,lambda *args,fn=fn,**kw:fn(app,*args,**kw))
+    if '--before' in sys.argv:
+        segments=app._doping_color_segments('Si',-1,1)
+        assert all(v[2]=='#2f6fed' for v in segments)
+        assert app.wafer_state.net_doping_at(0,-1.5).net_doping==-1e17
+        print('REPRODUCED: lower p region painted n by y=0 lookup; engine imports 0')
+        return
+    assert app._doping_color_at(0,-.5,'Si')=='#2f6fed'
+    assert app._doping_color_at(0,-1.5,'Si')=='#e0393e'
+    assert app._doping_color_at(0,-1.5,'SiO2')=='UNKNOWN'
+    assert app._doping_color_at(0,-3,'Si')=='UNKNOWN'
+    from dataclasses import replace
+    s=app.wafer_state
+    app.wafer_state=replace(s,cells=s.cells+(replace(s.cells[0],cell_id='overlap',material_instance_id='other'),))
+    assert app._doping_color_at(0,-.5,'Si')=='UNKNOWN'
+    for bad in (float('nan'),float('inf'),-1.0):
+        app.wafer_state=replace(s,attachments=(replace(s.attachments[0],concentration_at=lambda x,y,bad=bad:bad),))
+        result=app.wafer_state.net_doping_at(0,-.5)
+        assert result.donor_concentration is result.acceptor_concentration is result.net_doping is None
+        assert result.physics_status['entries'][0]['parameter']=='dopant_concentration_validity'
+        assert app._doping_color_at(0,-.5,'Si')=='UNKNOWN'
+    for chemical in ('CHEMICAL','UNKNOWN'):
+        app.wafer_state=state(chemical)
+        assert app._doping_color_at(0,-.5,'Si')=='#2f6fed'
+        assert app._doping_color_at(0,-1.5,'Si')=='UNKNOWN'
+        assert app._doping_unsupported_hover_note(0,-.5)==''
+        assert 'UNSUPPORTED' in app._doping_unsupported_hover_note(0,-1.5)
+    app.wafer_state=initialize_wafer_state(cells=[('Si',(-1,1,-2,0),'si')])
+    assert app._doping_color_at(0,-1,'Si')=='ZERO'
+    app._viewing_step_index=0
+    assert app._doping_color_at(0,-1,'Si')=='UNKNOWN'
+    assert '이력' in app._doping_unsupported_hover_note(0,-1)
+    motion=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_on_canvas_motion')
+    assert 'self._doping_unsupported_hover_note(x_um, y_um)' in ast.get_source_segment(source,motion)
+    print('PASS: depth-dependent p/n, activation, ownership, true zero, history, mouse y; engine imports 0')
+
+if __name__=='__main__': main()
```
