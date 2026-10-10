"""고정된 GUI 계약 migration과 대조군 4개. 실제 엔진은 원격에서만."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PLAN_SHA = "e56c4eb99142e01a2aea347bc2cb0ed98961c913f2059531f2e3994cf8e5b935"
BASELINE = "e1c0c025d955540251e00a8f295db836044e61f7"
TESTS = (
    "tests/integration/test_gui_doping_donor_acceptor_real.py",
    "tests/integration/test_measurement_canonical_state_gate_real.py",
    "tests/integration/test_gui_headless_no_modal_hang_real.py",
    "tests/unit/test_doping_staleness_mock.py",
)


def preflight():
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise RuntimeError("REMOTE_ONLY")
    if hashlib.sha256((HERE/"PLAN.md").read_bytes().replace(b"\r\n",b"\n")).hexdigest() != PLAN_SHA:
        raise ValueError("PLAN_HASH_MISMATCH_BEFORE_ENGINE_IMPORT")
    if subprocess.run(["git","diff","--exit-code",BASELINE,"HEAD","--","tcad","tcad_2d_stagewise.py"],
                      cwd=ROOT, stdout=subprocess.DEVNULL).returncode:
        raise ValueError("PRODUCTION_OR_GATE_CHANGED")
    for path in TESTS:
        ast.parse((ROOT/path).read_text(encoding="utf-8"), filename=path)


def judge_gui(m):
    expected = {"compensated","n","p","gaussian","windows","barrier_x","barrier_y"}
    assert set(m) == expected, ("missing/extra GUI cases",set(m))
    for name in ("n","p"):
        r=m[name]
        assert r["solve_calls"]>=1 and r["doping_writes"]>=1 and r["reattach_identity"]
        assert r["attachment_count"] == 1 and r["canonical_state_object_unchanged"]
        c=r["currents_in_log"][:2]
        assert len(c)==2 and abs(c[0])>0 and abs(c[0]+c[1])<=1e-4*abs(c[0])
        assert r["canonical_vs_solved_netdoping"]["mismatched_nodes"]==0
        assert not r["unsupported_in_log"] and r["measurement_section_logged"]
    for name in expected-{"n","p"}:
        r=m[name]
        assert r["solve_calls"]==r["doping_writes"]==r["history_entries_added"]==0
        assert not r["currents_in_log"] and r["unsupported_in_log"]
        assert r["last_physics_status"]["resolution"]=="UNSUPPORTED_BY_MODEL"
    assert m["compensated"]["last_physics_status"]["reason_code"]=="COMPENSATED_TRANSPORT_MODEL_MISSING"
    for name in ("gaussian","windows"):
        assert m[name]["last_physics_status"]["reason_code"]=="DOPANT_ACTIVATION_MODEL_MISSING"
        assert m[name]["new_attachments"]
        assert all(a["chemical_state"]=="CHEMICAL" for a in m[name]["new_attachments"])
    for name in ("barrier_x","barrier_y"):
        assert m[name]["detector_axis"]=="x" and m[name]["input_provenance"]=="DIRECT_EXPLICIT_GEOMETRY"
        assert m[name]["barrier_windows"]
    return {"pass":True,"cases":7,"scope":"GUI_CONTRACTS_NOT_GENERAL_PHYSICS_APPROVAL"}


def main():
    preflight()
    sys.path.insert(0,str(ROOT/"docs/audits/2026-10-02-e6na-import-reduction"))
    sys.path.insert(0,str(ROOT/"remote"))
    from resource_supervisor import supervise
    from run_profile import Sanitizer
    out=ROOT/"e6nad_out"
    out.mkdir(exist_ok=True)
    records={}
    sanitizer=Sanitizer()
    gui_verdict={"pass":False,"reason":"NOT_RECORDED"}
    for i,path in enumerate(TESTS):
        log=out/(Path(path).stem+".log")
        r=supervise([sys.executable,"-B",path],ROOT,log,candidate_s=180)
        text=log.read_text(encoding="utf-8",errors="replace")
        text=sanitizer.clean(text)
        log.write_text(text,encoding="utf-8",newline="\n")
        r.update(input_lf_sha256=hashlib.sha256((ROOT/path).read_bytes().replace(b"\r\n",b"\n")).hexdigest(),
                 log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),log_file=log.name,
                 skip_detected=("SKIPPED:" in text or "SKIP:" in text))
        records[path]=r
        (out/"records.json").write_text(json.dumps(records,indent=2),encoding="utf-8")
        print(json.dumps({"file":path,"status":r["status"],"rc":r.get("exit_code")}),flush=True)
        if i==0 and r.get("exit_code")==0:
            lines=[line[len("METRICS "):] for line in text.splitlines() if line.startswith("METRICS ")]
            if len(lines)!=1:
                gui_verdict={"pass":False,"reason":"GUI_METRICS_MISSING_OR_DUPLICATED"}
            else:
                m=json.loads(lines[0])
                (out/"gui_metrics.json").write_text(json.dumps(m,indent=2),encoding="utf-8")
                try:
                    gui_verdict=judge_gui(m)
                except Exception as exc:
                    gui_verdict={"pass":False,"reason":repr(exc)}
    passed=len(records)==4 and all(r["status"]=="COMPLETED" and r.get("exit_code")==0
                and r["cleanup_ok"] and not r["skip_detected"] for r in records.values()) and gui_verdict["pass"]
    verdict={"pass":passed,"expected_files":4,"recorded_files":len(records),"gui":gui_verdict,
             "production_unchanged":True,"plan_sha":PLAN_SHA}
    (out/"verdict.json").write_text(json.dumps(verdict,indent=2),encoding="utf-8")
    print(json.dumps(verdict),flush=True)
    return 0 if passed else 1


if __name__=="__main__":
    raise SystemExit(main())
