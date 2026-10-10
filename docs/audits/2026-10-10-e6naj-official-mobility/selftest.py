"""엔진 없이 capability 판정기의 false-green 경계를 검사한다."""
import copy
import sys
from judge import judge, EXPECTED, MODELS


def forbid(event, args):
    if event == 'import' and args[0].split('.')[0] in {'devsim', 'viennaps', 'viennals'}:
        raise RuntimeError('ENGINE_FORBIDDEN')


sys.addaudithook(forbid)
PLAN = 'synthetic-plan'
rows = {}
for label, values in EXPECTED.items():
    rows[label] = {'case': label, 'scope': 'SYNTHETIC_MODEL_INPUT_ONLY', 'plan_sha': PLAN,
        'devsim_version': '2.11.0', 'helper': 'devsim.python_packages.Klaassen',
        'helper_source_sha256': 'a'*64, 'helper_source_lf_sha256': 'a'*64,
        'temperature_K': 300., 'cleanup_devices': [], 'solve_attempts': 0,
        'inputs': {name: [value]*4 for name, value in zip(('Donors', 'Acceptors', 'Electrons', 'Holes'), values)},
        'coefficient_species_comments': ['As donor', 'B acceptor'],
        'parameters': {'mu_min_e': 52.2, 'mu_max_e': 1417., 'mu_min_h': 44.9,
                       'mu_max_h': 470.5, 'Nref_D': 4e20, 'Nref_A': 7.2e20},
        'models': {name: {'status': 'FINITE_POSITIVE', 'values': [1.]*(4 if name.endswith('_Node') or name in {'Z_D', 'Z_A'} else 5)} for name in MODELS},
        'creation': 'COMPLETE', 'status': 'NUMERIC_EVALUABLE'}
judge(rows, PLAN)
unavailable = copy.deepcopy(rows)
unavailable['PURE_N']['models']['Z_A'] = {'status': 'EVALUATION_FAILED', 'error': 'synthetic exact-zero failure'}
unavailable['PURE_N']['status'] = 'CAPABILITY_UNAVAILABLE'
judge(unavailable, PLAN)
blocked = []
for label in ('missing_case', 'invented_zero', 'extra_solve', 'hidden_nan', 'wrong_plan', 'missing_error', 'edge_mismatch', 'changed_parameter', 'unknown_creation'):
    m = copy.deepcopy(rows)
    if label == 'missing_case': del m['INTRINSIC']
    elif label == 'invented_zero': m['PURE_N']['inputs']['Acceptors'] = [1e-30]*4
    elif label == 'extra_solve': m['PURE_N']['solve_attempts'] = 1
    elif label == 'hidden_nan': m['PURE_N']['models']['mu_bulk_e']['values'][0] = float('nan')
    elif label == 'wrong_plan': m['PURE_N']['plan_sha'] = 'changed'
    elif label == 'missing_error': m['PURE_N']['models']['Z_A'] = {'status': 'EVALUATION_FAILED'}
    elif label == 'edge_mismatch': m['PURE_N']['models']['mu_bulk_e']['values'][0] = 2.
    elif label == 'changed_parameter': m['PURE_N']['parameters']['mu_max_e'] = 999.
    else: m['PURE_N']['creation'] = 'UNKNOWN'
    try: judge(m, PLAN)
    except (AssertionError, KeyError, ValueError): blocked.append(label)
    else: raise AssertionError('FALSE_GREEN: '+label)
print('PASS: supported/unavailable controls and '+str(len(blocked))+' blocked mutants; engine imports zero')
