"""고정 barrier 반례. ViennaPS만 원격 실행, DEVSIM import/solve 금지."""
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
PLAN_SHA="b41c37cace5393ca4824b9d8aea23752a1e4290f35385297768e07f2a5ebfe13"
PROBES=[-4.75,-4.5,-4.25,-4.0,-3.0,0.0,3.0,4.25,4.75]


def detector_functions():
    # Execute EXACT production function ASTs, no backend module/import.
    # This isolates pure exported-mesh classification, not a second detector.
    source=(ROOT/"tcad/device/devsim/mesh_import.py").read_text(encoding="utf-8")
    tree=ast.parse(source)
    names={"_estimate_mesh_spacing_um","derive_barrier_covered_windows"}
    selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(selected)==2
    ns={"np":__import__("numpy"),"ProcessResult":Any,"Optional":Optional,"List":List,"Dict":Dict}
    module=ast.Module(body=selected,type_ignores=[])
    exec(compile(module,"PRODUCTION_FUNCTION_AST","exec"),ns)
    return ns, hashlib.sha256(ast.dump(module,include_attributes=False).encode()).hexdigest()


def intervals(points,triangles,tags,tag,x):
    from fractions import Fraction as F
    x=F(float(x)); pieces=[]
    for tri in triangles[tags==tag]:
        v=[(F(float(points[i][0])),F(float(points[i][1]))) for i in tri]
        if not min(p[0] for p in v)<=x<=max(p[0] for p in v):
            continue
        yy=[]
        for a,b in zip(v,v[1:]+v[:1]):
            if a[0]==b[0]:
                if x==a[0]:
                    yy.extend((a[1],b[1]))
            elif min(a[0],b[0])<=x<=max(a[0],b[0]):
                yy.append(a[1]+(x-a[0])*(b[1]-a[1])/(b[0]-a[0]))
        if yy and max(yy)>min(yy):
            pieces.append((min(yy),max(yy)))
    union=[]
    for lo,hi in sorted(pieces):
        if union and lo<=union[-1][1]:
            union[-1]=(union[-1][0],max(union[-1][1],hi))
        else:
            union.append((lo,hi))
    return [[float(a),float(b)] for a,b in union]


def inspect(path,result,native,ns):
    import meshio
    mesh=meshio.read(path)
    block=next(c for c in mesh.cells if c.type=="triangle")
    index=mesh.cells.index(block)
    tags=mesh.cell_data[result.material_field][index]
    points=mesh.points[:,:2].astype(float)
    triangles=block.data
    material={r.name:r.tag for r in result.material_regions}
    windows=ns["derive_barrier_covered_windows"](
        result,"Si","SiO2",axis="x",min_barrier_thickness_um=0.01)
    spacing=ns["_estimate_mesh_spacing_um"](points,triangles)
    rows=[]
    for x in PROBES:
        si=intervals(points,triangles,tags,material["Si"],x)
        oxide=intervals(points,triangles,tags,material["SiO2"],x)
        detected=any(w["min_um"]<=x<=w["max_um"] for w in windows)
        si_top=max((v[1] for v in si),default=None)
        above=[v for v in oxide if si_top is not None and v[0]>=si_top-1e-6]
        covered=any(v[1]-v[0]>=0.01 for v in above)
        nsi=float(native["Si"][x])
        nox=native["SiO2"].get(x)
        ncover=nox is not None and float(nox)-nsi>=0.01
        if ncover and not covered:
            label="EXPORT_REPRESENTATION_MISMATCH"
        elif ncover and covered and not detected:
            label="DETECTOR_FALSE_NEGATIVE"
        elif not ncover and not covered and detected:
            label="DETECTOR_FALSE_POSITIVE"
        else:
            label="AGREEMENT" if ncover==covered==detected else "INCONCLUSIVE"
        rows.append(dict(x_um=x,native_si_top=nsi,native_oxide_top=nox,
                         native_covered=ncover,exported_si_intervals=si,
                         exported_oxide_intervals=oxide,exported_covered=covered,
                         detector_covered=detected,diagnosis=label))
    return dict(probes=rows,windows=windows,spacing_um=spacing,
                points=len(points),triangles=len(triangles))


def main():
    if os.environ.get("RUNNER_ENVIRONMENT")!="github-hosted":
        raise RuntimeError("REMOTE_ONLY")
    if hashlib.sha256((HERE/"PLAN.md").read_bytes().replace(b"\r\n",b"\n")).hexdigest()!=PLAN_SHA:
        raise ValueError("PLAN_HASH_MISMATCH_BEFORE_ENGINE_IMPORT")
    def no_devsim(event,args):
        if event=="import" and args[0].split(".")[0]=="devsim":
            raise RuntimeError("DEVSIM_IMPORT_FORBIDDEN")
    sys.addaudithook(no_devsim)
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"tests/integration"))
    import numpy as np
    import _explicit_chain_fixture as C
    import tcad.process.etching
    from tcad.process.flow import FlowStep
    from tcad.mesh.viennaps_adapter import build_process_result
    out=ROOT/"e6nae_out";out.mkdir(exist_ok=True)
    state=C.build_explicit_chain_state(out,x_extent_um=10,y_extent_um=8,
        silicon_depth_um=5,oxide_top_um=0.3,grid_delta_um=0.1,
        extra_columns_um=PROBES)
    ns,function_sha=detector_functions()
    recipe=dict(grid_delta_um=0.1,x_extent_um=10,y_extent_um=8,silicon_depth_um=5,
        pr_thickness_um=0.5,remask_spans_um=[[-5,-1.5],[1.5,5]],mask_material="PHS",
        material_rates={"SiO2":-0.6,"Si":0.0,"PHS":0.0},default_rate=0.0,etch_time_s=1.0)
    results,counts,stages=C.run_steps_from_state(state,out,"selective_etch",
        [FlowStep("etching","isotropic",recipe)])
    assert counts["Oxidation"]==0 and counts["Process"]>0
    stage=stages[0]
    shutil.copyfile(state.mesh_path,out/"before.vtu")
    shutil.copyfile(results[0].volume_mesh_path,out/"after.vtu")
    np.savez(out/"native_columns.npz",x=state.columns_um,
             before_si=state.native_tops["Si"],before_oxide=state.native_tops["SiO2"],
             after_si=stage.native["Si"],after_oxide=stage.native["SiO2"])
    assert np.max(np.abs(stage.native["Si"]-state.native_tops["Si"]))<=C.native_eps(8)
    idx=[list(state.columns_um).index(x) for x in PROBES]
    initial=state.native_tops["SiO2"][idx]
    final=stage.native["SiO2"][idx]
    assert np.all(np.isfinite(initial)) and np.all(np.isfinite(final))
    assert np.all(initial-state.native_tops["Si"][idx]>=0.01)
    protected=[i for i,x in enumerate(PROBES) if x!=0]
    assert np.max(np.abs(final[protected]-initial[protected]))<=C.native_eps(8)
    opened=PROBES.index(0.0)
    assert abs(final[opened]-stage.native["Si"][idx[opened]])<=C.native_eps(8)
    def nmap(data):
        return {name:{x:float(data[name][list(state.columns_um).index(x)]) for x in PROBES}
                for name in ("Si","SiO2")}
    before=build_process_result({"final_mesh":state.mesh_path,"snapshots":[]})
    records={"before":inspect(state.mesh_path,before,nmap(state.native_tops),ns),
             "after":inspect(results[0].volume_mesh_path,results[0],nmap(stage.native),ns)}
    result=dict(complete=True,records=records,function_ast_sha=function_sha,
                plan_sha=PLAN_SHA,provenance=state.provenance,engine_calls=counts,
                initial_request_offset_um=(initial-0.3).tolist(),
                request_offset_status="REQUEST_OFFSET_RECORDED_ONLY",
                devsim_imports=0,devsim_solves=0,production_changed=False,
                source_sha=os.environ["GITHUB_SHA"])
    (out/"result.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    for label,r in records.items():
        for row in r["probes"]:
            print(label,row["x_um"],row["diagnosis"],flush=True)
    print(json.dumps({"complete":True,"false_negatives":sum(
        v["diagnosis"]=="DETECTOR_FALSE_NEGATIVE" for r in records.values() for v in r["probes"])}))
    assert "devsim" not in sys.modules
    return 0


if __name__=="__main__":
    raise SystemExit(main())
