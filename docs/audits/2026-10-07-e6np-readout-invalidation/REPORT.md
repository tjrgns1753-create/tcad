# E6N-P 마지막 stale 숫자 readout 제거

## 반례와 수정

실제 redraw 메서드의 widget size 조회 이전 prefix만 실행했다(엔진/Tk0).
수정 전 canvas 삭제 후 마지막 node 수치 문자열 유지가 재현됨.
수정 후 coord_var 빈 문자열. 생산 변경은 redraw 초입의 2줄뿐.

## 원격 실제 검증

PLAN 6d7fee5, 실행 source 4190b5e55d7f955937a439a26842a2cdfeb98027.
https://github.com/tjrgns1753-create/tcad/actions/runs/37572007123
artifact remote-run-64. 기존 E6N-O profile/script 재사용해 추가 assertion을 붙임.
export/pure/hover/snapshot/readout/gate_control 6개 COMPLETED/RC0/cleanup true.

기존 uniform ACTIVE DD 3 solve, 73개 actual nodes. 실제 node hover 값을 읽은 뒤
전압 변수 편집만으로 지도와 coord readout 모두 빈 상태. reset은 고의로 복원한
이전 실제 readout 문자열을 추가 mouse event 없이 지웠다. reset 부분은 UI fault
fixture이며 새 물리 현상의 실측이라고 주장하지 않는다.

기존 export/전류 단위/CHEMICAL·UNKNOWN gate 대조군 유지. 새 물리 모델/수렴
기준/gate 변경0, 추가 field solve0, device 누수0. 전체 회귀 미실행.

## 독립 증거 대조

13 source input SHA, raw output/log11파일 byte/hash, 6개 단계, readout flags,
저장 JSON의 73개 전체 배열·bias·unit·source evidence를 재검증 PASS.
원시 자료는 raw/에 정규화 없이 보존. E6N-O의 남은 readout 문제는 이 배치로 해소.

## 이번 연속 구간 전체 상태

E6N-M 실제 노드 복사+점 지도, E6N-N 수치 hover/reset, E6N-O JSON 저장+편집
시 지도 해제, E6N-P 마지막 숫자 해제까지 구현·원격·독립 검증 완료.
모두 현재 지원되는 uniform ACTIVE Si 저항 사례만 실측. PN/MOSFET·모든
메쉬/공정 순서 검증을 새로 승인한 것이 아니다. official API 조회만 사용.

## production diff

```diff
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index 3b0e0bb..f4cc1b6 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -8354,6 +8354,8 @@ class TCADApplication(tk.Tk):
     def redraw(self):

         canvas = self.canvas
+        if hasattr(self, "coord_var"):
+            self.coord_var.set("")

         canvas.delete(
             "all"
```

