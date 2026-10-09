"""무도핑 입력은 불명 상태와 다르다. 합성 결과는 실측으로 집계하지 않는다."""
from dataclasses import replace
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')
sys.addaudithook(deny)
from tcad.characterization.intrinsic import known_undoped_si,validate_intrinsic_bias,validate_intrinsic_result
from tcad.characterization.node_fields import NodeFields
from tcad.characterization.interface import BiasPoint,CharacterizationResult,current_unit_metadata
from tcad.physics.wafer_state_v2 import initialize_wafer_state,advance,attach_dopant,uniform_inventory_integral

def main():
    state=initialize_wafer_state(cells=[('Si',(-1.,1.,-.5,0.),'substrate')])
    assert known_undoped_si(state)
    for invalid in (None,advance(state,None,step_seed='etching'),replace(state,events=()),
                    replace(state,cells=(replace(state.cells[0],material='SiO2'),))):
        assert not known_undoped_si(invalid)
    for chemical in ('CHEMICAL','UNKNOWN','ACTIVE'):
        doped=attach_dopant(state,species='P',polarity='donor',chemical_state=chemical,
            concentration_at=lambda x,y:1e16,inventory_integral=uniform_inventory_integral(1e16),
            support_instance_id='substrate',support_region_um=(-1.,1.,-.5,0.),model='unit')
        assert not known_undoped_si(doped)
    params={'ElectronCharge':1.6e-19,'n_i':1e10,'mu_n':400.,'mu_p':200.}
    fields=NodeFields('Si',((-1.,-.5),(1.,-.5),(-1.,0.),(1.,0.)),(0.,.001,0.,.001),(1e10,)*4,(1e10,)*4)
    result=CharacterizationResult('unit','none','Si','arbitrary_source',
        [BiasPoint({'arbitrary_source':.001,'arbitrary_ground':0.},{'arbitrary_source':2.4e-10,'arbitrary_ground':-2.4e-10})],current_unit_metadata(2))
    args=(state,'x',.001,fields,result,params,'arbitrary_source','arbitrary_ground')
    validate_intrinsic_result(*args,source_at_max=True)
    errors=(replace(fields,electron=(0.,)*4),replace(fields,potential=(0.,)*4),replace(fields,xy_um=((-1.,-.4),(1.,-.4),(-1.,0.),(1.,0.))))
    for changed in errors:
        try: validate_intrinsic_result(state,'x',.001,changed,result,params,'arbitrary_source','arbitrary_ground',source_at_max=True)
        except ValueError: pass
        else: raise AssertionError('invalid physical fields accepted')
    for voltage in (.00101,float('nan'),float('inf')):
        try: validate_intrinsic_bias(state,'x',voltage)
        except ValueError: pass
        else: raise AssertionError('unsupported bias accepted')
    print('PASS known input, missing/unresolved/non-Si/recorded-dopant rejection, physical fields, arbitrary contact names; engine imports0')

if __name__=='__main__': main()
