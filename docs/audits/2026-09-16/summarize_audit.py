"""Generate an evidence index from completed audit results (no test reruns)."""
import collections
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
data=json.loads((HERE/"validated-env/results.json").read_text(encoding="utf-8"))
if not data["complete"]:
    raise SystemExit(f"Audit not finished: {len(data['results'])}/{data['planned']}")

rows=data["results"]
counts=collections.Counter(r["status"] for r in rows)
units=[r for r in rows if "unit" in Path(r["test"]).parts]
integration=[r for r in rows if r not in units]
lines=["# 실행 결과 인덱스 — 2026-09-16", "",
       f"기존 테스트 파일 {len(rows)}개 실행 시도 완료: {dict(counts)}.",
       f"Unit {len(units)}개: {dict(collections.Counter(r['status'] for r in units))}.",
       f"Integration {len(integration)}개: {dict(collections.Counter(r['status'] for r in integration))}.", "",
       "전체 결과는 `validated-env/results.json`, 상세 물리 판정은 [REPORT.md](REPORT.md).",
       "Unit 60초/integration 180초 제한 감사이며 정식 회귀의 장기 timeout 예산과 다르다.",
       "파일이 일찍 실패한 경우 뒤쪽 시나리오는 미실행이다. 아래 분류는 이번 로그의 실패 지점 분류이며 baseline 대비 회귀 판정은 아니다.", "",
       "| 테스트 | 결과 | 초 | 로그상 실패 유형 |", "|---|---|---:|---|"]
failure_groups=collections.Counter()
for r in rows:
    label=""
    if r["status"]!="PASS":
        content=(HERE/"validated-env"/r["log"]).read_text(encoding="utf-8",errors="replace")
        if r["status"]=="AUDIT_TIMEOUT":
            label="진단 시간 예산 초과; 물리 실패 판정 아님"
        elif "raise UnsupportedDopingState" in content:
            label="v2 미지원 상태로 device mapping 차단"
        elif "AttributeError:" in content or "TypeError:" in content:
            label="API/자료형 호환 실패"
        elif "StopIteration" in content:
            label="예상한 도핑 profile 부재"
        elif "AssertionError" in content:
            label="assertion 불일치; 보고서와 로그 확인"
        else:
            label="기타 실행 실패; 로그 확인"
        failure_groups[label]+=1
    name=Path(r["test"]).name
    lines.append(f"| [{name}](validated-env/{r['log']}) | {r['status']} | {r['seconds']:.2f} | {label} |")
lines.extend(["", "## 실패 지점 분류", ""])
lines.extend(f"- {k}: {v}개" for k,v in failure_groups.items())
lines.extend(["", "## 별도 반례와 실제 물리 benchmark", "",
    "- [상태 전달 반례 수치](counterexample_state.json): 6개 주요 결함 + 보조 조회",
    "- [실제 ViennaPS 산화](counterexample_oxidation.json): 3 grids × 2 durations",
    "- [실제 GUI/DevSim 미지원 상태 우회](counterexample_gui.json)",
    "- [실제 PN 3-grid 결과](counterexample_diode.json)",
    "", "초기 DLL 경로 오류로 중단한 상위 폴더 로그는 집계에서 제외했다.", ""])
(HERE/"RESULTS.md").write_text("\n".join(lines),encoding="utf-8")
print(json.dumps(dict(total=len(rows),counts=dict(counts),unit=dict(collections.Counter(r['status'] for r in units)),
    integration=dict(collections.Counter(r['status'] for r in integration)),failure_groups=dict(failure_groups)),ensure_ascii=False,indent=2))
