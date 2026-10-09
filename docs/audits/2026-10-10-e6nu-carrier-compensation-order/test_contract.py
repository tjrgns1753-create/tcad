"""합성 판정기 대조군/반례. 엔진 미사용, 실제 물리 증거가 아니다."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))


def deny(event,args):
    if event == 'import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
from judge import PROFILES, CASES, EXPECTED_PARAMS, evaluate, theory
from tcad.characterization.node_fields import NodeFields, field_caption
from tcad.characterization.interface import BiasPoint, CharacterizationResult, current_unit_metadata


def main():
    records = {}
    xy = tuple((-1+(i%9)/4,-.5+(i//9)/16) for i in range(73))
    for name,profile,voltage in CASES:
        donor,acceptor = (sum(p[k] for p in PROFILES[profile]) for k in (0,1))
        th = theory(donor,acceptor,1e10,1.6e-19,400,200,.5e-4,2e-4)
        offset = .3576 if donor>=acceptor else -.3576
        fields = NodeFields('Si',xy,tuple(offset+voltage*(x+1)/2 for x,y in xy),(th['n0'],)*73,(th['p0'],)*73)
        current = th['G_A_per_V_per_cm_depth']*voltage
        result = CharacterizationResult('synthetic','none','Si','Si_xmax',
            [BiasPoint({'Si_xmax':voltage,'Si_xmin':0.},{'Si_xmax':current,'Si_xmin':-current})],current_unit_metadata(2))
        records[name] = {'profile':profile,'voltage':voltage,'steps':[list(p) for p in PROFILES[profile]],
            'canonical_query':{'donor':donor,'acceptor':acceptor,'net':donor-acceptor,'physics_status':None},
            'attachment_count':len(PROFILES[profile]),'solves':3,'device_cleanup':True,'live_api_equal':True,
            'params':dict(EXPECTED_PARAMS),'snapshot':asdict(fields),'measurement':asdict(result),
            'doping_arrays':{'Donors':[donor]*73,'Acceptors':[acceptor]*73,'NetDoping':[donor-acceptor]*73},
            'export_equal':True,'success_log_present':True,'rendered':{layer:{'nodes':73,'text':field_caption(fields,result,layer)}
                for layer in ('potential','electron','hole')}}
    records = json.loads(json.dumps(records))
    verdict = evaluate(records)
    assert verdict['pass'] is True and len(verdict['checks']) == 62, verdict
    for fault in ('lost_donor','lost_acceptor','wrong_sign','order_changed','nan','missing','unknown_query'):
        bad = deepcopy(records)
        row = bad['n_comp_da_pos']
        if fault == 'lost_donor':
            row['doping_arrays']['Donors'] = [0.]*73
        elif fault == 'lost_acceptor':
            row['canonical_query']['acceptor'] = 0.
        elif fault == 'wrong_sign':
            row['measurement']['points'][0]['currents']['Si_xmax'] *= -1
        elif fault == 'order_changed':
            bad['p_comp_da_pos']['measurement']['points'][0]['currents']['Si_xmax'] *= 1.1
        elif fault == 'nan':
            row['snapshot']['hole'] = [float('nan')]*73
        elif fault == 'missing':
            bad.pop('p_single_neg')
        else:
            row['canonical_query']['physics_status'] = {'resolution':'UNSUPPORTED_BY_MODEL'}
        assert evaluate(bad)['pass'] is False, fault
    print('PASS synthetic 62 criteria + 7 faults; actual engines/solves 0')


if __name__ == '__main__':
    main()
