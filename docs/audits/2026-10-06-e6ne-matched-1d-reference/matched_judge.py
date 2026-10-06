"""원시 배열에서 보간 없는 동일 x PN 비교. 엔진을 호출하지 않는다."""
import json
import math
from pathlib import Path

import numpy as np

import common as C


def number(v):
    return type(v) in (int,float) and math.isfinite(v)


def arr(arrays,key,size=None,positive=False):
    v = np.asarray(arrays[key])
    if (v.dtype.kind not in 'if' or v.ndim!=1 or not np.all(np.isfinite(v))
            or (size is not None and v.shape!=(size,)) or (positive and np.any(v<=0))):
        raise ValueError('INVALID_ARRAY:'+key)
    return v


def device_contract(dr,arrays,kind,x):
    if dr.get('error') is not None or dr.get('cleanup_ok') is not True:
        raise ValueError('DEVICE_ERROR_OR_CLEANUP:'+kind)
    expected = 3 if kind=='control' else 2+len(C.P.M.VOLTAGES[kind])
    for name,want in {'nodes':1545,'dimension':1,'solve_attempts':expected,'solves':expected,'solve_failures':0,'snapshot_failures':0}.items():
        if type(dr.get(name)) is not int or dr[name]!=want:
            raise ValueError('DEVICE_COUNT_OR_DIMENSION:'+kind+':'+name)
    C.P.M.require_canonical(dr['canonical_audit'],1545)
    actual = arr(arrays,kind+'_x',1545)
    if len(np.unique(actual))!=1545 or not np.array_equal(np.sort(actual),x):
        raise ValueError('REFERENCE_GRID_CHANGED')
    C.matched_indices(x,actual)
    if not np.all(arr(arrays,kind+'_y',1545)==0):
        raise ValueError('NOT_1D_Y')
    volumes = arr(arrays,kind+'_NodeVolume',1545)
    if np.any(volumes<0) or abs(math.fsum(volumes)/.004-1)>1e-12:
        raise ValueError('1D_VOLUME_LENGTH_MISMATCH')
    donors,acceptors = (np.full(1545,1e16),np.zeros(1545)) if kind=='control' else (1e17*(actual>=0),1e17*(actual<=0))
    for nm,values in [('Donors',donors),('Acceptors',acceptors),('NetDoping',donors-acceptors)]:
        if not np.array_equal(arr(arrays,kind+'_'+nm,1545),values):
            raise ValueError('ACTUAL_DOPING_MISMATCH:'+kind+':'+nm)
    expected_writes = [('node_model',nm) for nm in ('Donors','Acceptors','NetDoping')]+[('set_node_values',nm) for nm in ('Donors','Acceptors','NetDoping')]
    writes = dr['doping_writes_before_solve']
    if sorted(map(tuple,writes))!=sorted(expected_writes):
        raise ValueError('PRODUCTION_DOPING_WRITES_MISSING')
    md = dr['metadata']
    if type(md.get('device_dimension')) is not int or md['device_dimension']!=1 or md.get('current_unit') is not None or md.get('current_normalization') is not None:
        raise ValueError('1D_PRODUCTION_METADATA_CHANGED')
    if not all(number(dr['params'].get(k)) for k in C.P.T.J.PARAMS+('V_t',)):
        raise ValueError('PHYSICS_PARAMETERS_MISSING')
    volts = [.001] if kind=='control' else C.P.M.VOLTAGES[kind]
    currents = dr['currents']
    if len(currents)!=len(volts) or any(not all(number(c.get(k)) for k in ('V','I_min','I_max')) or c['V']!=v for c,v in zip(currents,volts)):
        raise ValueError('CURRENTS_MISSING_OR_INVALID')
    e0,e1,ell = [arr(arrays,kind+'_'+nm,1544) for nm in ('x@n0','x@n1','EdgeLength')]
    C.matched_indices(x,e0)
    C.matched_indices(x,e1)
    if np.any(ell<=0) or not np.allclose(ell,abs(e1-e0),rtol=1e-12,atol=0):
        raise ValueError('EDGE_LENGTH_MISMATCH')
    pairs = np.sort(np.column_stack((e0,e1)),axis=1)
    pairs = pairs[np.argsort(pairs[:,0])]
    if not np.array_equal(pairs,np.column_stack((x[:-1],x[1:]))):
        raise ValueError('1D_EDGE_TOPOLOGY_MISMATCH')
    return np.argsort(actual)


def unit_control(dr,arrays,x):
    device_contract(dr,arrays,'control',x)
    p = dr['params']
    ni = p['n_i']
    n0 = (1e16+math.sqrt(1e32+4*ni*ni))/2
    p0 = ni*ni/n0
    sigma = p['ElectronCharge']*(p['mu_n']*n0+p['mu_p']*p0)
    theory = sigma*.001/(x[-1]-x[0])
    c = dr['currents'][0]
    if theory<=0 or c['I_min']==0:
        raise ValueError('UNIT_CONTROL_INVALID_REFERENCE')
    relative = abs(c['I_min']-theory)/abs(theory)
    kcl = abs(c['I_min']+c['I_max'])/abs(c['I_min'])
    return {'pass':bool(relative<=1e-6 and kcl<=1e-6),'relative':relative,'kcl_relative':kcl,
            'J_theory_A_per_cm2':theory,'I_min_raw':c['I_min'],
            'audit_unit':'A/cm^2' if relative<=1e-6 and kcl<=1e-6 else None,
            'production_metadata_unit_unchanged':None}


def compare(raw,reference,source_raw,source_arrays):
    x = C.unique_source_x(source_arrays)
    if raw.get('plan_sha256')!=C.PLAN_SHA or raw.get('source_hashes')!=C.INPUT_SHA or type(raw.get('new_2d_solves')) is not int or raw['new_2d_solves']!=0 or raw.get('production_gate_released') is not False:
        raise ValueError('REFERENCE_IDENTITY_CHANGED')
    unit = unit_control(raw['devices']['control'],reference,x)
    if unit['pass'] is not True:
        raise ValueError('UNIT_CONTROL_NOT_ESTABLISHED')
    checks,metrics = [],{}
    def need(name,ok,value=None):
        checks.append({'name':name,'pass':bool(ok),'value':value})
    for d in C.P.M.DIRECTIONS:
        dr,original = raw['devices'][d],source_raw['devices'][d]
        order = device_contract(dr,reference,d,x)
        x2,y2 = [arr(source_arrays,d+'_'+nm,122761) for nm in ('x','y')]
        match = C.matched_indices(x,x2)
        C.P.M.require_canonical(original['canonical_audit'],122761)
        if original['error'] is not None or original['cleanup_ok'] is not True or original['gate_counts']!={'writes':0,'attempts':0} or original['gate']['reason_code']!=C.P.T.J.GATE_REASON:
            raise ValueError('ORIGINAL_2D_GATE_OR_DEVICE_ERROR')
        md = original['metadata']
        if md.get('current_unit')!='A/cm' or md.get('current_normalization')!='per_out_of_plane_depth' or md.get('device_dimension')!=2:
            raise ValueError('ORIGINAL_2D_UNIT_UNKNOWN')
        need(d+'_parameters',all(number(original['params'].get(k)) and math.isclose(dr['params'][k],original['params'][k],rel_tol=1e-12,abs_tol=0) for k in C.P.T.J.PARAMS+('V_t',)))
        if len(original['currents'])!=len(dr['currents']):
            raise ValueError('ORIGINAL_CURRENT_INCOMPLETE')
        currents = []
        for ref,c2,v in zip(dr['currents'],original['currents'],C.P.M.VOLTAGES[d]):
            if c2['V']!=v or any(not number(c2.get(k)) for k in ('V','I_min','I_max')) or ref['I_min']==0 or c2['I_min']==0:
                raise ValueError('CURRENT_BIAS_OR_FINITE_CONTRACT')
            j2 = c2['I_min']/C.P.M.H_CM
            relative = abs(j2-ref['I_min'])/abs(ref['I_min'])
            kcl1 = abs(ref['I_min']+ref['I_max'])/abs(ref['I_min'])
            kcl2 = abs(c2['I_min']+c2['I_max'])/abs(c2['I_min'])
            need(f'{d}_current_{v}',relative<=(.01 if d=='fwd' else .02) and max(kcl1,kcl2)<=1e-3 and j2*v>0 and ref['I_min']*v>0)
            currents.append({'V':v,'J_2D_A_per_cm2':j2,'J_1D_A_per_cm2':ref['I_min'],'relative':relative,'kcl_1d':kcl1,'kcl_2d':kcl2})
        need(d+'_monotonic',np.all(np.diff(np.abs([c['J_1D_A_per_cm2'] for c in currents]))>0) and np.all(np.diff(np.abs([c['J_2D_A_per_cm2'] for c in currents]))>0))
        ex0,ex1,ey0,ey1,ell = [arr(source_arrays,d+'_'+nm) for nm in ('x@n0','x@n1','y@n0','y@n1','EdgeLength')]
        if any(a.shape!=ell.shape for a in (ex0,ex1,ey0,ey1)) or np.any(ell<=0):
            raise ValueError('2D_EDGE_GEOMETRY_INVALID')
        m0,m1 = C.matched_indices(x,ex0),C.matched_indices(x,ex1)
        horizontal = (ey0==ey1)&(ex0!=ex1)
        if not np.any(horizontal):
            raise ValueError('NO_HORIZONTAL_2D_EDGE')
        re0,re1,rell = [arr(reference,d+'_'+nm,1544) for nm in ('x@n0','x@n1','EdgeLength')]
        r0,r1 = C.matched_indices(x,re0),C.matched_indices(x,re1)
        yorder = np.argsort(x2,kind='stable')
        starts = np.r_[0,np.flatnonzero(np.diff(x2[yorder]))+1]
        profiles = []
        for v in C.P.M.SNAP_BIASES[d]:
            values1 = {nm:arr(reference,f'{d}_{v}_{nm}',1545 if nm!='ElectricField' else 1544,positive=nm in ('Electrons','Holes')) for nm in C.P.M.SNAP_ARRAYS}
            values2 = {nm:arr(source_arrays,f'{d}_{v}_{nm}',len(x2) if nm!='ElectricField' else len(ell),positive=nm in ('Electrons','Holes')) for nm in C.P.M.SNAP_ARRAYS}
            psi1 = values1['Potential'][order]
            need(f'{d}_native_1d_field_{v}',np.allclose(values1['ElectricField'],(psi1[r0]-psi1[r1])/rell,rtol=1e-9,atol=1e-7))
            psi_error = float(np.max(np.abs(values2['Potential']-psi1[match])))
            psi_sorted = values2['Potential'][yorder]
            spread = float(np.max(np.maximum.reduceat(psi_sorted,starts)-np.minimum.reduceat(psi_sorted,starts)))
            carriers = {}
            locations = {}
            for nm in ('Electrons','Holes'):
                expected = values1[nm][order][match]
                relative = np.abs(values2[nm]-expected)/expected
                imax = int(np.argmax(relative))
                carriers[nm] = float(relative[imax])
                locations[nm] = [float(x2[imax]*1e4),float(y2[imax]*1e4)]
            expected_field = (psi1[m0]-psi1[m1])/ell
            denominator = float(np.max(np.abs(expected_field[horizontal])))
            if denominator<=0:
                raise ValueError('ZERO_REFERENCE_FIELD')
            field_error = float(np.max(np.abs(values2['ElectricField'][horizontal]-expected_field[horizontal]))/denominator)
            need(f'{d}_profile_{v}',psi_error<=.01*dr['params']['V_t'] and spread<=1e-5 and max(carriers.values())<=.01 and field_error<=.02)
            profiles.append({'V':v,'potential_max_V':psi_error,'y_spread_V':spread,'carriers_relative':carriers,'carrier_max_location_um':locations,'field_peak_normalized':field_error})
        metrics[d] = {'currents':currents,'profiles':profiles}
    return {'unit_control':unit,'checks':checks,'metrics':metrics}


def judge(out):
    problems,checks,metrics,unit = [],[],{},None
    try:
        C.preflight()
        execution = json.loads((out/'execution.json').read_text())
        if execution['plan_sha256']!=C.PLAN_SHA or execution['status']!='COMPLETED' or execution['cleanup_ok'] is not True or execution['exit_code']!=0:
            raise ValueError('REFERENCE_EXECUTION_INCOMPLETE')
        raw = json.loads((out/'reference/record.json').read_text())
        original = json.loads((C.DATA/'record.json').read_text())
        with np.load(out/'reference/arrays.npz',allow_pickle=False) as reference,np.load(C.DATA/'arrays.npz',allow_pickle=False) as source:
            result = compare(raw,reference,original,source)
            checks,metrics,unit = result['checks'],result['metrics'],result['unit_control']
    except Exception as exc:
        problems.append(type(exc).__name__+': '+str(exc))
    passed = bool(checks) and not problems and all(c['pass'] is True for c in checks)
    return {'status':'MATCHED_REFERENCE_PASS' if passed else 'MATCHED_REFERENCE_NOT_APPROVED','unit_control':unit,'checks':checks,'metrics':metrics,'problems':problems,'production_gate_released':False,'new_2d_solves':0,'scope':'exact-x consistency for symmetric PN only; not general PN or fabrication validation'}
