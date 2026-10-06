# E6N-H: 현재 웨이퍼 형상 표시의 fail-closed 계약

## 결론 및 물리적 의미

이 작업은 새 공정 모델이나 PN gate 해제가 아니라, **계산 결과가 없는데 GUI가
그럴듯한 형상을 만들어 보여주는 경로를 제거**하는 작업이다.
실제 mesh, 입력 도식, 과거 이력, 미지원 상태를 구분한다.
형상 표시 성공을 소자 물리 검증 성공으로 간주하지 않는다.

Si가 식각된 실제 형상 파일을 잃어버렸다고 해서 평평한 Si로 복구되지는 않는다.
식각 깊이는 계산된 mesh에서 읽어야 하며 cycles 값에 임의 픽셀 상수를 곱해서
ViennaPS 결과라고 부를 수 없다. 이는 물리 법칙을 새로 근사하는 문제가 아니라
측정·계산된 상태와 사용자에게 보여주는 상태의 동일성을 보장하는 문제다.

## 사전 고정 및 실행 위치

- 시작 SHA d0dc7c27756fefe77416f341d8f6aad5d6ef2e96.
- PLAN 단독 커밋 55689e2. 조사 및 합성/AST 검사는 로컬, 실제 Tk/ViennaPS/DEVSIM은 원격.
- production 공정·상태 전달·소자 방정식·기존 gate는 변경하지 않았다.
- 전체 회귀, main 병합, 엔진 내부 변경, 수치 허용오차 완화는 하지 않았다.

## 수정 전 확인된 반례와 수정

| 입력/상태 | 수정 전 | 수정 후 계약 |
|---|---|---|
| 공정 후 mesh 파일 누락 | 평평한 Si 사각형을 표시 | 형상 표시 차단, 물리 도형 0개 |
| 파일은 있으나 volume triangle 없음 | 정상 Si로 대체 | 형상 표시 차단, 물리 도형 0개 |
| VTU 형식 손상 | meshio SystemExit가 GUI 호출 경계를 탈출 | mesh 읽기 경계에서만 포착, GUI 유지 및 표시 차단 |
| 실제 mesh 존재, processed=False | 입력 도식으로 대체 가능 | processed와 독립적으로 실제 파일 표시 |
| 미지원 canonical/활성화 상태 | 로그/hover에 의존 | canvas에도 미지원 상태 포함 명시 |
| 과거 이력 선택 | 현재 상태와 혼동 위험 | 이력 mesh, 현재 웨이퍼/전기 검증 아님 명시 |
| 아직 공정 결과가 없는 새 웨이퍼 | 도식을 결과로 오해 가능 | 입력 도식, 계산 결과 아님 명시 |

기존 `visual_depth=min(...,80+cycles*10)` 및 `VIENNAPS RESULT` 대체 도식을 삭제했다.
잘못된 이력 index 역시 현재 mesh로 조용히 대체하지 않고 표시를 차단한다.
오류 시 cursor 좌표 변환도 None으로 초기화하여 이전 형상의 좌표를 표시하지 않는다.
미지원 안내는 현재 cells/attachments/ledger 및 현재 physics status만 읽는다.
과거 사건 목록만으로 전체 현재 상태의 미지 여부를 판정하지 않는다.
이 안내는 solver gate를 새로 추가하거나 해제하지 않는다.

## 실제 실행에서 추가 발견한 표시 정밀도 문제

run 37459241120의 bbox.json:

- 실제 Si 최소 y = -5.0 µm.
- canvas 역변환 최소 y = -4.999999046325684 µm.
- 차이 = 9.53674316e-7 µm, 고정 기준 1e-7 µm 초과.

Si 소속 삼각형 vertex로 비교 범위를 수정해도 차이가 남았으므로, 참조 범위 오류만은 아니었다.
float32 mesh 좌표에서 픽셀 변환 산술이 float32로 진행되는 것을 고쳤다.
원본 mesh 값은 그대로 두고 xs/ys 및 to_canvas()에서 Python float로 승격한다.
메쉬 이동·보간·반올림·허용오차 확대는 없다.
동일 변환 함수의 float32 입력 역변환도 AST 순수 테스트에 추가했다.

## Serena investigation / 직접 코드 조사

Serena 도구가 세션에 제공되지 않아 연결을 시도하거나 성공했다고 주장하지 않았다.
rg 및 직접 파일 읽기로 다음을 확인했다.

- `_draw_real_mesh_result()`의 실제 production 호출은 redraw()다.
- redraw()는 공정 완료, lithography UI, 새 웨이퍼 reset, timeline 및 Configure 경로에서 호출된다.
- `_view_flow_step()`은 표시 mesh만 선택하고 현재 last_final_mesh는 바꾸지 않는다.
- `run_oxidation()`의 미지원 결과는 실제 last-known mesh와 fail-closed canonical state를 전달한다.
- `_on_canvas_motion()`은 `_viewer_scale=None`일 때 좌표를 표시하지 않는다.
- 관련 테스트: 기존 litho placeholder/lifecycle, GUI 단위, canonical measurement gate.
- 과거 investigation 로그에도 fallback 사각형이 기록되어 있었지만 현재 물리 표시 원칙에 부합하지 않는다.

변경 심볼:

- `_draw_real_mesh_result()`: 읽기 실패 의미 정정, 제한된 SystemExit 처리, 픽셀 변환 정밀도.
- `_canvas_state_note()`: 출처/미지원 상태 안내만 생성.
- `_draw_canvas_unavailable()`: 기존 canvas 및 stale 좌표를 제거하고 오류만 표시.
- `redraw()`: 실제 파일을 기준으로 선택, 임의 형상 fallback 제거, 출처 표시.
- `reset()`: 과거 `_viewing_step_index`를 제거하여 새 입력 도식과 이력을 혼동하지 않는다.

공정 선택/버튼 활성화, canonical query, solve 호출 규칙은 그대로다.

## 검증 이력과 실패를 숨기지 않는 기록

1. run 37458459891: 최초 수정 전 조사. 파일 누락 반례를 통과한 후 손상 파일에서
   meshio SystemExit로 종료했다. 조사 실패를 PASS로 바꾸지 않았다.
2. run 37458931442: 고정 과거 source 4316c3f를 메모리에서 읽어 전후 반례를 비교.
   수정 전 반례는 통과했고 수정 후 실제 canvas bbox에서 실패했다.
3. run 37459241120: Si triangle-owned vertex 기준으로 정정, 같은 bbox 차이로 실패.
   원시 수치를 bbox.json에 기록했다.
4. run 37459543344: double precision 표시 수정 후 좌표 기준은 통과했으나,
   reset 후 과거 이력 index가 남아 입력 도식 대신 오류가 표시되는 반례로 실패했다.
5. run 37459938706: reset 보완 후 동일 기준의 6개 대상 검사가 모두 통과했다.

모든 실패에서 물리 방정식이나 gate를 바꾸지 않았다.
기존 GUI 2D 균일 ACTIVE 측정 대조군과 CHEMICAL/UNKNOWN 차단을 별도로 유지한다.
실제 mesh와 canvas의 재료별 bbox를 대조하는 것은 이 virgin Si 형상에 대한 표시 검증이다.
비평면 undercut·다중 재료·리소그래피 입력 overlay 전체의 정확성을 새로 검증한 것은 아니다.

## Change diff

전체 production 및 신규 unit 테스트 diff는 CHANGE.patch에 보존한다.
파일 SHA-256: `f490cc857e431d62733b5b50146298d2d8ceb5a5c312e475953cd81df1f537fa`.
새 원격 실행기와 반례 프로그램도 별도 원본으로 보존한다.
특히 PR/마스크 세션 입력 도식은 기존대로 존재하며, 실제 수치 공정 결과와 동일하다고
이번 변경으로 승인하지 않는다. 물리 기능 완료나 모든 경우의 타당성 보증으로 과장하지 않는다.

## 최종 원격 결과 및 독립 재검사

- [최종 원격 실행](https://github.com/tjrgns1753-create/tcad/actions/runs/37459938706)
- 실행 SHA: `7bfc27e35952c729f7293398034dc20b54311934`.
- GitHub-hosted Windows, Python 3.11.9, ViennaPS 4.6.2, DEVSIM 2.11.0.
- 대상 실행 구간: 2026-10-06 11:58:46–11:58:56 UTC, 10.299초(환경 설치 시간 제외).
- 원시 파일은 `raw/`에 그대로 보존했다. 실패 49/50/51의 원시 결과도 별도 폴더에 유지한다.
- `verify_artifact.py`는 실행 SHA 전체와 run ID, 11개 출력 및 run.log의 길이·SHA-256을
  검사하고 원시 before/after 반례와 bbox 수치를 다시 대조한다. 엔진 import 0회로 통과했다.
- 최종 표시 bbox 최대 오차: `8.881784197001252e-16 µm`, 기준 `1e-7 µm` 유지.
- 신규 canvas 검사 sampled process-tree working-set 최대 164,421,632 bytes.
  이는 0.5초 간격 표본 합계이며 절대 최대 메모리라고 주장하지 않는다.

| 대상 | 종료 코드 | 검증 범위 |
|---|---:|---|
| before | 0 | 고정된 수정 전 코드에서 임의 Si 대체와 SystemExit 재현 |
| canvas | 0 | 실제 Tk·virgin Si export, bbox, 미지원 last-known, 이력 및 reset |
| source_mock | 0 | 출처·활성화 안내 9개 상태, 정적 계약, float32 입력 좌표 역변환 |
| canonical_gate | 0 | 기존 측정 gate 대조군 |
| existing_gui | 0 | 기존 2D 균일 ACTIVE 전류 단위·실제 DD, CHEMICAL/UNKNOWN 차단 |
| pn_reference | 0 | 기존 별도 1D 기준 보기 계약 |

각 자식 실행은 COMPLETED·cleanup_ok=True다. 기존 GUI 대조군은 최종 실행에서
직접 DD 3회와 GUI DD 3회를 수행했다. 원격 실행기에 기록된 engine_info의
NOT_IMPORTED는 부모의 버전 조회를 생략했다는 뜻이며 자식 검사에 엔진이 없다는 뜻이 아니다.
현재 positive-time 산화는 기존 계약대로 solver 없이 차단되며 그 전의 형상만 유지했다.

`tcad/`의 공정·소자·canonical 물리 코드 diff는 시작 SHA 대비 0이다.
GUI와 신규 unit 테스트의 의미 있는 변경만 아래에 공개한다.
전체 회귀·main 병합·gate 해제는 하지 않았다. 개인 이름·개인 작업 경로·토큰 패턴
스캔은 보존 JSON/log에서 0건이며 익명 GitHub runner 경로는 원시 로그에 남아 있다.
보고서 이후 증거 커밋은 원격 solve를 다시 시작하지 않는다.

이번 검사는 실제 Tk canvas 명령과 좌표의 대조이며 사용자 노트북 화면을 클릭하거나
스크린샷의 모든 시각 요소를 독립 검증한 것은 아니다. 비평면·다중 재료의 내부 렌더링,
모든 공정 순서의 상태 전달 및 일반 PN 2D 수렴은 여전히 별도 검증 대상이다.
## 전체 GUI 및 unit 의미 변경 diff

```diff
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index 38e00d8..4834124 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -7761,9 +7761,9 @@ class TCADApplication(tk.Tk):
         """Draw a real ViennaPS mesh (.vtu volume mesh) instead of the
         placeholder rectangle in redraw(). Returns True on success;
         False if the mesh can't be read (meshio/ViennaPS unavailable,
-        file missing, no triangle cells, degenerate bounds, etc.), so
-        the caller falls back to the placeholder in that case -- this
-        must never raise.
+        file missing, no triangle cells, degenerate bounds, etc.). The
+        caller reports unavailable geometry instead of inventing a
+        replacement substrate. This must never raise.
 
         mesh_path : which mesh to draw. Defaults to self.last_final_mesh
         (the real current wafer) when None -- every existing caller
@@ -7805,7 +7805,11 @@ class TCADApplication(tk.Tk):
                 return False
             module = viennaps_session.require_viennaps()
 
-            mesh = meshio.read(mesh_path)
+            try:
+                mesh = meshio.read(mesh_path)
+            except SystemExit:
+                # meshio's invalid-format path calls sys.exit; it must not close Tk.
+                return False
             triangle_block = next((c for c in mesh.cells if c.type == "triangle"), None)
             if triangle_block is None or "Material" not in mesh.cell_data:
                 return False
@@ -7814,8 +7818,9 @@ class TCADApplication(tk.Tk):
             triangle_data = triangle_block.data
 
             points = mesh.points
-            xs = [p[0] for p in points]
-            ys = [p[1] for p in points]
+            # Preserve mesh values, but use double precision for pixel transforms.
+            xs = [float(p[0]) for p in points]
+            ys = [float(p[1]) for p in points]
             x_min, x_max = min(xs), max(xs)
             y_min, y_max = min(ys), max(ys)
             if (x_max - x_min) < 1e-9 or (x1 - x0) <= 0:
@@ -7862,7 +7867,7 @@ class TCADApplication(tk.Tk):
             material_names = {}
 
             def to_canvas(node_idx):
-                px, py = points[node_idx][0], points[node_idx][1]
+                px, py = float(points[node_idx][0]), float(points[node_idx][1])
                 return x0 + (px - x_min) * x_scale, surface_y - py * y_scale
 
             by_material = {}
@@ -8220,6 +8225,31 @@ class TCADApplication(tk.Tk):
 
         self.redraw()
 
+    def _canvas_state_note(self):
+        """Disclosure only; never grants a device-physics capability."""
+        if self._viewing_step_index is not None:
+            return "이력 mesh — 현재 웨이퍼 또는 해당 시점의 전기적 검증 결과가 아닙니다."
+        state = self.wafer_state
+        unresolved = (
+            any(c.lifecycle in ("UNRESOLVED", "LEGACY_UNRESOLVED") for c in getattr(state, "cells", ()))
+            or bool(getattr(state, "unresolved_inventory", ()))
+            or any(a.chemical_state != "ACTIVE" for a in getattr(state, "attachments", ()))
+            or (isinstance(self.last_physics_status, dict)
+                and self.last_physics_status.get("resolution") == "UNSUPPORTED_BY_MODEL")
+        )
+        if unresolved:
+            return "미지원 상태 포함 (UNSUPPORTED_BY_MODEL) — 표시 형상만으로 공정 후 물리 상태를 보증하지 않습니다."
+        return "실제 mesh — 형상 데이터 표시이며, 소자 물리 검증 승인은 별도입니다."
+
+    def _draw_canvas_unavailable(self, canvas, x0, width, reason):
+        canvas.delete("all")
+        self._viewer_scale = None
+        canvas.create_text(
+            x0, 70, anchor="nw", width=max(100, width - 140),
+            text="형상 표시 차단 — " + reason + "\n계산된 형상 대신 임의 Si/식각 도식을 표시하지 않습니다.",
+            fill="#b42318", font=(Tokens.FONT_UI, 11, "bold"),
+        )
+
     def redraw(self):
 
         canvas = self.canvas
@@ -8227,6 +8257,7 @@ class TCADApplication(tk.Tk):
         canvas.delete(
             "all"
         )
+        self._viewer_scale = None
 
         width = max(
             canvas.winfo_width(),
@@ -8277,7 +8308,10 @@ class TCADApplication(tk.Tk):
         # (what doping/measurement actually operate on) is untouched
         # either way.
         display_mesh = self.last_final_mesh
-        if self._viewing_step_index is not None and 0 <= self._viewing_step_index < len(self.flow_step_meshes):
+        if self._viewing_step_index is not None:
+            if not 0 <= self._viewing_step_index < len(self.flow_step_meshes):
+                self._draw_canvas_unavailable(canvas, x0, width, "선택한 이력 mesh가 없습니다.")
+                return
             display_mesh = self.flow_step_meshes[self._viewing_step_index]
 
         # Whether a REAL PHYSICAL mesh exists to draw -- mesh existence
@@ -8289,13 +8323,19 @@ class TCADApplication(tk.Tk):
         # even though nothing was actually lost. Litho-stage visuals
         # (PR film / mask box / UV rays) are drawn independently, below,
         # positioned on top of whatever real_mesh_available finds here.
-        real_mesh_available = bool(
-            self.wafer.processed
-            and display_mesh
-            and Path(display_mesh).exists()
-        )
+        mesh_expected = bool(display_mesh or self.wafer.processed or self.wafer.etched
+                             or self._viewing_step_index is not None)
+        real_mesh_available = bool(display_mesh and Path(display_mesh).is_file())
+        if mesh_expected and not real_mesh_available:
+            self._draw_canvas_unavailable(canvas, x0, width, "공정/이력 mesh 파일을 찾을 수 없습니다.")
+            return
 
         if not real_mesh_available:
+            canvas.create_text(
+                x0, 55, anchor="nw", width=width - 140,
+                text="입력 도식 — 계산된 공정 형상이나 물리 검증 결과가 아닙니다.",
+                fill=Tokens.FG_DIM, font=(Tokens.FONT_UI, 9),
+            )
             canvas.create_rectangle(
                 x0,
                 surface_y,
@@ -8551,80 +8591,16 @@ class TCADApplication(tk.Tk):
                     fill="#155ea8",
                 )
 
-        # Prefer drawing the actual ViennaPS mesh (real geometry, e.g.
-        # isotropic undercut) when one is available from the last
-        # successful run_etch(). Falls back to the placeholder rectangle
-        # below only if that fails (older project state, meshio missing,
-        # etc.) -- the placeholder never pretended to be the numerical
-        # ViennaPS surface, so this is a strict improvement, not a
-        # behavior change for the case it can't apply to.
+        # A failed physical-mesh render must never turn into invented geometry.
         if real_mesh_available:
             if not self._draw_real_mesh_result(canvas, x0, x1, surface_y, bottom_y,
                                                 mesh_path=display_mesh):
-                # real_mesh_available said a mesh file exists, but
-                # reading/rendering it failed anyway (meshio missing,
-                # corrupt file, ViennaPS unavailable, etc.). The flat
-                # rectangle was skipped earlier trusting this call to
-                # succeed -- draw it now as a last-resort fallback so
-                # the canvas isn't left blank.
-                canvas.create_rectangle(
-                    x0, surface_y, x1, bottom_y,
-                    fill="#bdbdbd", outline="#555",
-                )
-                canvas.create_text(
-                    x0 + 10, bottom_y - 20,
-                    text="Si substrate", anchor="w",
-                )
-
-        elif self.wafer.etched:
-
-            scale = (
-                x1 - x0
-            ) / self.wafer.width_um
-
-            opening_x0 = (
-                x0
-                + self.wafer.mask_left_um
-                * scale
-            )
-
-            opening_x1 = (
-                x0
-                + self.wafer.mask_right_um
-                * scale
-            )
-
-            try:
-                cycles = int(
-                    float(
-                        self.cycles_var.get()
-                    )
-                )
-            except Exception:
-                cycles = 1
-
-            visual_depth = min(
-                bottom_y - surface_y - 10,
-                80 + cycles * 10,
-            )
-
-            canvas.create_rectangle(
-                opening_x0,
-                surface_y,
-                opening_x1,
-                surface_y + visual_depth,
-                fill="white",
-                outline="#444",
-            )
-
+                self._draw_canvas_unavailable(canvas, x0, width, "mesh를 읽거나 렌더링할 수 없습니다.")
+                return
             canvas.create_text(
-                (opening_x0 + opening_x1) / 2,
-                surface_y + visual_depth / 2,
-                text=(
-                    "VIENNAPS\n"
-                    "RESULT"
-                ),
-                justify="center",
+                x0, 55, anchor="nw", width=width - 140,
+                text=self._canvas_state_note(), fill=Tokens.FG_DIM,
+                font=(Tokens.FONT_UI, 9),
             )
 
         # Current PR/mask, drawn as real solid material -- on top of the
@@ -8995,6 +8971,7 @@ class TCADApplication(tk.Tk):
         self.last_doped_result = None
         self.wafer_state = None
         self.last_final_mesh = None
+        self._viewing_step_index = None
         self._viewer_depth_budget_um = {}
         self.history = []
         self.process_stage = "wafer"
diff --git a/tests/unit/test_gui_canvas_source_contract_mock.py b/tests/unit/test_gui_canvas_source_contract_mock.py
new file mode 100644
index 0000000..1c9cb60
--- /dev/null
+++ b/tests/unit/test_gui_canvas_source_contract_mock.py
@@ -0,0 +1,45 @@
+"""AST로 표시 안내만 실행한다. Tk/engine import 없이 계약을 검사한다."""
+import ast
+from pathlib import Path
+from types import SimpleNamespace as S
+import sys
+
+def no_engine(event,args):
+    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals'}:
+        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
+sys.addaudithook(no_engine)
+source=(Path(__file__).resolve().parents[2]/'tcad_2d_stagewise.py').read_text(encoding='utf-8')
+tree=ast.parse(source)
+cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='TCADApplication')
+note=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_canvas_state_note')
+ns={}
+exec(compile(ast.fix_missing_locations(ast.Module(body=[note],type_ignores=[])),'canvas_note','exec'),ns)
+def check(state,physics=None,view=None):
+    return ns['_canvas_state_note'](S(wafer_state=state,last_physics_status=physics,_viewing_step_index=view))
+known=S(cells=[S(lifecycle='ACTIVE')],attachments=[S(chemical_state='ACTIVE')],unresolved_inventory=[])
+assert '실제 mesh' in check(known)
+assert '별도' in check(known)
+for state in (S(cells=[S(lifecycle='UNRESOLVED')]),S(cells=[S(lifecycle='LEGACY_UNRESOLVED')]),
+              S(unresolved_inventory=[object()]),S(attachments=[S(chemical_state='CHEMICAL')]),
+              S(attachments=[S(chemical_state='UNKNOWN')])):
+    assert 'UNSUPPORTED_BY_MODEL' in check(state)
+assert 'UNSUPPORTED_BY_MODEL' in check(known,{'resolution':'UNSUPPORTED_BY_MODEL'})
+assert '이력 mesh' in check(known,view=0)
+redraw=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='redraw')
+text=ast.get_source_segment(source,redraw)
+assert 'visual_depth' not in text and 'VIENNAPS\\n' not in text
+assert 'self.wafer.processed\n            and display_mesh' not in text
+assert 'mesh_expected and not real_mesh_available' in text
+reset=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='reset')
+assert 'self._viewing_step_index = None' in ast.get_source_segment(source,reset)
+import numpy as np
+draw=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_draw_real_mesh_result')
+transform=next(n for n in ast.walk(draw) if isinstance(n,ast.FunctionDef) and n.name=='to_canvas')
+points=np.array([[-5.,-5.],[5.,0.]],dtype=np.float32)
+scope={'points':points,'x0':70.,'x_min':-5.,'x_scale':56.,'surface_y':297.6,'y_scale':37.4}
+exec(compile(ast.fix_missing_locations(ast.Module(body=[transform],type_ignores=[])),'canvas_transform','exec'),scope)
+for i in range(2):
+    cx,cy=scope['to_canvas'](i)
+    assert abs((cx-70.)/56.-5.-float(points[i,0]))<1e-12
+    assert abs((297.6-cy)/37.4-float(points[i,1]))<1e-12
+print('PASS: 9 disclosure states, invented etch removed, source gating; engine imports 0')
```
