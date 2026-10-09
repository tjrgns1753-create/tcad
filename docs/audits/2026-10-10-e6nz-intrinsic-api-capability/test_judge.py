"""합성 대조군과 오류 입력만 검사. 실제 API 결과로 집계하지 않는다."""
from copy import deepcopy
import json
from judge import judge, EXPECTED, BIASES

def main():
    cases={}
    xs=[-1e-4+2e-4*i/72 for i in range(73)]
    ni=EXPECTED['n_i']; g=EXPECTED['ElectronCharge']*(EXPECTED['mu_n']+EXPECTED['mu_p'])*ni*.25
    for name,v in BIASES.items():
        i=g*v; contacts=['left','right']
        cases[name]={'voltage':v,'solves':3,'attachments':0,'state_identity':True,'params':dict(EXPECTED),
            'canonical_before':[0.]*73,'canonical_after':[0.]*73,'contacts':contacts,
            'arrays':{'x':xs,'y':[0.]*73,'Potential':[v*(x+1e-4)/2e-4 for x in xs],
                      'Electrons':[ni]*73,'Holes':[ni]*73,'Donors':[0.]*73,'Acceptors':[0.]*73,'NetDoping':[0.]*73},
            'currents':{'left':{'electron':-i*2/3,'hole':-i/3},'right':{'electron':i*2/3,'hole':i/3}},
            'result_current':{'left':-i*2/3-i/3,'right':i*2/3+i/3},
            'result_metadata':{'current_unit':'A/cm','current_normalization':'per_out_of_plane_depth','device_dimension':2},
            'devices_after':[],'meshes_after':[]}
    base={'cases':cases,'blocked':{name:{'refused':True,'solves':0,'writes':0,'resolution':'UNSUPPORTED_BY_MODEL','devices_after':[],'meshes_after':[]} for name in ('missing','unresolved')}}
    assert judge(base)['pass']
    mutations=[]
    r=deepcopy(base); del r['cases']['zero']; mutations.append(r)
    r=deepcopy(base); r['cases']['positive']['arrays']['Electrons'][0]=float('nan'); mutations.append(r)
    r=deepcopy(base); r['cases']['positive']['arrays']['Holes'][0]=0.; mutations.append(r)
    r=deepcopy(base); r['cases']['positive']['result_metadata']['current_unit']='A'; mutations.append(r)
    r=deepcopy(base); r['blocked']['unresolved']['writes']=1; mutations.append(r)
    r=deepcopy(base); r['cases']['positive']['canonical_after'][0]=None; mutations.append(r)
    r=deepcopy(base); r['cases']['positive']['currents']['right']['hole']=0.; mutations.append(r)
    assert all(not judge(r)['pass'] for r in mutations)
    print(json.dumps({'synthetic_control':'PASS','mutations_blocked':len(mutations),'engine_imports':0}))

if __name__=='__main__':
    main()
