"""엔진 없는 분리 계약 정상/반례. 실제 계산 증거 아님."""
from copy import deepcopy
import sys


def deny(event,args):
    if event=='import' and args[0].split('.')[0] in {'devsim','viennaps','viennals','tkinter'}:
        raise AssertionError('ENGINE_IMPORT_FORBIDDEN')


sys.addaudithook(deny)
from test_contract import synthetic_records
from judge import PROFILES, CASES
from judge_boundary import evaluate


def main():
    records=synthetic_records()
    for name,profile,voltage in CASES:
        if profile in {'n_single','p_single'}:
            continue
        nd,na=(sum(p[k] for p in PROFILES[profile]) for k in (0,1))
        q={'donor':nd,'acceptor':na,'net':nd-na,'physics_status':None}
        records[name]={'profile':profile,'voltage':voltage,'steps':[list(p) for p in PROFILES[profile]],
            'canonical_query':q,'canonical_queries_before':[q]*73,'canonical_queries_after':[q]*73,
            'attachment_count':2,'state_identity_preserved':True,'outcome':'UNSUPPORTED_BY_MODEL',
            'reason_code':'COMPENSATED_TRANSPORT_MODEL_MISSING','solves':0,'doping_writes':0,
            'field_capture_attempts':0,'measurement':None,'snapshot':None,'success_log_present':False,
            'history_delta':0,'field_nodes':{'potential':0,'electron':0,'hole':0},
            'export_dialog_calls':0,'export_created':False,'device_cleanup':True}
    verdict=evaluate(records)
    assert verdict['pass'] is True and len(verdict['checks'])==30 and verdict['actual_solves']==12,verdict
    for fault in ('missing','collapse','solve','write','fake_current','fake_field','opposite_order','wrong_reason'):
        bad=deepcopy(records)
        row=bad['n_comp_da_pos']
        if fault=='missing': bad.pop('p_comp_da_neg')
        elif fault=='collapse': row['attachment_count']=1
        elif fault=='solve': row['solves']=1
        elif fault=='write': row['doping_writes']=1
        elif fault=='fake_current': row['measurement']={'currents':{'Si_xmax':0.}}
        elif fault=='fake_field': row['snapshot']={'potential':[0.]*73}
        elif fault=='opposite_order': bad['n_comp_ad_pos']['canonical_queries_after'][0]['donor']=1e16
        else: row['reason_code']='STEP_JUNCTION_2D_MESH_CONVERGENCE_UNVERIFIED'
        assert evaluate(bad)['pass'] is False,fault
    print('PASS synthetic split contract 30 criteria + 8 faults; engines/solves 0')


if __name__=='__main__':
    main()
