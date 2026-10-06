"""보존된 데이터의 합성 정상/손상 입력. 실제 물리 결과를 생성하지 않는다."""
import copy
import json
import math
import sys
from unittest.mock import patch

import numpy as np

import common as C
import matched_judge as J


def fixture():
    with np.load(C.DATA/'arrays.npz',allow_pickle=False) as archive:
        source = {k:np.array(archive[k],copy=True) for k in archive.files}
    original = json.loads((C.DATA/'record.json').read_text())
    x = C.unique_source_x(source)
    volumes = np.r_[np.diff(x)/2,0]+np.r_[0,np.diff(x)/2]
    raw = {'plan_sha256':C.PLAN_SHA,'source_hashes':C.INPUT_SHA,'new_2d_solves':0,'production_gate_released':False,'devices':{}}
    arrays = {}
    for d in ('control','fwd','rev'):
        params = dict(original['devices']['fwd']['params'])
        count = 3 if d=='control' else 2+len(C.P.M.VOLTAGES[d])
        dr = {'error':None,'cleanup_ok':True,'nodes':1545,'dimension':1,'solve_attempts':count,'solves':count,'solve_failures':0,'snapshot_failures':0,'canonical_audit':{'canonical_checked':1545,'canonical_unresolved':0,'canonical_mismatch':0},'metadata':{'device_dimension':1,'current_unit':None,'current_normalization':None},'params':params,'doping_writes_before_solve':[[action,nm] for action in ('node_model','set_node_values') for nm in ('Donors','Acceptors','NetDoping')]}
        raw['devices'][d] = dr
        arrays[d+'_x'],arrays[d+'_y'],arrays[d+'_NodeVolume'] = x.copy(),np.zeros(1545),volumes.copy()
        donors,acceptors = (np.full(1545,1e16),np.zeros(1545)) if d=='control' else (1e17*(x>=0),1e17*(x<=0))
        for nm,val in [('Donors',donors),('Acceptors',acceptors),('NetDoping',donors-acceptors)]:
            arrays[d+'_'+nm] = val
        arrays[d+'_x@n0'],arrays[d+'_x@n1'],arrays[d+'_EdgeLength'] = x[:-1],x[1:],np.diff(x)
        if d=='control':
            ni = params['n_i']
            n0 = (1e16+math.sqrt(1e32+4*ni*ni))/2
            theory = params['ElectronCharge']*(params['mu_n']*n0+params['mu_p']*ni*ni/n0)*.001/.004
            dr['currents'] = [{'V':.001,'I_min':theory,'I_max':-theory}]
        else:
            dr['currents'] = [{'V':q['V'],'I_min':q['I_min']/C.P.M.H_CM,'I_max':q['I_max']/C.P.M.H_CM} for q in original['devices'][d]['currents']]
            index = C.matched_indices(x,source[d+'_x'])
            counts = np.bincount(index,minlength=1545)
            e0,e1 = [C.matched_indices(x,source[d+'_'+nm]) for nm in ('x@n0','x@n1')]
            for v in C.P.M.SNAP_BIASES[d]:
                for nm in ('Potential','Electrons','Holes'):
                    # 명시적인 합성 y-균일 정상 fixture. 실제 원시 배열은 수정하지 않는다.
                    val = np.bincount(index,weights=source[f'{d}_{v}_{nm}'],minlength=1545)/counts
                    arrays[f'{d}_{v}_{nm}'] = val
                    source[f'{d}_{v}_{nm}'] = val[index]
                psi = arrays[f'{d}_{v}_Potential']
                arrays[f'{d}_{v}_ElectricField'] = (psi[:-1]-psi[1:])/np.diff(x)
                source[f'{d}_{v}_ElectricField'] = (psi[e0]-psi[e1])/source[d+'_EdgeLength']
    return raw,arrays,original,source


def main():
    def forbid(event,args):
        if event=='import' and args[0].split('.')[0] in ('devsim','viennaps'):
            raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
    sys.addaudithook(forbid)
    calls = []
    C.preflight(lambda:calls.append('valid'))
    for target,name,bad in [(C,'PLAN_SHA','0'*64),(C,'INPUT_SHA',{k:'0'*64 for k in C.INPUT_SHA})]:
        with patch.object(target,name,bad):
            try:
                C.preflight(lambda:calls.append('invalid'))
                raise AssertionError('BAD_PREFLIGHT_ACCEPTED')
            except ValueError:
                pass
    assert calls==['valid']
    raw,arrays,original,source = fixture()
    result = J.compare(raw,arrays,original,source)
    assert result['checks'] and all(c['pass'] for c in result['checks']),[c for c in result['checks'] if not c['pass']]
    mutations = [lambda r:r['devices']['rev']['canonical_audit'].update(canonical_unresolved=1),lambda r:r['devices']['fwd'].update(nodes=True),lambda r:r['devices']['rev'].update(solves=5),lambda r:r['devices']['control'].update(cleanup_ok=False),lambda r:r['devices']['control']['currents'][0].update(I_min=1),lambda r:r['devices']['fwd']['metadata'].update(current_unit='A'),lambda r:r['devices']['rev']['currents'].pop(),lambda r:r.update(new_2d_solves=1),lambda r:r.update(production_gate_released=True)]
    tested = 0
    for mutate in mutations:
        changed = copy.deepcopy(raw)
        mutate(changed)
        try:
            res = J.compare(changed,arrays,original,source)
            assert not all(c['pass'] for c in res['checks'])
        except (ValueError,KeyError):
            pass
        tested += 1
    for key,value in [('rev_x',np.nextafter(arrays['rev_x'][0],np.inf)),('rev_-1.0_Holes',0),('fwd_0.6_ElectricField',float('nan')),('rev_EdgeLength',0),('rev_NetDoping',1)]:
        changed = {k:np.array(v,copy=True) for k,v in arrays.items()}
        changed[key][0] = value
        try:
            res = J.compare(raw,changed,original,source)
            assert not all(c['pass'] for c in res['checks'])
        except (ValueError,KeyError):
            pass
        tested += 1
    altered = copy.deepcopy(raw)
    altered['devices']['rev']['currents'][0]['V'] = -.3
    try:
        J.compare(altered,arrays,original,source)
        raise AssertionError('BIAS_CHANGE_ACCEPTED')
    except ValueError:
        tested += 1
    print('PASS: synthetic normal control,',tested,'negative controls, 2 preflight traps; engine imports 0')


if __name__=='__main__':
    main()
