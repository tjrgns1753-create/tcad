"""공식 import 양성 경로 + 독립 해석해 Poisson; 실제 PN 모델이 아니다."""
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time
import traceback
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=HERE.parent/'2026-10-02-e6na-import-reduction'
sys.path[:0]=[str(ROOT),str(OLD)]
from diagnostics import analyze,validate,geometry_weights,checked_indices
from resource_supervisor import supervise
from test_positive_geometry import positive_fixture,H
from test_review_followup import fixture,check_geometry
from run_e6na import require_inputs,without_solve,cleanup,require_flux_source

PLAN_SHA='e126a3adc89b9c9b10a68908f5c4e28ade12a521eb75d50697cb9c87d32dc1a3'
SNAPSHOT_SHA='f82b7d41882bc170e8752b446cf884f175d9436da4a52a827d3a2668bd4daeeb'
LABELS=('M0','M1','M2','M3')


def preflight(callback,path=None):
    p=HERE/'PLAN.md' if path is None else Path(path)
    try:
        digest=hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    except OSError as exc:
        raise ValueError('PLAN_MISSING') from exc
    if digest!=PLAN_SHA:
        raise ValueError('PLAN_MISMATCH')
    snapshot=HERE/'SNAPSHOT_CORRECTION.md'
    if hashlib.sha256(snapshot.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=SNAPSHOT_SHA:
        raise ValueError('SNAPSHOT_CONTRACT_MISMATCH')
    return callback()


def judge(records,require_native_snapshot=False):
    if len(records)!=4:
        raise ValueError('MISSING_MESH_RECORD')
    rates=[]
    for i,r in enumerate(records):
        if require_native_snapshot and (r['source_verified'] is not True or r['flux_verified'] is not True):
            raise ValueError('NATIVE_SNAPSHOT_EVIDENCE_FAIL')
        if any(type(r[k]) is not int for k in ('triangles','solve_attempts','solve_successes','solve_failures','snapshot_failures')):
            raise ValueError('INVALID_COUNTER')
        if r['label']!=LABELS[i] or r['triangles']!=26*4**i:
            raise ValueError('MESH_IDENTITY_MISMATCH')
        if r['status']!='PASS':
            raise ValueError('MESH_EXECUTION_FAIL')
        if (r['solve_attempts']!=1 or r['solve_successes']!=1 or r['solve_failures']!=0
                or r['snapshot_failures']!=0 or r['cleanup_ok'] is not True):
            raise ValueError('EXECUTION_EVIDENCE_FAIL')
        for k in ('linf','l2','h_max','residual_relative','contact_error','y_spread'):
            if type(r[k]) not in (float,int) or not math.isfinite(r[k]) or r[k]<0:
                raise ValueError('INVALID_METRIC')
        if r['residual_relative']>1e-9 or r['contact_error']>1e-10:
            raise ValueError('EQUATION_OR_CONTACT_FAIL')
        geo=r['geometry']
        if geo['area']['pass'] is not True or any(not math.isfinite(geo[k]) or not 0<=geo[k]<=1e-10
                                                 for k in ('weight_relative','volume_relative')):
            raise ValueError('GEOMETRY_EVIDENCE_FAIL')
        if i:
            if not math.isclose(r['h_max']*2,records[i-1]['h_max'],rel_tol=1e-12,abs_tol=0):
                raise ValueError('REFINEMENT_SCALE_MISMATCH')
            rate={}
            for k in ('linf','l2'):
                previous,current=records[i-1][k],r[k]
                if current==0:
                    rate[k]=None
                elif previous==0:
                    raise ValueError('EXACT_CONTROL_LOST')
                else:
                    rate[k]=math.log2(previous/current)
                if i>=2 and rate[k] is not None and rate[k]<1.5:
                    raise ValueError('CONVERGENCE_RATE_FAIL')
            rates.append(rate)
    if records[-1]['linf']>0.01 or records[-1]['y_spread']<=0.5:
        raise ValueError('FINE_ERROR_OR_2D_RESPONSE_FAIL')
    return {'verdict':'MMS_2D_NUMERICAL_PASS','rates':rates,'pn_approved':False}


def imported_arrays(dv,device):
    kw=dict(device=device,region='Si')
    xy=np.column_stack([dv.get_node_model_values(**kw,name=k) for k in ('x','y')])
    a=dict(xy=xy,triangles=checked_indices(dv.get_element_node_list(**kw),len(xy),3),
           NodeVolume=np.array(dv.get_node_model_values(**kw,name='NodeVolume')))
    dv.edge_from_node_model(**kw,node_model='node_index')
    a['edges']=checked_indices(np.column_stack([dv.get_edge_model_values(**kw,name='node_index@n'+str(k))
                                               for k in (0,1)]),len(xy),2)
    a.update({k:np.array(dv.get_edge_model_values(**kw,name=k)) for k in ('EdgeCouple','EdgeLength')})
    validate(a)
    return a


def import_one(dv,points_um,triangles,label,out):
    import meshio
    from tcad.backends.viennaps import session
    from tcad.mesh.viennaps_adapter import build_process_result
    from tcad.device.devsim.mesh_import import import_process_result
    path=out/(label+'.vtu')
    si=int(session.require_viennaps().Material.Si)
    meshio.write(path,meshio.Mesh(points_um,[('triangle',triangles)],
                                 cell_data={'Material':[np.full(len(triangles),si,dtype=np.int32)]}))
    result=build_process_result({'final_mesh':str(path),'snapshots':[]})
    imported=import_process_result(result,mesh_name=label+'_mesh',device_name=label,
                                  contact_regions=['Si'],contact_axis='x',length_scale_to_cm=1e-4)
    a=imported_arrays(dv,label)
    expected=points_um[:,:2]*1e-4
    oo=np.lexsort((a['xy'][:,1],a['xy'][:,0]))
    rr=np.lexsort((expected[:,1],expected[:,0]))
    if len(oo)!=len(rr) or not np.all(np.abs(a['xy'][oo]-expected[rr])<=64*np.finfo(float).eps*np.ptp(expected,axis=0)):
        raise ValueError('COORDINATE_MISMATCH')
    mapping=np.empty(len(oo),dtype=np.int64); mapping[oo]=rr
    canon=lambda t:sorted(map(tuple,np.sort(t,axis=1).tolist()))
    if canon(mapping[a['triangles']])!=canon(triangles):
        raise ValueError('CONNECTIVITY_MISMATCH')
    reverse=np.empty(len(mapping),dtype=np.int64);reverse[mapping]=np.arange(len(mapping))
    if imported.regions!=['Si'] or not imported.area_conservation['Si']['pass']:
        raise ValueError('MATERIAL_OR_AREA_FAIL')
    for contact,x in (('Si_xmin',a['xy'][:,0].min()),('Si_xmax',a['xy'][:,0].max())):
        ids=sorted({int(i) for el in dv.get_element_node_list(device=label,region='Si',contact=contact) for i in el})
        if ids!=np.flatnonzero(a['xy'][:,0]==x).tolist():
            raise ValueError('CONTACT_SET_MISMATCH')
        a[contact]=np.array(ids,dtype=np.int64)
    gw,gv=geometry_weights(a['xy'],a['triangles'],a['edges'])
    wr=float(np.max(np.abs(a['EdgeCouple']/a['EdgeLength']-gw)/np.maximum(1,np.abs(gw))))
    vr=float(np.max(np.abs(a['NodeVolume']-gv)/gv))
    if max(wr,vr)>1e-10:
        raise ValueError('GEOMETRY_WEIGHT_MISMATCH')
    return imported,a,reverse,dict(weight_relative=wr,volume_relative=vr,area=imported.area_conservation['Si'])


def native_controls(dv,report,out):
    from devsim.python_packages import simple_physics
    require_flux_source(simple_physics.CreateSiliconPotentialOnly,lambda:None)
    for label,data,expected in (('positive',positive_fixture(),'NONINVARIANCE_WITNESS'),
                                ('tensor',fixture(),'INCONCLUSIVE')):
        check_geometry(data)
        points=np.column_stack((data['xy']*1e4,np.zeros(len(data['xy']))))
        rec=report['controls'][label]={'status':'STARTED'}
        try:
            imported,a,mapping,geo=import_one(dv,points,data['triangles'],label,out)
            diag,arrays=analyze(a)
            if diag['verdict']!=expected:
                raise ValueError('NATIVE_CONTROL_VERDICT_MISMATCH')
            if label=='positive':
                got=arrays['stable_actions'][2,mapping[[6,11]]]
                exact=np.array([-125000.,-2250000./17])
                if not np.all(np.abs(got-exact)<=1e-10*np.abs(exact)):
                    raise ValueError('HAND_DERIVATION_MISMATCH')
                rec['hand_actions']=got.tolist()
            a.update(arrays)
            np.savez_compressed(out/(label+'.npz'),**a)
            rec.update(status='PASS',diagnostic=diag,geometry=geo)
        finally:
            if not cleanup(dv,label,label+'_mesh',rec):
                raise RuntimeError('CLEANUP_FAIL')
    report['b0']='PASS'


def solve_mesh(dv,points,triangles,label,out):
    # Independent continuous derivative gives source. Never use graph residual as source.
    rec=dict(label=label,triangles=len(triangles),solve_attempts=0,solve_successes=0,
             solve_failures=0,snapshot_failures=0,cleanup_ok=False)
    try:
        data=dict(xy=points[:,:2]*1e-4,triangles=triangles)
        edges=np.array(sorted({tuple(sorted((int(t[k]),int(t[(k+1)%3])))) for t in triangles for k in range(3)}))
        data['edges']=edges
        gw,gv=geometry_weights(data['xy'],triangles,edges)
        if np.any(gw<0) or np.any(gv<=0):
            raise ValueError('NONOBTUSE_OR_VOLUME_FAIL')
        check_geometry(data)
        imported,a,_,geo=import_one(dv,points,triangles,label,out)
        kw=dict(device=label,region='Si')
        x,y=a['xy'].T; Lx=np.ptp(x);Ly=np.ptp(y)
        exact=np.sin(np.pi*(x-x.min())/Lx)*np.cos(np.pi*(y-y.min())/Ly)
        K=np.pi**2*(1/Lx**2+1/Ly**2)
        source=-K*exact
        dv.node_solution(**kw,name='Potential')
        dv.edge_from_node_model(**kw,node_model='Potential')
        for name,equation in (('Flux','(Potential@n0-Potential@n1)*EdgeInverseLength'),
                              ('Flux:Potential@n0','EdgeInverseLength'),
                              ('Flux:Potential@n1','-EdgeInverseLength')):
            dv.edge_model(**kw,name=name,equation=equation)
        dv.node_model(**kw,name='Source',equation='0')
        dv.set_node_values(**kw,name='Source',values=source.tolist())
        dv.node_model(**kw,name='Source:Potential',equation='0')
        dv.equation(**kw,name='PotentialEquation',variable_name='Potential',edge_model='Flux',node_model='Source')
        for c in ('Si_xmin','Si_xmax'):
            dv.contact_node_model(device=label,contact=c,name=c+'_bc',equation='Potential')
            dv.contact_node_model(device=label,contact=c,name=c+'_bc:Potential',equation='1')
            dv.contact_equation(device=label,contact=c,name='PotentialEquation',node_model=c+'_bc')
        rec['solve_attempts']+=1
        try:
            dv.solve(type='dc',solver_type='direct',absolute_error=1e-10,relative_error=1e-10,maximum_iterations=30)
        except Exception:
            rec['solve_failures']+=1
            raise
        rec['solve_successes']+=1
        try:
            potential=np.array(dv.get_node_model_values(**kw,name='Potential'))
            if not np.all(np.isfinite(potential)):
                raise ValueError('INVALID_POTENTIAL')
            native_source=np.array(dv.get_node_model_values(**kw,name='Source'))
            native_flux=np.array(dv.get_edge_model_values(**kw,name='Flux'))
            if not np.array_equal(native_source,source):
                raise ValueError('NATIVE_SOURCE_MISMATCH')
            expected_flux=(potential[a['edges'][:,0]]-potential[a['edges'][:,1]])/a['EdgeLength']
            if (native_flux.shape!=expected_flux.shape or not np.all(np.isfinite(native_flux))
                    or np.max(abs(native_flux-expected_flux))>256*np.finfo(float).eps*np.max(abs(expected_flux))):
                raise ValueError('NATIVE_FLUX_MISMATCH')
            rec.update(source_verified=True,flux_verified=True)
            error=potential-exact
            weights=a['EdgeCouple']/a['EdgeLength'];e=a['edges'];nv=a['NodeVolume']
            flux=weights*(potential[e[:,0]]-potential[e[:,1]])
            residual=source*nv; rowmag=np.abs(source*nv)
            for k,s in ((0,1),(1,-1)):
                np.add.at(residual,e[:,k],s*flux)
                np.add.at(rowmag,e[:,k],np.abs(flux))
            contact=np.concatenate([a[k] for k in ('Si_xmin','Si_xmax')])
            free=np.ones(len(x),dtype=bool);free[contact]=False
            columns=np.unique(x[free]);center=columns[np.argmin(np.abs(columns-(x.min()+x.max())/2))]
            rec.update(linf=float(np.max(np.abs(error))),l2=float(np.sqrt(np.sum(nv*error**2)/np.sum(nv))),
                       h_max=float(np.max(a['EdgeLength'])),
                       residual_relative=float(np.max(np.abs(residual[free]))/np.max(rowmag[free])),
                       contact_error=float(np.max(np.abs(potential[contact]))),
                       y_spread=float(np.ptp(potential[x==center])),geometry=geo)
            a.update(Potential=potential,analytic=exact,Source=native_source,PrescribedSource=source,
                     NativeFlux=native_flux,discrete_residual=residual)
            np.savez_compressed(out/(label+'.npz'),**a)
        except Exception:
            rec['snapshot_failures']+=1
            raise
    except Exception as exc:
        rec.update(status='FAIL',error_type=type(exc).__name__,error=str(exc))
    finally:
        if not cleanup(dv,label,label+'_mesh',rec):
            rec['status']='FAIL'
    rec.setdefault('status','PASS')
    return rec


def child():
    require_inputs()
    from tcad.device.devsim import backend
    dv=backend.require_devsim()
    out=ROOT/'e6nb_out';out.mkdir(exist_ok=True)
    report=dict(plan_sha=PLAN_SHA,snapshot_contract_sha=SNAPSHOT_SHA,snapshot_schema=2,
                source_sha=os.environ.get('GITHUB_SHA'),controls={},meshes=[],
                solve_attempts=0,pn_approved=False,execution_status='FAIL')
    try:
        if dv.get_device_list() or dv.get_mesh_list():
            raise RuntimeError('PREEXISTING_ENGINE_OBJECTS')
        without_solve(dv,report,lambda:native_controls(dv,report,out))
        if report['solve_attempts']!=0:
            raise ValueError('B0_SOLVE_FORBIDDEN')
        from tcad.device.devsim.mesh_refine import _refine_once
        a=positive_fixture();points=np.column_stack((a['xy']*1e4,np.zeros(len(a['xy']))));tri=a['triangles']
        tags=np.zeros(len(tri),dtype=np.int32)
        for i,label in enumerate(LABELS):
            if len(tri)>10000 or len(tri)!=26*4**i:
                raise ValueError('ELEMENT_RESOURCE_CAP')
            rec=solve_mesh(dv,points,tri,label,out)
            report['meshes'].append(rec)
            if rec['status']!='PASS':
                raise ValueError('MMS_EXECUTION_FAIL')
            if i<3:
                points,tri,tags=_refine_once(points,tri,tags,np.ones(len(tri),dtype=bool))
        report['judgment']=judge(report['meshes'],require_native_snapshot=True)
        report['execution_status']='COMPLETED'
    except Exception as exc:
        report.update(error_type=type(exc).__name__,error=str(exc))
        traceback.print_exc()
    report['solve_attempts']+=sum(r['solve_attempts'] for r in report['meshes'])
    report['solve_successes']=sum(r['solve_successes'] for r in report['meshes'])
    report['cleanup_ok']=not (dv.get_device_list() or dv.get_mesh_list())
    if not report['cleanup_ok']:
        report['execution_status']='FAIL'
    import importlib.metadata
    report['versions']={k:importlib.metadata.version(k) for k in ('devsim','ViennaPS','numpy')}
    (out/'result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report.get(k) for k in ('execution_status','b0','solve_attempts','solve_successes','judgment')}),flush=True)
    return 0 if report['execution_status']=='COMPLETED' else 1


def main():
    def approved():
        if os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted' or os.name!='nt':
            raise RuntimeError('REMOTE_WINDOWS_ONLY')
        if '--child' in sys.argv:
            return child()
        out=ROOT/'e6nb_out';out.mkdir(exist_ok=False)
        rec=supervise([sys.executable,'-B',str(Path(__file__).resolve()),'--child'],ROOT,out/'child.log',candidate_s=120)
        log=out/'child.log'
        text=log.read_text(encoding='utf-8',errors='replace')
        for p in (str(ROOT),str(Path.home())):
            text=text.replace(p,'<REDACTED_PATH>')
        log.write_text(text,encoding='utf-8',newline='\n')
        ok=rec['status']=='COMPLETED' and rec['cleanup_ok'] is True
        if not (out/'result.json').is_file():
            ok=False
        else:
            child_report=json.loads((out/'result.json').read_text())
            ok=ok and child_report['plan_sha']==PLAN_SHA and child_report['source_sha']==os.environ.get('GITHUB_SHA')
            ok=ok and child_report['execution_status']=='COMPLETED' and child_report['cleanup_ok'] is True
            ok=ok and child_report['solve_attempts']==4 and child_report['solve_successes']==4 and child_report['b0']=='PASS'
            ok=ok and child_report['snapshot_schema']==2 and child_report['snapshot_contract_sha']==SNAPSHOT_SHA
            ok=ok and judge(child_report['meshes'],require_native_snapshot=True)==child_report['judgment']
        if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>50*1024**2:
            ok=False
        (out/'supervisor.json').write_text(json.dumps(dict(status='PASS' if ok else 'FAIL',monitor=rec),indent=2)+'\n',encoding='utf-8')
        return 0 if ok else 1
    return preflight(approved)


if __name__=='__main__':
    raise SystemExit(main())
