"""Read preserved AE artifact; no process/device engines or solves."""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
def forbid(event,args):
    if event=="import" and args[0].split(".")[0] in {"devsim","viennaps","viennals"}:
        raise RuntimeError("ENGINE_IMPORT_FORBIDDEN")
sys.addaudithook(forbid)
import numpy as np
AE=ROOT/"docs/audits/2026-10-10-e6nae-barrier-detection"
RAW=AE/"raw_corrected/remote-run-81"


def main():
    summary=json.loads((RAW/"summary.json").read_text(encoding="utf-8"))
    assert summary["status"]=="PASS" and summary["exit_code"]==0
    for entry in summary["outputs"]:
        assert hashlib.sha256((RAW/"outputs"/entry["path"]).read_bytes()).hexdigest()==entry["sha256"]
    assert hashlib.sha256((RAW/"run.log").read_bytes()).hexdigest()==summary["log"]["sha256"]
    data=json.loads((RAW/"outputs/e6nae_out/result.json").read_text(encoding="utf-8"))
    assert data["source_sha"]=="6615d28e06f03af29c4d95cfbf0c2a68525c1af8"
    assert data["engine_calls"]=={"Oxidation":0,"Process":1} and data["devsim_solves"]==0
    assert sum(v["diagnosis"]=="DETECTOR_FALSE_NEGATIVE" for r in data["records"].values() for v in r["probes"])==4
    spec=importlib.util.spec_from_file_location("ae_probe",AE/"probe.py")
    ae=importlib.util.module_from_spec(spec); spec.loader.exec_module(ae)
    ns,_=ae.detector_functions(); ns["math"]=math
    arrays=np.load(RAW/"outputs/e6nae_out/native_columns.npz",allow_pickle=False)
    results={}; start=time.perf_counter()
    for phase in ("before","after"):
        path=RAW/("outputs/e6nae_out/"+phase+".vtu")
        result=NS(volume_mesh_path=str(path),material_field="Material",
                  material_regions=[NS(name="Si",tag=10),NS(name="SiO2",tag=30)])
        native={name:{float(x):float(v) for x,v in zip(arrays["x"],arrays[phase+suffix])}
                for name,suffix in (("Si","_si"),("SiO2","_oxide"))}
        r=ae.inspect(path,result,native,ns)
        assert len(r["probes"])==9 and all(v["diagnosis"]=="AGREEMENT" for v in r["probes"]),r
        for old,new in zip(data["records"][phase]["probes"],r["probes"]):
            for key in ("x_um","native_si_top","native_oxide_top","exported_si_intervals","exported_oxide_intervals"):
                assert old[key]==new[key],(phase,key)
        results[phase]=r["windows"]
    assert results["before"]==[{"min_um":-5.,"max_um":5.}]
    assert len(results["after"])==2 and not any(v["min_um"]<=0<=v["max_um"] for v in results["after"])
    print(json.dumps({"agreement":18,"false_negatives_before":4,"false_negatives_after":0,
                      "windows":results,"seconds":time.perf_counter()-start,"engine_imports":0}))


if __name__=="__main__": main()
