# E6N-S 완료: 요청 바이어스와 전류 결과의 동일성 검사

## 결론

실제 GUI 2단자 측정은 반환 region/sweep 접점/접점 집합/인가전압이
현재 요청과 일치할 때만 전류·history·field 결과를 보고한다.
잘못된 metadata를 실제 요청의 전류로 붙이는 방어 공백을 닫았다.
엔진이 실제로 wrong voltage를 반환한 사례를 발견했다고 주장하지 않는다.

시작 HEAD 79daa22, tracked clean. PLAN 단독 커밋 53b97d3,
실행 구현 SHA 086911bdb66f99db1b787cacbf8b75055b195410.
Serena 도구 미제공으로 직접 소스·caller 조사했다.

## 수정 전/후 합성 반례

실제 run_measurement의 반환 기록 검증 구문을 AST로 실행했다.

| 반례 | 기존 | 수정 후 |
|---|---|---|
| source voltage 다른 기록 | ACCEPTED | BLOCKED |
| ground voltage 다른 기록 | ACCEPTED | BLOCKED |
| 다른 region | ACCEPTED | BLOCKED |
| 다른 sweep_contact | ACCEPTED | BLOCKED |
| voltage에 추가 접점 | ACCEPTED | BLOCKED |
| current에 추가 접점 | ACCEPTED | BLOCKED |

정상 positive/negative/zero bias 3개 및 음수 current 모두 유지된다.
expected_voltages를 생략하는 기존 다단자 caller 계약은 그대로다.
이상적인 gate voltage에 전류를 발명하지 않는 기존 검사도 유지된다.
로컬 신규 bias/기존 validity/caption/contact/export/hover/capture/readout
8개 국소 unit rc=0, 엔진·Tk import를 trap했다.

## 정확 비교의 이유

비교 대상은 해의 electrostatic Potential이 아니라 Python command 기록이다.
기존 pn_junction_iv_sweep.py와 robust_iv_sweep.py가 요청 sweep voltage 및
fixed_contacts 값을 변환/반올림 없이 BiasPoint.voltages에 복사한다.
그 기록이 요청과 다르면 tolerance로 통과시킬 이유가 없다.
새 수렴 tolerance, 물리 보정, 전위 이동 또는 gate 변경을 만들지 않았다.

## 원격 실제 실행과 통제된 변조

[Actions run 37973819504](https://github.com/tjrgns1753-create/tcad/actions/runs/37973819504),
artifact remote-run-67, 위 구현 SHA의 GitHub-hosted Windows 실행이다.
gui_bias / pure_bias / validity / caption / contacts / export / hover /
snapshot / readout 9개 모두 COMPLETED, rc=0, cleanup_ok=True.

정상 uniform ACTIVE Si +1mV 1회, 이후 wrong_source_voltage 및
wrong_ground_voltage 각각 1회: 실제 시도/성공 3씩, 총 9 solve.
변조는 실제 원래 성공한 계산의 반환 metadata에만 통제해서 주입했다.
소자를 다른 전압으로 다시 계산하거나 원본 증거를 변경하지 않았다.

두 변조 케이스 모두:
- 원래 실제 반환 전압은 Si_xmin=0, Si_xmax=0.001 V.
- 주입된 값은 각각 source=0.002 V 또는 ground=0.1 V.
- 오류 알림 발생, DEVSIM MEASUREMENT 성공 블록 없음.
- history 증가 0, field capture callback 호출 0.
- 필드/보관 결과 None, 화면 solved_field_node 0.
- export dialog 호출 없음, 이미 저장한 정상 파일 바이트 불변.
- 각 측정 끝에 실제 DEVSIM device 목록 빈 상태.

정상 케이스의 export는 R/Q/P 고정 결과 전체와 동일:
SHA 8111c300184eccc680938178e6112fc6e8152e2b4789cc1cdfa79d935df1056f.
73개 실제 노드 좌표·전위·전자·정공, 두 접점 전압·전류·단위·출처
전부 변함없다. 일부 선택 노드만 비교한 것이 아니다.

독립 verify_artifact.py는 입력 18개 git blob, 원시 파일 13개 크기·SHA,
실제 실행 ID/SHA/runner, 모든 상태·cleanup, 두 주입 metadata,
6개 bias 반례 및 8개 contact 반례를 재확인했다. 독립 엔진 import 0회.

## 전체 production semantic diff

```diff
diff --git a/tcad/characterization/interface.py b/tcad/characterization/interface.py
index e87a42b..45ff3b8 100644
--- a/tcad/characterization/interface.py
+++ b/tcad/characterization/interface.py
@@ -103,7 +103,7 @@ class BiasPoint:
     converged: bool = True


-def validate_bias_point(point: BiasPoint, required_contacts=()) -> None:
+def validate_bias_point(point: BiasPoint, required_contacts=(), expected_voltages=None) -> None:
     """Reject invalid terminal evidence, without replacing values or approving physics.

     This is a GUI result-boundary check, not a convergence/charge-conservation
@@ -118,6 +118,13 @@ def validate_bias_point(point: BiasPoint, required_contacts=()) -> None:
     for values in (point.voltages, point.currents):
         if any(not math.isfinite(float(value)) for value in values.values()):
             raise ValueError("Measurement result contains a non-finite value; no current is reported.")
+    if expected_voltages is not None:
+        # Command metadata, not the solved electrostatic Potential: the sweep
+        # producers copy the requested values into BiasPoint without rounding.
+        for contact, voltage in expected_voltages.items():
+            if (contact not in point.voltages or not math.isfinite(float(voltage)) or
+                    float(point.voltages[contact]) != float(voltage)):
+                raise ValueError(f"Measurement voltage record does not match request for {contact!r}.")


 @dataclass
diff --git a/tcad_2d_stagewise.py b/tcad_2d_stagewise.py
index f1f3f1f..c030084 100644
--- a/tcad_2d_stagewise.py
+++ b/tcad_2d_stagewise.py
@@ -5980,7 +5980,12 @@ class TCADApplication(tk.Tk):

             if len(result.points) != 1:
                 raise ValueError("Measurement must return exactly one bias point.")
-            validate_bias_point(result.points[0], (source_contact, gnd_contact))
+            if (result.region != region or result.sweep_contact != source_contact or
+                    set(result.points[0].voltages) != set(imported.contacts) or
+                    set(result.points[0].currents) != set(imported.contacts)):
+                raise ValueError("Measurement result identity does not match the imported two-terminal request.")
+            validate_bias_point(result.points[0], (source_contact, gnd_contact),
+                                expected_voltages={source_contact: voltage, gnd_contact: 0.0})
             from tcad.characterization.node_fields import capture_node_fields
             try:
                 fields = capture_node_fields(module, imported.device, region, length_scale_to_cm)

```

다른 변경은 신규 unit·원격 검사/driver/profile/request 및 감사 자료다.
이 shared GUI gate는 simple/robust 분기가 반환한 다음의 같은 지점에 있다.
실제 원격 방어 검사는 uniform simple 분기이며 robust 물리 결과를 새로 승인하지 않는다.

## 무변경과 한계

기존 원시 증거·PLAN 불변. 새 raw는 원래 바이트 그대로 -text -diff 보존.
물리 식·canonical state·mesh·backend 내부·공정·PN gate·main 불변.
git diff --check rc=0. 전체 회귀 미실행.
현재 요청 바이어스 기록의 일치는 필요조건이지 해의 물리적 타당성 충분조건이 아니다.
다른 소자/새 PN 지원을 이 검사만으로 열지 않는다.

