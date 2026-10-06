"""별도 사후 확장 계획. N0/N1을 재실행하거나 기존 실패를 덮어쓰지 않는다."""
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np

import pilot as P
from judge import evaluate_device

FINE_SHA = '82f6467eb31576f97761939d998861ae7dc06d57e5978b869ab9f94bb598333a'


def preflight():
    P.require_plan()
    sha = hashlib.sha256((P.HERE/'PLAN_FINE.md').read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    if sha!=FINE_SHA:
        raise ValueError('FINE_PLAN_HASH_MISMATCH')


def evaluate(out):
    checks, metrics, problems = [],{},[]
    try:
        preflight()
        supervisor = json.loads((out/'execution.json').read_text())
        if supervisor['plan_sha256']!=FINE_SHA or supervisor['status']!='COMPLETED' or supervisor['cleanup_ok'] is not True or supervisor['exit_code']!=0:
            raise ValueError('FINE_EXECUTION_FAILED')
        raw = json.loads((out/'N2/record.json').read_text())
        if raw['plan_sha256']!=P.PLAN_SHA or raw['level']!='L2' or raw['conformity']['pass'] is not True:
            raise ValueError('FINE_IDENTITY_INVALID')
        ref = json.loads((P.T.E6K/'pn_1d_diagnostic.json').read_text())
        previous = json.loads((P.HERE/'raw/outputs/e6nd_out/result.json').read_text())
        manifest = json.loads((P.HERE/'raw/summary.json').read_text())
        old_file = P.HERE/'raw/outputs/e6nd_out/result.json'
        expected = [r for r in manifest['outputs'] if r['path']=='e6nd_out/result.json']
        if (manifest['source']['github_sha']!='0aae0a35bcfa38ceca374556199a451dd01c3076'
                or len(expected)!=1 or hashlib.sha256(old_file.read_bytes()).hexdigest()!=expected[0]['sha256']):
            raise ValueError('PREVIOUS_MESH_EVIDENCE_HASH')
        with np.load(out/'N2/arrays.npz',allow_pickle=False) as arrays, np.load(P.T.E6K/'states.npz',allow_pickle=False) as states:
            g = P.M.geometry_checks(arrays['points_um'],arrays['triangles'])
            if g['n_points']!=122761 or g['n_triangles']!=242304 or g['obtuse_triangles'] or g['degenerate_triangles'] or g['area_rel_err']>1e-12:
                raise ValueError('FINE_GEOMETRY_INVALID')
            for d in P.M.DIRECTIONS:
                cc,mm = evaluate_device(raw['devices'][d],arrays,'L2',d,ref,states,P.T)
                checks.extend({'name':'L2_'+d+'_'+c['name'],'pass':c['pass'],'value':c['value']} for c in cc)
                metrics['L2_'+d] = mm
                if (len(previous['metrics']['L1_'+d]['currents'])!=len(mm['currents'])
                        or [c['V'] for c in previous['metrics']['L1_'+d]['currents']]!=P.M.VOLTAGES[d]):
                    raise ValueError('PREVIOUS_MESH_EVIDENCE_INCOMPLETE')
                for old,new in zip(previous['metrics']['L1_'+d]['currents'],mm['currents']):
                    if old['V']!=new['V']:
                        raise ValueError('MESH_BIAS_IDENTITY')
                    diff = abs(old['J_A_per_cm2']-new['J_A_per_cm2'])/abs(new['J_A_per_cm2'])
                    checks.append({'name':'N1_N2_'+str(new['V']),'pass':bool(diff<=(.01 if d=='fwd' else .02)),'value':diff})
    except Exception as exc:
        problems.append(type(exc).__name__+': '+str(exc))
    passed = bool(checks) and not problems and all(c['pass'] is True for c in checks)
    return {'status':'FINE_PILOT_PASS' if passed else 'FINE_PILOT_NOT_APPROVED','checks':checks,'metrics':metrics,'problems':problems,'production_gate_released':False,'original_pilot_status':'PILOT_NOT_APPROVED','scope':'post-hoc third mesh diagnostic; not general PN approval'}


def main():
    preflight()
    if os.name!='nt' or os.environ.get('RUNNER_ENVIRONMENT')!='github-hosted':
        raise RuntimeError('REMOTE_WINDOWS_ONLY')
    if len(sys.argv)>1 and sys.argv[1]=='--worker':
        return P.worker(2,Path(sys.argv[2]))
    from resource_supervisor import supervise
    out = P.ROOT/'e6nd_fine_out'
    out.mkdir(exist_ok=True)
    rec = supervise([sys.executable,'-B',str(__file__),'--worker',str(out/'N2')],P.ROOT,out/'N2.log',candidate_s=900)
    rec['plan_sha256'] = FINE_SHA
    P.save(out/'execution.json',rec)
    result = evaluate(out)
    P.save(out/'result.json',result)
    print(json.dumps(result,indent=2))
    return 0 if result['status']=='FINE_PILOT_PASS' else 1


if __name__=='__main__':
    raise SystemExit(main())
