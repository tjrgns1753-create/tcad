"""87-file unit evidence and 86-file baseline comparison; engine free."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
RAW=HERE/"raw/remote-run-84"
SOURCE="f45d5a9ec947e89554fd0b359d0c32ff74b263a4"
RUN="38055172828"
def forbid(event,args):
    if event=="import" and args[0].split(".")[0] in {"viennaps","viennals","devsim"}:
        raise RuntimeError("ENGINE_IMPORT_FORBIDDEN")
sys.addaudithook(forbid)
def sha(data):return hashlib.sha256(data).hexdigest()


def main():
    summary=json.loads((RAW/"summary.json").read_text(encoding="utf-8"))
    assert summary["source"]["github_sha"]==summary["source"]["git_head"]==SOURCE
    assert summary["source"]["run_id"]==RUN and summary["runner"]["github_hosted_confirmed"] is True
    assert summary["status"]=="PASS" and summary["exit_code"]==0
    assert summary["omitted_outputs"]==[] and summary["log_truncated"] is False
    for r in summary["outputs"]:
        data=(RAW/"outputs"/r["path"]).read_bytes()
        assert sha(data)==r["sha256"] and len(data)==r["bytes"]
    assert sha((RAW/"run.log").read_bytes())==summary["log"]["sha256"]
    manifest=json.loads((HERE/"MANIFEST.json").read_text(encoding="utf-8"))
    assert sha((HERE/"MANIFEST.json").read_bytes().replace(b"\r\n",b"\n"))=="3b92b7cd2331f38eca89a0489cf9c5ad8a32b1746375a4fca6c60d19e723870c"
    assert sha((HERE/"PLAN.md").read_bytes().replace(b"\r\n",b"\n"))=="d1b0411e6579a3f293275c1eb867c4410ca5851a5f9e1cb9b3881b1cc9a51839"
    expected={r["path"]:r["lf_sha256"] for r in manifest["tests"]}
    assert manifest["count"]==len(expected)==87
    out=RAW/"outputs/e6nag_out"
    records=json.loads((out/"records.json").read_text(encoding="utf-8"))
    assert set(records)==set(expected)
    for path,r in records.items():
        assert r["status"]=="COMPLETED" and r["exit_code"]==0 and r["cleanup_ok"] is True and r["skip_detected"] is False
        assert r["input_lf_sha256"]==expected[path]
        blob=subprocess.check_output(["git","show",SOURCE+":"+path],cwd=ROOT)
        assert sha(blob.replace(b"\r\n",b"\n"))==expected[path]
        assert sha((out/r["log_file"]).read_bytes())==r["log_sha256"]
    olddir=ROOT/"docs/audits/2026-10-10-e6nac-unit-cross-regression"
    oldmanifest=json.loads((olddir/"MANIFEST.json").read_text(encoding="utf-8"))
    oldrecords=json.loads((olddir/"raw/outputs/e6nac_out/records.json").read_text(encoding="utf-8"))
    assert len(oldrecords)==len(oldmanifest["tests"])==86
    for r in oldmanifest["tests"]:
        assert expected[r["path"]]==r["lf_sha256"]
        prior=oldrecords[r["path"]]
        assert prior["status"]=="COMPLETED" and prior["exit_code"]==0 and prior["cleanup_ok"] is True
    assert set(expected)-set(oldrecords)=={"tests/unit/test_barrier_sections_mock.py"}
    verdict=json.loads((out/"verdict.json").read_text(encoding="utf-8"))
    assert verdict["pass"] is True and verdict["counts"]=={"PASS":87,"FAIL":0,"TIMEOUT":0,"ERROR":0}
    assert subprocess.run(["git","diff","--exit-code","48bf6ab",SOURCE,"--","tcad","tcad_2d_stagewise.py"],cwd=ROOT,stdout=subprocess.DEVNULL).returncode==0
    print(json.dumps({"pass":True,"run_id":RUN,"source_sha":SOURCE,"files":87,
                      "baseline_same_input_pass_to_pass":86,"new_test_pass":1,"new_failure":0,
                      "byte_verified_outputs":len(summary["outputs"]),"seconds":summary["duration_s"],
                      "verifier_engine_imports":0,"scope":"UNIT_CONTRACTS_NOT_PHYSICAL_CAPABILITY"},indent=2))


if __name__=="__main__":main()
