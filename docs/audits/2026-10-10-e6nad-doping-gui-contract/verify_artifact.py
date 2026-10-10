"""원본 artifact 바이트와 GUI 계약을 엔진 없이 독립 재검사."""
import copy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
RAW=HERE/"raw/remote-run-79"
SOURCE="586b6f9f4da4f80f456cde1b65431558af8686e0"
RUN="38053242103"
PLAN_SHA="e56c4eb99142e01a2aea347bc2cb0ed98961c913f2059531f2e3994cf8e5b935"


def digest(b):
    return hashlib.sha256(b).hexdigest()


def check_metrics(m):
    names={"compensated","n","p","gaussian","windows","barrier_x","barrier_y"}
    assert set(m)==names
    for name in ("n","p"):
        r=m[name]
        assert type(r["solve_calls"]) is int and r["solve_calls"]>=1
        assert r["doping_writes"]>=1 and r["reattach_identity"] is True
        assert r["attachment_count"]==1 and r["canonical_state_object_unchanged"] is True
        logged=r["currents_in_log"]
        # Two contacts appear once in the result section and again in the
        # log-only notification. These are repeated output, not four contacts.
        assert len(logged)==4 and logged[:2]==logged[2:]
        c=logged[:2]
        assert all(math.isfinite(v) for v in c) and c[0]!=0
        assert abs(c[0]+c[1])<=1e-4*abs(c[0])
        cmp=r["canonical_vs_solved_netdoping"]
        assert cmp["nodes"]>0 and cmp["mismatched_nodes"]==0 and cmp["max_abs_diff_cm3"]==0
        assert r["measurement_section_logged"] is True and not r["unsupported_in_log"]
    for name in names-{"n","p"}:
        r=m[name]
        assert r["solve_calls"]==r["doping_writes"]==r["history_entries_added"]==0
        assert r["currents_in_log"]==[] and r["measurement_section_logged"] is False
        assert r["last_physics_status"]["resolution"]=="UNSUPPORTED_BY_MODEL"
    assert m["compensated"]["last_physics_status"]["reason_code"]=="COMPENSATED_TRANSPORT_MODEL_MISSING"
    for name in ("gaussian","windows"):
        r=m[name]
        assert r["last_physics_status"]["reason_code"]=="DOPANT_ACTIVATION_MODEL_MISSING"
        at=r["new_attachments"]
        assert len(at)==2 and {a["polarity"] for a in at}=={"donor","acceptor"}
        assert all(a["chemical_state"]=="CHEMICAL" for a in at)
    g={a["polarity"]:a for a in m["gaussian"]["new_attachments"]}
    assert g["donor"]["species"]=="P" and g["acceptor"]["species"]=="B"
    assert g["donor"]["model_params"]["peak_conc_cm3"]==2e17
    assert g["acceptor"]["model_params"]["peak_conc_cm3"]==3e16
    w={a["polarity"]:a for a in m["windows"]["new_attachments"]}
    assert w["donor"]["model_params"]["background_cm3"]==1e14
    assert w["acceptor"]["model_params"]["background_cm3"]==1e17
    # Canonical profile omits the exact-zero source acceptor term; the
    # GUI request's raw zero field is separately asserted in the real test.
    for polarity, expected in (("donor",[1e20,9e19]),("acceptor",[1e19])):
        assert [v[2] for v in w[polarity]["model_params"]["windows"]]==expected
    for name in ("barrier_x","barrier_y"):
        r=m[name]
        assert r["detector_axis"]=="x" and r["input_provenance"]=="DIRECT_EXPLICIT_GEOMETRY"
        win=r["barrier_windows"]
        assert not any(v["min_um"]<0<v["max_um"] for v in win)
        assert any(v["min_um"]<=-4<=v["max_um"] for v in win)
    assert m["barrier_x"]["barrier_windows"]==m["barrier_y"]["barrier_windows"]


def main():
    def forbid(event,args):
        if event=="import" and args[0].split(".")[0] in {"devsim","viennaps","viennals"}:
            raise RuntimeError("ENGINE_IMPORT_FORBIDDEN")
    sys.addaudithook(forbid)
    summary=json.loads((RAW/"summary.json").read_text())
    assert summary["source"]["github_sha"]==summary["source"]["git_head"]==SOURCE
    assert summary["source"]["run_id"]==RUN
    assert summary["runner"]["github_hosted_confirmed"] is True
    assert summary["status"]=="PASS" and summary["exit_code"]==0
    assert summary["omitted_outputs"]==[] and summary["log_truncated"] is False
    verified=[]
    for record in summary["outputs"]:
        data=(RAW/"outputs"/record["path"]).read_bytes()
        assert len(data)==record["bytes"] and digest(data)==record["sha256"]
        rel=(RAW/"outputs"/record["path"]).relative_to(ROOT).as_posix()
        assert subprocess.check_output(["git","show","HEAD:"+rel],cwd=ROOT)==data
        verified.append(record["path"])
    log=(RAW/"run.log").read_bytes()
    assert len(log)==summary["log"]["bytes"] and digest(log)==summary["log"]["sha256"]
    for name in ("run.log","summary.json"):
        rel=(RAW/name).relative_to(ROOT).as_posix()
        assert subprocess.check_output(["git","show","HEAD:"+rel],cwd=ROOT)==(RAW/name).read_bytes()
    input_verified=[]
    for r in summary["inputs"]:
        blob=subprocess.check_output(["git","show",SOURCE+":"+r["path"]],cwd=ROOT)
        # Actions checkout autocrlf=true; use exact recorded bytes or its CRLF checkout.
        variants=(blob,blob.replace(b"\r\n",b"\n").replace(b"\n",b"\r\n"))
        assert any(len(b)==r["bytes"] and digest(b)==r["sha256"] for b in variants), r["path"]
        input_verified.append(r["path"])
    assert digest((HERE/"PLAN.md").read_bytes().replace(b"\r\n",b"\n"))==PLAN_SHA
    assert subprocess.run(["git","diff","--exit-code","e1c0c025",SOURCE,"--","tcad","tcad_2d_stagewise.py"],
                          cwd=ROOT,stdout=subprocess.DEVNULL).returncode==0
    outputs=RAW/"outputs/e6nad_out"
    records=json.loads((outputs/"records.json").read_text())
    expected={"tests/integration/test_gui_doping_donor_acceptor_real.py",
              "tests/integration/test_measurement_canonical_state_gate_real.py",
              "tests/integration/test_gui_headless_no_modal_hang_real.py",
              "tests/unit/test_doping_staleness_mock.py"}
    assert set(records)==expected
    for path,r in records.items():
        assert r["status"]=="COMPLETED" and r["exit_code"]==0 and r["cleanup_ok"] is True
        assert r["skip_detected"] is False
        data=(outputs/r["log_file"]).read_bytes()
        assert digest(data)==r["log_sha256"]
        blob=subprocess.check_output(["git","show",SOURCE+":"+path],cwd=ROOT)
        assert digest(blob.replace(b"\r\n",b"\n"))==r["input_lf_sha256"]
    m=json.loads((outputs/"gui_metrics.json").read_text())
    rawlog=(outputs/"test_gui_doping_donor_acceptor_real.log").read_text()
    lines=[line[8:] for line in rawlog.splitlines() if line.startswith("METRICS ")]
    assert len(lines)==1 and json.loads(lines[0])==m
    check_metrics(m)
    failures=[]
    for name,edit in (
        ("missing_case",lambda x:x.pop("windows")),
        ("blocked_solve",lambda x:x["gaussian"].update(solve_calls=1)),
        ("canonical_mismatch",lambda x:x["n"]["canonical_vs_solved_netdoping"].update(mismatched_nodes=1)),
        ("duplicate_reattach",lambda x:x["p"].update(attachment_count=2)),
        ("chemical_active",lambda x:x["gaussian"]["new_attachments"][0].update(chemical_state="ACTIVE")),
        ("wrong_species",lambda x:x["gaussian"]["new_attachments"][0].update(species="As")),
        ("wrong_window",lambda x:x["windows"]["new_attachments"][0]["model_params"].update(background_cm3=0)),
        ("wrong_barrier_axis",lambda x:x["barrier_y"].update(detector_axis="y")),
        ("stale_current",lambda x:x["barrier_x"].update(currents_in_log=[1.0])),
    ):
        damaged=copy.deepcopy(m);edit(damaged)
        try:
            check_metrics(damaged)
        except (AssertionError,KeyError,TypeError):
            failures.append(name)
        else:
            raise AssertionError("FALSE_GREEN: "+name)
    assert len(failures)==9 and not {"devsim","viennaps","viennals"}.intersection(sys.modules)
    report={"pass":True,"source_sha":SOURCE,"run_id":RUN,
            "input_hashes_verified":len(input_verified),"output_hashes_verified":len(verified),
            "log_hash_verified":True,"cases":7,"controls":3,
            "mutations_blocked":failures,"engine_imports":0,"new_solves":0,
            "production_and_gate_unchanged":True,
            "normal_currents_A_per_cm":{n:m[n]["currents_in_log"][:2] for n in ("n","p")},
            "normal_solve_calls":{n:m[n]["solve_calls"] for n in ("n","p")},
            "barrier_windows":m["barrier_x"]["barrier_windows"]}
    print(json.dumps(report,indent=2))
    return report


if __name__=="__main__":
    main()
