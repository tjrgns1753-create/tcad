"""수치 지원과 transport 거절을 서로 바꿔 통과시킬 수 없는 분리 판정."""
from judge import CASES, PROFILES, evaluate as evaluate_numeric, require
NORMAL_CASES = tuple(row for row in CASES if row[1] in {'n_single','p_single'})


def evaluate(records):
    try:
        require(set(records)=={row[0] for row in CASES},'CASE_SET')
        normal={name:records[name] for name,_,_ in NORMAL_CASES}
        verdict=evaluate_numeric(normal,NORMAL_CASES)
        require(verdict['pass'] is True,'SUPPORTED_NUMERIC_CRITERIA')
        checks=list(verdict['checks'])
        for name,profile,voltage in CASES:
            if profile in {'n_single','p_single'}:
                continue
            r=records[name]
            nd,na=(sum(p[k] for p in PROFILES[profile]) for k in (0,1))
            expected={'donor':nd,'acceptor':na,'net':nd-na,'physics_status':None}
            require(r['profile']==profile and r['voltage']==voltage and r['steps']==[list(p) for p in PROFILES[profile]],'DECLARATION_SEQUENCE')
            require(r['canonical_query']==expected and r['canonical_queries_before']==[expected]*73 and
                    r['canonical_queries_after']==[expected]*73 and r['attachment_count']==2 and r['state_identity_preserved'] is True,'CONCENTRATION_PRESERVATION')
            require(r['outcome']=='UNSUPPORTED_BY_MODEL' and r['reason_code']=='COMPENSATED_TRANSPORT_MODEL_MISSING','TRANSPORT_REASON')
            require(r['solves']==0 and r['doping_writes']==0 and r['field_capture_attempts']==0,'NO_BACKEND_NUMBERS')
            require(r['measurement'] is None and r['snapshot'] is None and r['success_log_present'] is False and
                    r['history_delta']==0 and r['field_nodes']=={'potential':0,'electron':0,'hole':0},'NO_NUMERIC_GUI_RESULT')
            require(r['export_dialog_calls']==0 and r['export_created'] is False and r['device_cleanup'] is True,'NO_STALE_EXPORT_OR_DEVICE')
            checks.append({'name':name+'_truthful_transport_refusal','pass':True})
        for sign in ('pos','neg'):
            for label,a,b in (('n_order','n_comp_da','n_comp_ad'),('p_order','p_comp_ad','p_comp_da')):
                ra,rb=records[a+'_'+sign],records[b+'_'+sign]
                require(ra['canonical_queries_after']==rb['canonical_queries_after'] and ra['reason_code']==rb['reason_code'],'ORDER_PRESERVATION')
                checks.append({'name':label+'_'+sign+'_concentrations_and_refusal','pass':True})
        return {'pass':all(c['pass'] for c in checks),'checks':checks,'numeric_metrics':verdict['metrics'],
                'numeric_cases':4,'blocked_cases':8,'actual_solves':sum(r['solves'] for r in records.values())}
    except (KeyError,IndexError,ValueError,TypeError,ZeroDivisionError,OverflowError) as error:
        return {'pass':False,'error':str(error)}
