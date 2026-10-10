"""Independent source/raw/GUI/native checks; no engine imports."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
RAW=HERE/"raw_final/remote-run-83"
SOURCE="48bf6ab951c9851b5328ef0f1d502de540d90042"
RUN="38054909716"
sys.path.insert(0,str(ROOT))
def forbid(event,args):
    if event=="import" and args[0].split(".")[0] in {"devsim","viennaps","viennals"}:
        raise RuntimeError("ENGINE_IMPORT_FORBIDDEN")
sys.addaudithook(forbid)


def digest(data): return hashlib.sha256(data).hexdigest()


def judge_records(records,expected):
    assert set(records)==set(expected)
    for path,r in records.items():
        assert r["status"]=="COMPLETED" and r["exit_code"]==0
        assert r["cleanup_ok"] is True and r["skip_detected"] is False


def main():
    import numpy as np
    s=json.loads((RAW/"summary.json").read_text(encoding="utf-8"))
    assert s["source"]["github_sha"]==s["source"]["git_head"]==SOURCE
    assert s["source"]["run_id"]==RUN and s["runner"]["github_hosted_confirmed"] is True
    assert s["status"]=="PASS" and s["exit_code"]==0 and not s["omitted_outputs"] and not s["log_truncated"]
    for entry in s["outputs"]:
        b=(RAW/"outputs"/entry["path"]).read_bytes()
        assert digest(b)==entry["sha256"] and len(b)==entry["bytes"]
    assert digest((RAW/"run.log").read_bytes())==s["log"]["sha256"]
    for entry in s["inputs"]:
        b=subprocess.check_output(["git","show",SOURCE+":"+entry["path"]],cwd=ROOT)
        variants=(b,b.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n"))
        assert any(digest(v)==entry["sha256"] and len(v)==entry["bytes"] for v in variants),entry["path"]
    spec=importlib.util.spec_from_file_location("af_runner",HERE/"run_checks.py")
    af=importlib.util.module_from_spec(spec);spec.loader.exec_module(af)
    assert digest((HERE/"PLAN.md").read_bytes().replace(b"\r\n",b"\n"))==af.PLAN_SHA
    out=RAW/"outputs/e6naf_out"
    records=json.loads((out/"records.json").read_text(encoding="utf-8"))
    judge_records(records,af.FILES)
    mutants=[]
    for key in ("missing","solve_failure","cleanup","skip"):
        m=copy.deepcopy(records);path=next(iter(m))
        if key=="missing":del m[path]
        elif key=="solve_failure":m[path]["exit_code"]=1
        elif key=="cleanup":m[path]["cleanup_ok"]=False
        else:m[path]["skip_detected"]=True
        try:judge_records(m,af.FILES)
        except AssertionError:mutants.append(key)
        else:raise AssertionError("FALSE PASS "+key)
    spec=importlib.util.spec_from_file_location("ad_verify",ROOT/"docs/audits/2026-10-10-e6nad-doping-gui-contract/verify_artifact.py")
    ad=importlib.util.module_from_spec(spec);spec.loader.exec_module(ad)
    m=json.loads((out/"gui_metrics.json").read_text(encoding="utf-8"));ad.check_metrics(m)
    text=(out/"test_gui_doping_donor_acceptor_real.log").read_text(encoding="utf-8")
    assert [json.loads(line[8:]) for line in text.splitlines() if line.startswith("METRICS ")]==[m]
    fault=(out/"gui_failure.log").read_text(encoding="utf-8")
    assert "attach/write/solve/modal 0" in fault
    probe=RAW/"outputs/e6naf_probe_out"
    data=json.loads((probe/"result.json").read_text(encoding="utf-8"))
    assert data["source_sha"]==SOURCE and data["plan_sha"]==af.PLAN_SHA
    assert data["engine_calls"]=={"Oxidation":0,"Process":1} and data["devsim_solves"]==data["devsim_imports"]==0
    z=np.load(probe/"native_columns.npz",allow_pickle=False)
    assert np.max(np.abs(z["after_si"]-z["before_si"]))<=16*2**-52*8
    assert set(data["records"])=={"before","after"}
    for phase,r in data["records"].items():
        assert len(r["probes"])==9 and all(v["diagnosis"]=="AGREEMENT" for v in r["probes"])
        assert sum(v["native_covered"] for v in r["probes"])==(9 if phase=="before" else 8)
    assert len(m["barrier_x"]["barrier_windows"])==2
    report={"pass":True,"source_sha":SOURCE,"run_id":RUN,"files":len(records),
            "outputs_byte_verified":len(s["outputs"]),"inputs_verified":len(s["inputs"]),
            "fresh_column_agreements":18,"mutations_blocked":mutants,
            "GUI_cases":7,"unknown_barrier_attach_write_solve":0,
            "engine_imports_in_verifier":0,"scope":"GEOMETRY_NOT_IMPLANT_TRANSPORT"}
    print(json.dumps(report,indent=2))


if __name__=="__main__":main()
