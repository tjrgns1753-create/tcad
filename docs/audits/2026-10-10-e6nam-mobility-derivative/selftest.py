import copy
from judge import classify

row = {'analytic': 1., 'carrier_value': 1., 'base_mobility': 100.,
       'samples': [{'step': h, 'plus': 100.+h, 'minus': 100.-h} for h in (1e-3, 5e-4, 2.5e-4)]}
assert classify(row)['status'] == 'CONSISTENT_AT_TESTED_STEPS'
wrong = copy.deepcopy(row)
wrong['analytic'] = 2.
assert classify(wrong)['status'] == 'NUMERICAL_DERIVATIVE_MISMATCH'
flat = copy.deepcopy(row)
flat['analytic'] = 0.
for sample in flat['samples']: sample['plus'] = sample['minus'] = 100.
assert classify(flat)['status'] == 'ROUND_OFF_LIMITED'
for fault in ('nan', 'missing', 'step'):
    bad = copy.deepcopy(row)
    if fault == 'nan': bad['analytic'] = float('nan')
    elif fault == 'missing': bad['samples'].pop()
    else: bad['samples'][0]['step'] = .1
    try: classify(bad)
    except (AssertionError, KeyError, ValueError): pass
    else: raise AssertionError(fault)
print('PASS consistent/mismatch/roundoff plus invalid evidence; engine imports zero')
