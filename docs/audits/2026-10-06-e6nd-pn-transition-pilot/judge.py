"""엔진 없는 원시 증거 재계산. 누락/오류는 정상 승인하지 않는다."""
import json
import math
from pathlib import Path

import numpy as np


def evaluate_device(dr, arrays, lv, direction, reference, states, T):
    M = T.M
    checks, metrics = [], {}

    def need(name, condition, value=None):
        checks.append({'name':name,'pass':bool(condition),'value':value})

    def a(nm, size=None):
        v = np.asarray(arrays[direction+'_'+nm])
        if v.dtype.kind not in 'iuf' or not np.all(np.isfinite(v)) or (size is not None and v.shape!=(size,)):
            raise ValueError('INVALID_ARRAY:'+nm)
        return v

    if dr.get('error') is not None or dr.get('cleanup_ok') is not True:
        raise ValueError('DEVICE_ERROR_OR_CLEANUP')
    x,y = a('x'),a('y')
    n = len(x)
    if x.ndim!=1 or y.shape!=x.shape or type(dr.get('node_count')) is not int or dr['node_count']!=n:
        raise ValueError('NODE_COUNT_MISMATCH')
    M.require_canonical(dr['canonical_audit'],n)
    need('gate',dr['gate']['reason_code']==T.J.GATE_REASON and dr['gate']['resolution']=='UNSUPPORTED_BY_MODEL' and dr['gate_counts']=={'writes':0,'attempts':0})
    need('solve_counts',all(type(dr.get(k)) is int and dr[k]==v for k,v in {'solve_attempts':2+len(M.VOLTAGES[direction]),'solves':2+len(M.VOLTAGES[direction]),'solve_failures':0,'snapshot_failures':0}.items()))
    md = dr['metadata']
    need('units',md.get('current_unit')=='A/cm' and md.get('current_normalization')=='per_out_of_plane_depth' and type(md.get('device_dimension')) is int and md['device_dimension']==2)
    rp = reference['reference_parameters']
    need('parameters',all(math.isfinite(dr['params'][k]) and math.isclose(dr['params'][k],rp[T.J.REF_OF[k]],rel_tol=1e-12,abs_tol=0) for k in T.J.PARAMS))
    need('doping_arrays',np.array_equal(a('Donors',n),M.N_DOP*(x>=0)) and np.array_equal(a('Acceptors',n),M.N_DOP*(x<=0)) and np.array_equal(a('NetDoping',n),M.N_DOP*((x>=0)*1-(x<=0)*1)))
    p,t = arrays['points_um'],arrays['triangles']
    imported = a('elements')
    if imported.dtype.kind not in 'iu' or imported.shape!=t.shape or np.any(imported<0) or np.any(imported>=n):
        raise ValueError('ELEMENTS_INVALID')
    xy = np.column_stack((x,y))
    order, target = np.lexsort((y,x)), np.lexsort((p[:,1],p[:,0]))
    if len(p)!=n or len(np.unique(xy,axis=0))!=n or not np.all(np.abs(xy[order]-p[target,:2]*1e-4)<=[4e-15,1e-17]):
        raise ValueError('COORDINATE_MAPPING_INVALID')
    mapping = np.empty(n,dtype=int)
    mapping[order] = target
    sortrows = lambda z: np.array(sorted(map(tuple,np.sort(z,axis=1))))
    need('topology',np.array_equal(sortrows(mapping[imported]),sortrows(t)))
    need('volume',np.all(a('NodeVolume',n)>=0) and abs(math.fsum(a('NodeVolume',n))/(M.L_CM*M.H_CM)-1)<=1e-12 and dr['area_gate']['pass'] is True)
    for contact,xx in [(T.C_MIN,-.002),(T.C_MAX,.002)]:
        idx = np.asarray(dr['contacts'][contact])
        if idx.dtype.kind not in 'iu' or idx.ndim!=1 or not len(idx) or np.any(idx<0) or np.any(idx>=n):
            raise ValueError('CONTACT_INDICES')
        need(contact,np.array_equal(np.sort(idx),np.flatnonzero(x==xx)) and min(y[idx])==-M.H_CM and max(y[idx])==0)
    currents = dr['currents']
    if len(currents)!=len(M.VOLTAGES[direction]):
        raise ValueError('CURRENTS_INCOMPLETE')
    metrics['currents'] = []
    for c,v in zip(currents,M.VOLTAGES[direction]):
        if any(type(c[k]) not in (int,float) or not math.isfinite(c[k]) for k in ('V','I_min','I_max')) or c['V']!=v:
            raise ValueError('CURRENT_INVALID')
        c1 = [q for q in reference['devices'][lv+'_'+direction]['currents'] if q['V']==v]
        if len(c1)!=1 or c1[0]['I_l']==0 or c['I_min']==0:
            raise ValueError('REFERENCE_INVALID')
        j = c['I_min']/M.H_CM
        rel = abs(j-c1[0]['I_l'])/abs(c1[0]['I_l'])
        kcl = abs(c['I_min']+c['I_max'])/abs(c['I_min'])
        need(f'current_{v}',rel<=(.01 if direction=='fwd' else .02) and j*v>0 and kcl<=1e-3)
        metrics['currents'].append({'V':v,'J_A_per_cm2':j,'reference_rel':rel,'kcl_rel':kcl})
    need('monotonic',bool(np.all(np.diff(np.abs([c['I_min'] for c in currents]))>0)))
    ex0,ex1,ey0,ey1,length = [a(nm) for nm in ('x@n0','x@n1','y@n0','y@n1','EdgeLength')]
    if any(z.shape!=length.shape for z in (ex0,ex1,ey0,ey1)) or np.any(length<=0):
        raise ValueError('EDGE_GEOMETRY_INVALID')
    coordinate_ids = {tuple(v):i for i,v in enumerate(xy)}
    try:
        e0 = np.array([coordinate_ids[(xx,yy)] for xx,yy in zip(ex0,ey0)])
        e1 = np.array([coordinate_ids[(xx,yy)] for xx,yy in zip(ex1,ey1)])
    except KeyError as exc:
        raise ValueError('EDGE_ENDPOINT_NOT_NODE') from exc
    native_length = np.hypot(ex1-ex0,ey1-ey0)
    need('edge_length',np.allclose(length,native_length,rtol=1e-12,atol=0))
    horizontal = (ey0==ey1)&(ex0!=ex1)
    if not np.any(horizontal):
        raise ValueError('HORIZONTAL_EDGES_MISSING')
    metrics['profiles'] = []
    for v in M.SNAP_BIASES[direction]:
        r = M.e6k_snapshot(states,lv,direction,v)
        rx = r['x']
        if np.any(np.diff(rx)<=0) or min(x)<min(rx) or max(x)>max(rx):
            raise ValueError('REFERENCE_SUPPORT_INVALID')
        values = {nm:a(f'{v}_{nm}',n if nm!='ElectricField' else len(length)) for nm in M.SNAP_ARRAYS}
        psi = values['Potential']
        need(f'native_field_relation_{v}',np.allclose(values['ElectricField'],(psi[e0]-psi[e1])/length,rtol=1e-9,atol=1e-7))
        err = float(np.max(np.abs(psi-np.interp(x,rx,r['Potential']))))
        spread = max(float(np.ptp(psi[x==xx])) for xx in np.unique(x))
        carriers = {}
        for nm in ('Electrons','Holes'):
            if np.any(values[nm]<=0) or np.any(r[nm]<=0):
                raise ValueError('NONPOSITIVE_CARRIER')
            rr = np.exp(np.interp(x,rx,np.log(r[nm])))
            carriers[nm] = float(np.max(np.abs(values[nm]-rr)/rr))
        expected = (np.interp(ex0,rx,r['Potential'])-np.interp(ex1,rx,r['Potential']))/length
        denom = float(np.max(np.abs(expected[horizontal])))
        if denom<=0:
            raise ValueError('ZERO_FIELD_REFERENCE')
        field = float(np.max(np.abs(values['ElectricField'][horizontal]-expected[horizontal]))/denom)
        need(f'profile_{v}',err<=.01*dr['params']['V_t'] and spread<=1e-5 and max(carriers.values())<=.01 and field<=.02)
        metrics['profiles'].append({'V':v,'potential_max_V':err,'y_spread_V':spread,'carriers_relative':carriers,'field_peak_normalized':field})
    return checks,metrics


def judge(out):
    import pilot as T
    checks, metrics, problems = [],{},[]
    try:
        T.require_plan()
        execution = json.loads((out/'execution.json').read_text(encoding='utf-8'))
        if execution['plan_sha256']!=T.PLAN_SHA or len(execution['supervisors'])!=2 or any(s['status']!='COMPLETED' or s['cleanup_ok'] is not True or s.get('exit_code')!=0 for s in execution['supervisors']):
            raise ValueError('EXECUTION_INCOMPLETE')
        refs = json.loads((T.T.E6K/'pn_1d_diagnostic.json').read_text())
        with np.load(T.T.E6K/'states.npz',allow_pickle=False) as states:
            for k,lv in enumerate(('L0','L1')):
                raw = json.loads((out/f'N{k}/record.json').read_text())
                if raw['level']!=lv or raw['plan_sha256']!=T.PLAN_SHA or raw['conformity']['pass'] is not True:
                    raise ValueError('IDENTITY_OR_CONFORMITY')
                with np.load(out/f'N{k}/arrays.npz',allow_pickle=False) as arrays:
                    g = T.M.geometry_checks(arrays['points_um'],arrays['triangles'])
                    if g['obtuse_triangles'] or g['degenerate_triangles'] or g['area_rel_err']>1e-12:
                        raise ValueError('GEOMETRY_INVALID')
                    for direction in T.M.DIRECTIONS:
                        cc, mm = evaluate_device(raw['devices'][direction],arrays,lv,direction,refs,states,T.T)
                        checks.extend({'name':lv+'_'+direction+'_'+c['name'],**{a:b for a,b in c.items() if a!='name'}} for c in cc)
                        metrics[lv+'_'+direction] = mm
        for direction in T.M.DIRECTIONS:
            for c0,c1 in zip(metrics['L0_'+direction]['currents'],metrics['L1_'+direction]['currents']):
                rel = abs(c0['J_A_per_cm2']-c1['J_A_per_cm2'])/abs(c1['J_A_per_cm2'])
                checks.append({'name':'mesh_'+str(c0['V']),'pass':bool(rel<=(.01 if direction=='fwd' else .02)),'value':rel})
    except Exception as exc:
        problems.append(type(exc).__name__+': '+str(exc))
    passed = not problems and bool(checks) and all(c['pass'] is True for c in checks)
    return {'status':'PILOT_PASS' if passed else 'PILOT_NOT_APPROVED','checks':checks,'metrics':metrics,'problems':problems,'production_gate_released':False,'scope':'two-level symmetric Si PN audit; not general PN approval'}
