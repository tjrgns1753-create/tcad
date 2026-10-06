"""원격 공식 import-only 감사. 엔진 변경 및 실제 solve 금지."""
import hashlib
import importlib.util
import inspect
import json
import os
import sys
import time
import subprocess
from pathlib import Path
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
M_DIR = ROOT/'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency'
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(M_DIR/'scripts'))
import e6m_metrics as M
from diagnostics import analyze, validate, checked_indices
from flux_source_contract import require_reviewed_source
from resource_supervisor import supervise, require_elements, payload_check, TOTAL_CAP

PLAN_SHA = 'a7bb4e07d03a885c65d01db8f7ba6c341fee67d000e961e1ce6e597a1303e103'
RESOURCE_CONTRACT_SHA = '8baef556d4e7eb71b12d125896303294833719851e89f632ad29bdcc0c1a5b4a'
INPUT_SHAS = {
    'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_preflight.py':'47ce559e56e32d9d7214cc0ca30a0a360ba485e7661817e3b992725409448a9b',
    'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/e6n_geometry_result.json':'5b7225e949c6f41bbd72bd73e8d4ea54f88b937221f52618b03cdec21c038f6f',
    'docs/audits/2026-10-02-e6m-pn-2d-1d-consistency/GEOMETRY_DESIGN_RULE.md':'e51caf5218ba725b99a918c16501e725c62ae87fa389ad28f6ef29c06ebce1c0',
    'tcad/device/devsim/mesh_refine.py':'8973c358aca2e0173918b33117006dc638f37f8c68d8dc922c573c257b50f5e0',
    'tcad/device/devsim/mesh_import.py':'0fe7c71d6594db777d038907a52067ad13b99b868f094758f196d0bbbfe721a8',
    'docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out/states.npz':'65c1a938a6521a14897ed2ec2dfc04178e254248e5a2778f9e0b7d1a56e1c8e2'}


def preflight(callback, path=None):
    try:
        digest = hashlib.sha256((HERE/'PLAN.md' if path is None else path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    except OSError as exc:
        raise ValueError('PLAN_PREFLIGHT_BLOCKED: missing') from exc
    if digest != PLAN_SHA:
        raise ValueError('PLAN_PREFLIGHT_BLOCKED: mismatch')
    return callback()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_inputs():
    """문자 파일 예상 해시는 LF 정규화, npz 예상 해시는 원시 바이트 기준."""
    for relative,expected in INPUT_SHAS.items():
        data=(ROOT/relative).read_bytes()
        if not relative.endswith('.npz'):
            data=data.replace(b'\r\n',b'\n')
        if hashlib.sha256(data).hexdigest()!=expected:
            raise ValueError('INPUT_PREFLIGHT_BLOCKED: '+relative)


def require_flux_source(function, callback):
    """검토한 공식 helper AST를 대조한다. 엔진 구현 동일성 증명은 아니다."""
    try:
        source = inspect.getsource(function)
    except Exception as exc:
        raise ValueError('OFFICIAL_FLUX_SOURCE_UNAVAILABLE') from exc
    require_reviewed_source(source)
    return callback()


def without_solve(dv, report, callback):
    """엔진 확보 직후부터 helper import/np.load/cleanup 예외까지 보호한다."""
    old_solve = dv.solve
    def forbidden(*args, **kwargs):
        report['solve_attempts'] += 1
        raise RuntimeError('SOLVE_FORBIDDEN')
    dv.solve = forbidden
    try:
        return callback()
    finally:
        dv.solve = old_solve


def cleanup(dv, name, mesh, rec):
    errors = []
    for listing, remove, keyword, value in (
        (dv.get_device_list, dv.delete_device, 'device', name),
        (dv.get_mesh_list, dv.delete_mesh, 'mesh', mesh),
    ):
        try:
            if value in listing():
                remove(**{keyword: value})
        except Exception as exc:
            errors.append(type(exc).__name__ + ': ' + str(exc))
    try:
        leaked = bool(dv.get_device_list() or dv.get_mesh_list())
    except Exception as exc:
        errors.append(type(exc).__name__ + ': ' + str(exc))
        leaked = True
    rec['cleanup_ok'] = not errors and not leaked
    if not rec['cleanup_ok']:
        rec.update(status='FAIL', cleanup_errors=errors, error='CLEANUP_FAILED')
    return rec['cleanup_ok']


def execute():
    def approved_resource_boundary():
        digest=hashlib.sha256((HERE/'RESOURCE_EXECUTION_CONTRACT.md').read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        if digest!=RESOURCE_CONTRACT_SHA:
            raise ValueError('RESOURCE_CONTRACT_PREFLIGHT_BLOCKED')
        return _execute()
    return preflight(approved_resource_boundary)


def _execute():
    if '--candidate' not in sys.argv:
        return _supervised_execute()
    return _execute_candidate()


def _supervised_execute():
    """각 후보 엔진을 별도 Job Object에 격리. 부모에는 엔진 import가 없다."""
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    require_inputs()
    out = ROOT/'e6na_out'
    out.mkdir(exist_ok=False)
    deadline = time.monotonic()+1800
    report = {'plan_sha':PLAN_SHA, 'source_sha':os.environ.get('GITHUB_SHA'),
              'levels':{}, 'solve_attempts':0, 'pn':'NOT_RUN', 'verdict':'FAIL'}
    raw_total = 0
    stopped = False
    for lv in M.LEVELS:
        if stopped:
            report['levels'][lv] = {'status':'NOT_RUN'}
            continue
        monitor = supervise([sys.executable,'-B',str(Path(__file__).resolve()),'--candidate',lv],
                            ROOT, out/(lv+'.log'), total_deadline=deadline)
        rec = {'status':'FAIL', 'supervisor':monitor}
        rec['solve_attempts'] = None  # timeout/누락을 관측된 0으로 발명하지 않음.
        try:
            if monitor['status']!='COMPLETED' or not monitor['cleanup_ok']:
                raise ValueError('SUPERVISOR_BLOCKED')
            result_path = out/lv/'result.json'
            child = json.loads(result_path.read_text(encoding='utf-8'))
            c = child['levels'][lv]
            rec['solve_attempts'] = child.get('solve_attempts')
            if (child['plan_sha']!=PLAN_SHA or type(child['solve_attempts']) is not int or child['solve_attempts']!=0
                    or c['status']!='IMPORT_PASS' or c['cleanup_ok'] is not True
                    or child.get('candidate')!=lv or child.get('official_flux_source_matches') is not True
                    or child.get('execution_status')!='COMPLETED'
                    or c['diagnostic']['verdict'] not in ('NONINVARIANCE_WITNESS','INCONCLUSIVE','NOT_MEASURED')):
                raise ValueError('CHILD_EVIDENCE_INCOMPLETE')
            array_path = out/lv/(lv+'.npz')
            if sha(array_path)!=c['array_sha']:
                raise ValueError('CHILD_ARRAY_HASH_MISMATCH')
            payload_check(c['raw_bytes'], array_path.stat().st_size, raw_total)
            raw_total += c['raw_bytes']
            if raw_total + sum(p.stat().st_size for p in out.rglob('*') if p.is_file() and p.suffix!='.npz') > TOTAL_CAP:
                raise ValueError('OUTPUT_RESOURCE_CAP')
            rec = dict(c, supervisor=monitor, solve_attempts=child['solve_attempts'])
            stopped = c['diagnostic']['verdict']!='NONINVARIANCE_WITNESS'
        except Exception as exc:
            rec.update(error_type=type(exc).__name__, error=str(exc))
            stopped = True
        report['levels'][lv] = rec
    failed = any(r['status']=='FAIL' for r in report['levels'].values())
    attempts = [r.get('solve_attempts') for r in report['levels'].values() if r['status']!='NOT_RUN']
    report['solve_attempts'] = sum(attempts) if all(type(v) is int for v in attempts) else None
    report['execution_status'] = 'FAIL' if failed else 'COMPLETED'
    report['verdict'] = 'FAIL' if failed else ('NONINVARIANCE_WITNESS' if not stopped else 'INCONCLUSIVE')
    text = json.dumps(report,indent=2)+'\n'
    payload_check(0,len(text.encode('utf-8')))
    if raw_total + sum(p.stat().st_size for p in out.rglob('*') if p.is_file() and p.suffix!='.npz') + len(text.encode('utf-8')) > TOTAL_CAP:
        raise ValueError('OUTPUT_RESOURCE_CAP')
    (out/'result.json').write_text(text,encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('execution_status','verdict','solve_attempts')}))
    return int(failed)


def _execute_candidate():
    if os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('REMOTE_ONLY')
    require_inputs()
    if subprocess.run(['git','diff','--quiet','ffa7e4a8872cd914e42066b1b1742312883c8dda','HEAD','--','tcad','tests','tcad_2d_stagewise.py'],cwd=ROOT).returncode != 0:
        raise ValueError('PRODUCTION_OR_TEST_SOURCE_CHANGED')
    from tcad.device.devsim import backend
    dv = backend.require_devsim()
    report = {'plan_sha':PLAN_SHA,'source_sha':os.environ.get('GITHUB_SHA'),
              'solve_attempts':0,'levels':{},'pn':'NOT_RUN', 'precision':{}}
    index = sys.argv.index('--candidate')
    if index+2 != len(sys.argv) or sys.argv[index+1] not in M.LEVELS:
        raise ValueError('INVALID_CANDIDATE')
    report['candidate'] = sys.argv[index+1]
    return without_solve(dv, report, lambda: _execute_import_audit(dv, report))


def _execute_import_audit(dv, report):
    from devsim.python_packages import simple_physics
    require_flux_source(simple_physics.CreateSiliconPotentialOnly, lambda: None)
    out = ROOT/'e6na_out'
    if 'candidate' in report:
        out = out/report['candidate']
    out.mkdir(exist_ok=False)
    report.update(installed_simple_physics_sha=hashlib.sha256(inspect.getsource(simple_physics).encode()).hexdigest(),
                  official_flux_source_matches=True)
    for key in ('extended_model','extended_equation'):
        try:
            report['precision'][key]=dv.get_parameter(name=key)
        except Exception:
            report['precision'][key]='NOT_RECORDED'
    import importlib.metadata
    report['versions']={k:importlib.metadata.version(k) for k in ('devsim','ViennaPS','numpy','meshio')}
    input_paths=[M_DIR/'e6n_geometry_preflight.py',M_DIR/'e6n_geometry_result.json',M_DIR/'GEOMETRY_DESIGN_RULE.md',
                 ROOT/'tcad/device/devsim/mesh_refine.py',ROOT/'tcad/device/devsim/mesh_import.py',
                 ROOT/'docs/audits/2026-10-01-e6k-pn-1d-diagnostic/data/remote_run_36815925901/remote-run-31/outputs/e6k_out/states.npz']
    report['inputs']={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in input_paths}
    R=load('e6na_existing_builder',input_paths[3])
    C=load('e6na_existing_conformity',ROOT/'docs/audits/2026-10-01-batch7h-e6h-conformity-poisson/scripts/conformity_e6h.py')
    T=load('e6na_import_helpers',ROOT/'tests/integration/test_pn_2d_1d_consistency_real.py')
    from tcad.device.devsim.mesh_import import import_process_result
    from tcad.mesh.viennaps_adapter import build_process_result
    if dv.get_device_list() or dv.get_mesh_list():
        raise RuntimeError('PREEXISTING_ENGINE_OBJECTS')
    t0=time.monotonic()
    byte_budget=0
    failed=False
    try:
        ref=np.load(input_paths[-1])
        for lv,ny,nn,nt in zip(M.LEVELS,(16,32,64),(8037,31173,122761),(15264,60736,242304)):
            if 'candidate' in report and lv != report['candidate']:
                continue
            require_elements(nt, lambda: None)
            started=time.monotonic()
            rec=report['levels'][lv]={'status':'STARTED'}
            name='e6na_'+lv
            mesh=name+'_mesh'
            try:
                x1=M.e6k_snapshot(ref,lv,'rev',0.0)['x']
                with patch.object(M,'Y_LINES_UM',np.linspace(-M.H_UM,0,ny+1).tolist()):
                    p,t=M.build_mesh(x1)
                p,t,tags,_=R.structured_lateral_refine(p,t,np.zeros(len(t),dtype=np.int32),[0.],[0.1])
                require_elements(len(t), lambda: None)
                assert (len(p),len(t))==(nn,nt)
                conf=C.check_conformity(p,t)
                geo=M.geometry_checks(p,t)
                if not conf['pass'] or geo['obtuse_triangles'] or geo['degenerate_triangles'] or geo['area_rel_err']>1e-12:
                    raise ValueError('PRE_IMPORT_GEOMETRY_FAIL')
                rec.update(conformity=conf,geometry=geo,mesh_sha=hashlib.sha256(p.tobytes()+t.tobytes()).hexdigest())
                path=T.write_mesh(p,t,lv)
                result=build_process_result({'final_mesh':path,'snapshots':[]})
                imported=import_process_result(result,mesh_name=mesh,device_name=name,contact_regions=['Si'],contact_axis='x',length_scale_to_cm=1e-4)
                if imported.regions != ['Si']:
                    raise ValueError('REGION_MISMATCH')
                a={k:np.array(dv.get_node_model_values(device=name,region='Si',name=k)) for k in ('x','y','NodeVolume')}
                a['xy']=np.column_stack((a.pop('x'),a.pop('y')))
                a['triangles']=checked_indices(dv.get_element_node_list(device=name,region='Si'), len(a['xy']), 3)
                for k in ('node_index','x','y'):
                    dv.edge_from_node_model(device=name,region='Si',node_model=k)
                a['edges']=checked_indices(np.column_stack([dv.get_edge_model_values(device=name,region='Si',name='node_index@n'+str(k)) for k in (0,1)]), len(a['xy']), 2)
                a.update({k:np.array(dv.get_edge_model_values(device=name,region='Si',name=k)) for k in ('EdgeCouple','EdgeLength')})
                validate(a,report['solve_attempts'])
                refpoints=p[:,:2]*1e-4
                oo=np.lexsort((a['xy'][:,1],a['xy'][:,0]));rr=np.lexsort((refpoints[:,1],refpoints[:,0]))
                if len(a['xy'])!=len(refpoints) or not np.all(np.abs(a['xy'][oo]-refpoints[rr]) <= [4e-15,1e-17]):
                    raise ValueError('IMPORT_COORDINATE_MISMATCH')
                mapping=np.empty(nn,dtype=np.int64);mapping[oo]=rr
                canonical=lambda q:sorted(map(tuple,np.sort(q,axis=1).tolist()))
                if canonical(mapping[a['triangles']]) != canonical(t):
                    raise ValueError('IMPORT_CONNECTIVITY_MISMATCH')
                if not imported.area_conservation['Si']['pass']:
                    raise ValueError('IMPORT_AREA_FAIL')
                contacts={}
                for contact,xx in (('Si_xmin',-.002),('Si_xmax',.002)):
                    ids=T.nodes_of_contact(dv,name,contact)
                    expected=np.flatnonzero(a['xy'][:,0]==xx).tolist()
                    if ids!=expected:
                        raise ValueError('CONTACT_NODE_MISMATCH')
                    contacts[contact]=ids
                    a[contact]=np.array(ids,dtype=np.int64)
                diagnostic,arrays=analyze(a)
                a.update(arrays,source_points_um=p,source_triangles=t)
                rec.update(diagnostic=diagnostic,contacts=contacts,area_gate=imported.area_conservation['Si'])
                size=sum(v.nbytes for v in a.values()) + len(json.dumps(report).encode('utf-8'))
                byte_budget+=size
                if size>120*1024**2 or byte_budget>200*1024**2:
                    raise ValueError('OUTPUT_RESOURCE_CAP')
                if time.monotonic()-started>600 or time.monotonic()-t0>1800:
                    raise ValueError('WALL_RESOURCE_CAP')
                import ctypes
                class Memory(ctypes.Structure):
                    _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(k,ctypes.c_size_t) for k in ('peak_ws','ws','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
                mem=Memory();mem.cb=ctypes.sizeof(mem)
                if not ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1),ctypes.byref(mem),mem.cb):
                    raise RuntimeError('MEMORY_METRIC_UNAVAILABLE')
                if mem.peak_ws>6*1024**3:
                    raise ValueError('MEMORY_RESOURCE_CAP')
                rec.update(raw_bytes=size,peak_working_set=mem.peak_ws)
                np.savez_compressed(out/(lv+'.npz'),**a)
                import zipfile
                with zipfile.ZipFile(out/(lv+'.npz')) as archive:
                    uncompressed=sum(entry.file_size for entry in archive.infolist())
                payload_check(max(size,uncompressed), (out/(lv+'.npz')).stat().st_size)
                rec['raw_bytes']=max(size,uncompressed)
                rec['array_sha']=sha(out/(lv+'.npz'))
                rec['status']='IMPORT_PASS'
            except Exception as exc:
                rec.update(status='FAIL',error_type=type(exc).__name__,error=str(exc))
                failed=True
            finally:
                rec['duration_s']=time.monotonic()-started
                if not cleanup(dv, name, mesh, rec):
                    failed=True
                (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
            if failed or report['solve_attempts'] or rec['diagnostic']['verdict']!='NONINVARIANCE_WITNESS':
                break
        for lv in M.LEVELS:
            report['levels'].setdefault(lv,{'status':'NOT_RUN'})
        report['execution_status']='FAIL' if failed or report['solve_attempts'] else 'COMPLETED'
        report['verdict']='FAIL' if failed or report['solve_attempts'] else ('NONINVARIANCE_WITNESS' if all(report['levels'][lv].get('diagnostic',{}).get('verdict')=='NONINVARIANCE_WITNESS' for lv in M.LEVELS) else 'INCONCLUSIVE')
    except Exception as exc:
        report.update(execution_status='FAIL', verdict='FAIL', error_type=type(exc).__name__, error=str(exc))
        failed=True
    finally:
        report.setdefault('execution_status', 'FAIL')
        report.setdefault('verdict', 'FAIL')
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('execution_status','verdict','solve_attempts')},indent=2))
    return int(failed or report['solve_attempts']>0)


if __name__=='__main__':
    sys.exit(execute())
