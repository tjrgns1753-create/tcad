"""기준 GUI 표시 gate와 canonical 입력. 로컬 engine import 금지."""
import copy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in ('devsim','viennaps','viennals'):
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
from tcad.characterization import pn_reference as P
from tcad.characterization.pn_reference_view import require_pass

base,a=P.reference()
devices={}
for d in P.VOLTS:
    r=copy.deepcopy(base['devices'][d])
    r['canonical_checked']=1545
    r['x_cm']=a[d+'_x'].tolist()
    r['currents']=[{'V':c['V'],'left':c['I_min'],'right':c['I_max']} for c in r['currents']]
    r['profiles']={str(v):{nm:a[f'{d}_{v}_{nm}'].tolist() for nm in ('Potential','Electrons','Holes','ElectricField')} for v in P.SNAPS[d]}
    for nm in ('Donors','Acceptors','NetDoping','x@n0','x@n1','EdgeLength'):
        r[nm]=a[d+'_'+nm].tolist()
    devices[d]=r
checks=P.validate(devices,base,a)
assert checks and all(c['pass'] for c in checks),[c for c in checks if not c['pass']]
good={'schema':1,'status':'REFERENCE_MODEL_CHECKS_PASS','scope':P.SCOPE,'current_unit':'A/cm^2',
      'production_2d_gate_released':False,'problems':[],'devices':devices,'checks':checks}
assert require_pass(good)==checks
changes=[lambda z:z.update(checks=[]),lambda z:z.update(current_unit='A'),
         lambda z:z.update(production_2d_gate_released=True),lambda z:z.update(problems=['failed']),
         lambda z:z['devices']['rev'].update(solves=5),
         lambda z:z['devices']['rev']['profiles']['-1.0']['Holes'].__setitem__(0,float('nan')),
         lambda z:z['devices']['fwd']['currents'][0].update(left=-1.),
         lambda z:z['devices']['control'].update(cleanup_ok=False)]
for mutate in changes:
    z=copy.deepcopy(good); mutate(z)
    try:
        require_pass(z)
        raise AssertionError('FALSE_GREEN')
    except (ValueError,KeyError):
        pass
state=P.canonical()
assert state.net_doping_at(-1.,0.).net_doping==-1e17
assert state.net_doping_at(1.,0.).net_doping==1e17
assert state.net_doping_at(0.,0.).net_doping==0.
print('PASS: reference display normal + 8 rejection controls + canonical ACTIVE state; engine imports 0')
