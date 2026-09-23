"""Tier 1-1 r4: derive BOTH required reports from the ONE full-audit run
(./full-audit/results.json, baseline's 120 in baseline order + new files
appended -- see run_full_audit.py):

  1. The 120-file baseline COHORT, extracted from the same run (each of
     those 120 ran in its own subprocess with the same env/budget as
     every other round -- interleaving 4 more files afterward changes
     nothing about how each of the 120 itself ran), compared to the
     2026-09-16 baseline's 91 PASS / 29 FAIL -- BASELINE_COHORT_DIFF.md.
  2. The full CURRENT set (baseline's 120 + every file new since then),
     reported on its own -- FULL_CURRENT_DIFF.md -- separating existing
     (baseline-inherited) failures from genuinely NEW ones, and calling
     out any file whose status changed for a reason OTHER than "new
     test" (e.g. test_dopant_profile_matches_devsim_real.py, rewritten
     after the prior round's full audit, so that round's 90/30 number is
     not reused here).

Failure categories use exactly the classifier of
docs/audits/2026-09-16/summarize_audit.py, extended with one more class
this round's own snap/ownership fix can produce (Branch A/B print
format -- never actually a failure signature, but kept for completeness
of the classifier map). Reruns nothing.
"""
import collections
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_DIR = HERE.parent / "2026-09-16/validated-env"
R1_DIR = HERE.parent / "2026-09-17-tier1-1/full-audit"
R2_DIR = HERE.parent / "2026-09-17-tier1-1-r2/full-audit"
NEW_DIR = HERE / "full-audit"


def category(run_dir, row):
    if row["status"] == "PASS":
        return ""
    if row["status"] == "AUDIT_TIMEOUT":
        return "진단 시간 예산 초과"
    content = (run_dir / row["log"]).read_text(encoding="utf-8", errors="replace")
    if "raise UnsupportedDopingState" in content:
        return "v2 미지원 상태로 device mapping 차단"
    if "AttributeError:" in content or "TypeError:" in content:
        return "API/자료형 호환 실패"
    if "StopIteration" in content:
        return "예상한 도핑 profile 부재"
    if "AssertionError" in content:
        return "assertion 불일치"
    return "기타 실행 실패"


def load(run_dir):
    data = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    rows = data["results"] if isinstance(data, dict) else data
    return data, {r["test"].replace("\\", "/"): r for r in rows}


def summary(rows, run_dir):
    units = [r for r in rows if "/unit/" in r["test"].replace("\\", "/")]
    integ = [r for r in rows if r not in units]
    return dict(
        total=len(rows),
        status=dict(collections.Counter(r["status"] for r in rows)),
        unit=dict(collections.Counter(r["status"] for r in units)),
        integration=dict(collections.Counter(r["status"] for r in integ)),
        failure_categories=dict(collections.Counter(
            category(run_dir, r) for r in rows if r["status"] != "PASS")),
    )


def main():
    base_data, base = load(BASE_DIR)
    new_data, new_all = load(NEW_DIR)
    if not new_data["complete"]:
        raise SystemExit(f"r4 audit not finished: {len(new_all)}/{new_data['planned']}")

    baseline_names = list(base)
    new_since_baseline = [t for t in new_all if t not in base]
    assert set(baseline_names) <= set(new_all), (
        f"the full run is missing baseline test(s): {set(baseline_names) - set(new_all)}")

    # ---- Report 1: the 120-file baseline cohort, exactly ----
    cohort = {t: new_all[t] for t in baseline_names}
    assert list(cohort) == baseline_names
    s_base = summary(base_data["results"], BASE_DIR)
    s_cohort = summary(list(cohort.values()), NEW_DIR)

    lines = ["# Tier 1-1 r4 -- 120개 baseline cohort 대비 (2026-09-16)", "",
             f"- baseline: {json.dumps(s_base, ensure_ascii=False)}",
             f"- r4 cohort (같은 120개, 이번 감사에서 추출): {json.dumps(s_cohort, ensure_ascii=False)}", "",
             "## baseline 대비 상태 또는 실패 분류가 바뀐 파일 (120개 중)", "",
             "| 테스트 | baseline | 분류 | r4 | 분류 | 판정 |", "|---|---|---|---|---|---|"]
    changed = 0
    for test in baseline_names:
        b, n = base[test], cohort[test]
        cb, cn = category(BASE_DIR, b), category(NEW_DIR, n)
        if (b["status"], cb) == (n["status"], cn):
            continue
        changed += 1
        if b["status"] == "PASS" and n["status"] != "PASS":
            verdict = "신규 실패"
        elif b["status"] != "PASS" and n["status"] == "PASS":
            verdict = "신규 통과"
        else:
            verdict = "기존 실패 지속(분류 변경)"
        lines.append(f"| {Path(test).name} | {b['status']} | {cb} | {n['status']} | {cn} | {verdict} |")
    if not changed:
        lines.append("| (없음) | | | | | |")
    lines += ["", "## 120개 전체 파일 대조", "",
              "| 테스트 | baseline | r4 | baseline 초 | r4 초 |", "|---|---|---|---:|---:|"]
    for test in baseline_names:
        b, n = base[test], cohort[test]
        lines.append(f"| {Path(test).name} | {b['status']} | {n['status']} | {b['seconds']:.2f} | {n['seconds']:.2f} |")
    (HERE / "BASELINE_COHORT_DIFF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- Report 2: the full current set (120 + new-since-baseline), on its own ----
    s_full = summary(list(new_all.values()), NEW_DIR)
    lines2 = ["# Tier 1-1 r4 -- 전체 현재 테스트 (baseline 120 + 신규)", "",
              f"- 총 {len(new_all)}개 = baseline 120개 + 신규 {len(new_since_baseline)}개",
              f"- 신규 파일: {new_since_baseline}",
              f"- 전체: {json.dumps(s_full, ensure_ascii=False)}", "",
              "## 기존(baseline) 실패 지속", "", "| 테스트 | baseline | r4 | 분류 |", "|---|---|---|---|"]
    existing_fail = new_fail = 0
    for test in baseline_names:
        b, n = base[test], cohort[test]
        if n["status"] != "PASS":
            if b["status"] != "PASS":
                existing_fail += 1
                lines2.append(f"| {Path(test).name} | {b['status']} | {n['status']} | {category(NEW_DIR, n)} |")
    if not existing_fail:
        lines2.append("| (없음) | | | |")
    lines2 += ["", "## baseline에 없던 신규 실패 (120개 중, r4에서 새로 실패)", "",
               "| 테스트 | baseline | r4 | 분류 | 비고 |", "|---|---|---|---|---|"]
    for test in baseline_names:
        b, n = base[test], cohort[test]
        if n["status"] != "PASS" and b["status"] == "PASS":
            new_fail += 1
            note = ("rewritten after the prior round's own full audit -- "
                    "that round's 90/30 number is not reused as this round's baseline"
                    if Path(test).name == "test_dopant_profile_matches_devsim_real.py" else "")
            lines2.append(f"| {Path(test).name} | {b['status']} | {n['status']} | {category(NEW_DIR, n)} | {note} |")
    if not new_fail:
        lines2.append("| (없음) | | | | |")
    lines2 += ["", f"## 신규 테스트 파일 ({len(new_since_baseline)}개, baseline 목록에 없음)", "",
               "| 테스트 | 상태 | 초 |", "|---|---|---:|"]
    for test in new_since_baseline:
        n = new_all[test]
        lines2.append(f"| {Path(test).name} | {n['status']} | {n['seconds']:.2f} |")
    (HERE / "FULL_CURRENT_DIFF.md").write_text("\n".join(lines2) + "\n", encoding="utf-8")

    print(json.dumps(dict(
        baseline=s_base, r4_cohort_120=s_cohort, r4_full=s_full,
        cohort_changed_files=changed, existing_failures_in_120=existing_fail,
        new_failures_in_120=new_fail, new_files=new_since_baseline,
    ), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
