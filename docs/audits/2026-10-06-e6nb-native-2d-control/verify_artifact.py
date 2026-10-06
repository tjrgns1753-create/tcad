"""원시 native 배열과 독립 연속 해석식으로 결과 재계산; 엔진 없는 verifier."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import numpy as np
import run_control as R

SOURCE_SHA='d446b93643b0b11d25f2185221bc0386344b49ce'


def close(a,b,scale=1.):
    if not math.isfinite(float(a)) or not math.isfinite(float(b)):
        raise ValueError('NONFINITE_EVIDENCE')
    if abs(a-b)>256*np.finfo(float).eps*max(abs(a),abs(b),scale):
        raise ValueError('RECALCULATION_MISMATCH')


def verify(root,expected_source=SOURCE_SHA):
    root=Path(root)
    summary=json.loads((root/'summary.json').read_text())
    if (summary['source']['github_sha']!=expected_source or summary['status']!='PASS'
            or summary['omitted_outputs'] or summary['log_truncated']):
        raise ValueError('OUTER_EVIDENCE_BLOCKED')
    if hashlib.sha256((root/'run.log').read_bytes()).hexdigest()!=summary['log']['sha256']:
        raise ValueError('LOG_HASH_MISMATCH')
    for item in summary['outputs']:
        p=root/'outputs'/item['path']
        if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256'] or p.stat().st_size!=item['bytes']:
            raise ValueError('OUTPUT_HASH_MISMATCH')
    out=root/'outputs/e6nb_out'
    report=json.loads((out/'result.json').read_text())
    monitor=json.loads((out/'supervisor.json').read_text())
    if (report['source_sha']!=expected_source or report['plan_sha']!=R.PLAN_SHA or report['b0']!='PASS'
            or report['solve_attempts']!=4 or report['solve_successes']!=4
            or report['cleanup_ok'] is not True or report['pn_approved'] is not False
            or monitor['status']!='PASS' or monitor['monitor']['cleanup_ok'] is not True):
        raise ValueError('EXECUTION_RECORD_BLOCKED')
    for label in ('positive','tensor'):
        with np.load(out/(label+'.npz'),allow_pickle=False) as z:
            a={k:z[k] for k in z.files}
        diagnostic,arrays=R.analyze(a)
        if diagnostic!=report['controls'][label]['diagnostic']:
            raise ValueError('NATIVE_DIAGNOSTIC_MISMATCH')
        if not all(np.array_equal(arrays[k],a[k]) for k in arrays):
            raise ValueError('NATIVE_ACTION_MISMATCH')
    records=[]
    for saved in report['meshes']:
        label=saved['label']
        with np.load(out/(label+'.npz'),allow_pickle=False) as z:
            a={k:z[k] for k in z.files}
        xy,t,e=R.validate(a)
        x,y=xy.T;Lx=np.ptp(x);Ly=np.ptp(y)
        # Independent continuous formula, not native Source or recorded analytic array.
        exact=np.sin(np.pi*(x-x.min())/Lx)*np.cos(np.pi*(y-y.min())/Ly)
        source=-np.pi**2*(1/Lx**2+1/Ly**2)*exact
        if not np.array_equal(exact,a['analytic']) or not np.array_equal(source,a['Source']):
            raise ValueError('CONTINUOUS_SOURCE_MISMATCH')
        v=a['Potential'];nv=a['NodeVolume'];w=a['EdgeCouple']/a['EdgeLength']
        if report.get('snapshot_schema')==2:
            if report['snapshot_contract_sha']!=R.SNAPSHOT_SHA or not np.array_equal(a['Source'],a['PrescribedSource']):
                raise ValueError('NATIVE_SOURCE_SNAPSHOT_FAIL')
            expected=(v[e[:,0]]-v[e[:,1]])/a['EdgeLength']
            if not np.all(np.isfinite(a['NativeFlux'])) or np.max(abs(a['NativeFlux']-expected))>256*np.finfo(float).eps*np.max(abs(expected)):
                raise ValueError('NATIVE_FLUX_SNAPSHOT_FAIL')
        if not np.all(np.isfinite(v)):
            raise ValueError('NONFINITE_SOLUTION')
        contacts=np.concatenate([a[k] for k in ('Si_xmin','Si_xmax')])
        free=np.ones(len(v),dtype=bool);free[contacts]=False
        for key,side in (('Si_xmin',x.min()),('Si_xmax',x.max())):
            if not np.array_equal(np.sort(a[key]),np.flatnonzero(x==side)):
                raise ValueError('CONTACT_ARRAY_MISMATCH')
        terms=[[] for _ in v]
        for edge,(i,j) in enumerate(e):
            q=float(w[edge]*(v[i]-v[j]))
            terms[int(i)].append(q);terms[int(j)].append(-q)
        residual=np.array([math.fsum([float(source[i]*nv[i]),*q]) for i,q in enumerate(terms)])
        rowmag=np.array([math.fsum([abs(float(source[i]*nv[i])),*(abs(z) for z in q)])
                         for i,q in enumerate(terms)])
        error=v-exact
        center=np.unique(x[free]);center=center[np.argmin(abs(center-(x.min()+x.max())/2))]
        rec=dict(saved,linf=float(max(abs(error))),
                 l2=math.sqrt(math.fsum(float(nv[i]*error[i]**2) for i in range(len(v)))/math.fsum(map(float,nv))),
                 residual_relative=float(max(abs(residual[free]))/max(rowmag[free])),
                 contact_error=float(max(abs(v[contacts]))),y_spread=float(np.ptp(v[x==center])),
                 h_max=float(max(a['EdgeLength'])),triangles=len(t))
        for key in ('linf','l2','contact_error','y_spread','h_max'):
            close(rec[key],saved[key])
        if rec['residual_relative']>1e-9:
            raise ValueError('INDEPENDENT_RESIDUAL_FAIL')
        records.append(rec)
    judgment=R.judge(records,require_native_snapshot=report.get('snapshot_schema')==2)
    if judgment['verdict']!=report['judgment']['verdict']:
        raise ValueError('VERDICT_MISMATCH')
    if any(k in sys.modules for k in ('devsim','viennaps','viennals')):
        raise RuntimeError('ENGINE_IMPORTED_IN_VERIFIER')
    return dict(verdict=judgment['verdict'],records=records,rates=judgment['rates'],
                outputs_verified=len(summary['outputs']),new_engine_imports=0,new_solves=0,
                source_sha=expected_source,pn_approved=False,
                source_snapshot_scope='NATIVE_VERIFIED' if report.get('snapshot_schema')==2 else 'NOT_RECORDED')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('artifact');parser.add_argument('output')
    parser.add_argument('--expected-source',default=SOURCE_SHA,help='독립적으로 확인한 실행 SHA; summary에서 추론하지 않는다')
    args=parser.parse_args();result=verify(args.artifact,args.expected_source)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='records'}),flush=True)
