"""수렴 판정기의 합성 대조군. 실제 해를 생성하거나 승인하지 않는다."""
import copy
import json
import sys


def deny(event,args):
    if event=='import' and args[0].split('.')[0] in ('devsim','viennaps','viennals'):
        raise AssertionError('LOCAL_ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
import convergence as F
import numpy as np

assert F.preflight()==F.PLAN_SHA
with np.load(F.DATA/'arrays.npz',allow_pickle=False) as z:
    coarse={k:z[k].copy() for k in z.files}
old=json.loads((F.DATA/'record.json').read_text())
raw={'plan_sha256':F.PLAN_SHA,'source_hashes':F.INPUT_SHA,'devices':{}}
fine={}
for d in F.C.P.M.DIRECTIONS:
    ox=coarse[d+'_x']
    order=np.argsort(ox)
    x=F.refine(ox[order])
    fine[d+'_x'],fine[d+'_y']=x,np.zeros(len(x))
    fine[d+'_NodeVolume']=np.r_[np.diff(x)[0]/2,(x[2:]-x[:-2])/2,np.diff(x)[-1]/2]
    fine[d+'_Donors']=1e17*(x>=0)
    fine[d+'_Acceptors']=1e17*(x<=0)
    fine[d+'_NetDoping']=fine[d+'_Donors']-fine[d+'_Acceptors']
    fine[d+'_x@n0'],fine[d+'_x@n1'],fine[d+'_EdgeLength']=x[:-1],x[1:],np.diff(x)
    rec=copy.deepcopy(old['devices'][d])
    rec['nodes']=3089
    rec['canonical_audit']['canonical_checked']=3089
    raw['devices'][d]=rec
    for v in F.C.P.M.SNAP_BIASES[d]:
        for nm in ('Potential','Electrons','Holes'):
            fine[f'{d}_{v}_{nm}']=np.interp(x,ox[order],coarse[f'{d}_{v}_{nm}'][order])
        p=fine[f'{d}_{v}_Potential']
        fine[f'{d}_{v}_ElectricField']=(p[:-1]-p[1:])/np.diff(x)
checks,_=F.compare(raw,fine,old,coarse)
assert len(checks)==19 and all(c['pass'] for c in checks)
def rejected(r,a):
    try:
        cc,_=F.compare(r,a,old,coarse)
        assert not all(c['pass'] for c in cc), 'FALSE_PASS'
    except ValueError:
        pass
mutations=[('canonical',lambda r:r['devices']['fwd']['canonical_audit'].update(canonical_unresolved=1)),
           ('solve',lambda r:r['devices']['rev'].update(solves=5)),
           ('cleanup',lambda r:r['devices']['rev'].update(cleanup_ok=False)),
           ('metadata',lambda r:r['devices']['fwd']['metadata'].update(current_unit='A')),
           ('missing_current',lambda r:r['devices']['rev']['currents'].pop()),
           ('plan',lambda r:r.update(plan_sha256='0'*64))]
for name,change in mutations:
    r=copy.deepcopy(raw)
    change(r)
    rejected(r,fine)
for name,key,value in [('coordinate','fwd_x',np.nextafter(fine['fwd_x'][3],np.inf)),
                       ('dopant','fwd_NetDoping',0.),
                       ('carrier','rev_-1.0_Holes',np.nan),
                       ('field','fwd_0.6_ElectricField',np.nan)]:
    a=dict(fine)
    a[key]=fine[key].copy()
    a[key][3]=value
    rejected(raw,a)
for bad in (np.full(1545,np.nan),np.zeros(1545)):
    try:
        F.refine(bad)
        raise AssertionError('BAD_GRID_ACCEPTED')
    except ValueError:
        pass
print('PASS: synthetic normal control, 10 evidence mutations, 2 invalid grids; engine imports 0')
