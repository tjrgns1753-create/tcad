"""Bounded remote verification: geometry, actual GUI and unchanged controls."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
PLAN_SHA="f881d3d5af17363f1c4ed4418e9d545de3ee196ea61053d1c67296b697e86b8a"
AUDIT="docs/audits/2026-10-10-e6naf-barrier-sections/"
FILES=["tests/unit/test_barrier_sections_mock.py",AUDIT+"compare_saved.py",AUDIT+"probe.py",
       AUDIT+"gui_failure.py","tests/integration/test_gui_doping_donor_acceptor_real.py",
       "tests/integration/test_measurement_canonical_state_gate_real.py",
       "tests/integration/test_gui_headless_no_modal_hang_real.py","tests/unit/test_doping_staleness_mock.py"]


def main():
    assert os.environ.get("RUNNER_ENVIRONMENT")=="github-hosted", "REMOTE_ONLY"
    assert hashlib.sha256((HERE/"PLAN.md").read_bytes().replace(b"\r\n",b"\n")).hexdigest()==PLAN_SHA
    changed=subprocess.check_output(["git","diff","--name-only","6615d28","HEAD","--","tcad","tcad_2d_stagewise.py"],cwd=ROOT,text=True).splitlines()
    assert set(changed)=={"tcad/mesh/barrier_sections.py","tcad/device/devsim/mesh_import.py","tcad_2d_stagewise.py"},changed
    sys.path.insert(0,str(ROOT/"docs/audits/2026-10-02-e6na-import-reduction"))
    sys.path.insert(0,str(ROOT/"remote"))
    from resource_supervisor import supervise
    from run_profile import Sanitizer
    out=ROOT/"e6naf_out";out.mkdir(exist_ok=True)
    records={};sanitizer=Sanitizer()
    for path in FILES:
        log=out/(Path(path).stem+".log")
        r=supervise([sys.executable,"-B",path],ROOT,log,candidate_s=120)
        text=sanitizer.clean(log.read_text(encoding="utf-8",errors="replace"))
        log.write_text(text,encoding="utf-8",newline="\n")
        r.update(skip_detected=("SKIPPED:" in text or "SKIP:" in text),
                 input_lf_sha=hashlib.sha256((ROOT/path).read_bytes().replace(b"\r\n",b"\n")).hexdigest())
        records[path]=r
        (out/"records.json").write_text(json.dumps(records,indent=2),encoding="utf-8")
        print(json.dumps({"file":path,"status":r["status"],"rc":r.get("exit_code")}),flush=True)
    passed=all(r["status"]=="COMPLETED" and r.get("exit_code")==0 and r["cleanup_ok"] and not r["skip_detected"] for r in records.values())
    if passed:
        data=json.loads((ROOT/"e6naf_probe_out/result.json").read_text(encoding="utf-8"))
        assert all(p["diagnosis"]=="AGREEMENT" for r in data["records"].values() for p in r["probes"])
        assert data["engine_calls"]=={"Oxidation":0,"Process":1} and data["devsim_solves"]==0
        text=(out/"test_gui_doping_donor_acceptor_real.log").read_text(encoding="utf-8")
        rows=[json.loads(line[8:]) for line in text.splitlines() if line.startswith("METRICS ")]
        assert len(rows)==1
        spec=importlib.util.spec_from_file_location("ad_checks",ROOT/"docs/audits/2026-10-10-e6nad-doping-gui-contract/run_checks.py")
        ad=importlib.util.module_from_spec(spec);spec.loader.exec_module(ad)
        ad.judge_gui(rows[0])
        (out/"gui_metrics.json").write_text(json.dumps(rows[0],indent=2),encoding="utf-8")
    verdict={"pass":passed,"files":len(records),"plan_sha":PLAN_SHA,"source_sha":os.environ["GITHUB_SHA"],
             "scope":"EXPORTED_BARRIER_GEOMETRY_AND_GUI_REFUSAL_NOT_IMPLANT_PHYSICS"}
    (out/"verdict.json").write_text(json.dumps(verdict,indent=2),encoding="utf-8")
    return 0 if passed else 1


if __name__=="__main__":raise SystemExit(main())
