"""반올림 한계를 승인과 구분한다. 실제 미분 비교의 산술 재검산."""
import math


def classify(row):
    a = row['analytic']
    carrier = row['carrier_value']
    assert math.isfinite(a) and math.isfinite(carrier) and carrier > 0
    samples = row['samples']
    assert len(samples) == 3
    differences = []
    magnitude = abs(row['base_mobility'])
    assert math.isfinite(magnitude) and magnitude > 0
    for factor, sample in zip((1e-3, 5e-4, 2.5e-4), samples):
        h = carrier*factor
        assert sample['step'] == h and math.isfinite(h) and h > 0
        plus, minus = sample['plus'], sample['minus']
        assert math.isfinite(plus) and math.isfinite(minus) and plus > 0 and minus > 0
        differences.append((plus-minus)/(2*h))
        magnitude = max(magnitude, abs(plus), abs(minus))
    r1 = (4*differences[1]-differences[0])/3
    r2 = (4*differences[2]-differences[1])/3
    budget = 8*abs(r2-r1)+64*math.ulp(magnitude)/(carrier*2.5e-4)
    difference = abs(a-r2)
    assert all(math.isfinite(v) for v in (r1, r2, budget, difference))
    if difference > budget:
        status = 'NUMERICAL_DERIVATIVE_MISMATCH'
    elif budget >= max(abs(a), abs(r2)):
        status = 'ROUND_OFF_LIMITED'
    else:
        status = 'CONSISTENT_AT_TESTED_STEPS'
    return {'status': status, 'richardson': r2, 'difference': difference, 'budget': budget}


def judge(record, plan_sha):
    assert record['plan_sha'] == plan_sha and record['scope'] == 'AUDIT_ONLY_DERIVATIVE_EVALUATION'
    assert record['solve_attempts'] == 0 and record['cleanup_devices'] == []
    assert record['inputs_restored'] is True and record['engine_source_unchanged'] is True
    expected = {(case, model, carrier, node) for case in ('PURE_N', 'PURE_P', 'INTRINSIC', 'BOTH_POSITIVE_CONTROL')
        for model in ('mu_bulk_e_Node', 'mu_bulk_h_Node') for carrier in ('Electrons', 'Holes') for node in range(4)}
    assert len(record['rows']) == 64
    actual = set()
    counts = {}
    for row in record['rows']:
        key = row['case'], row['model'], row['carrier'], row['node']
        assert key not in actual
        actual.add(key)
        result = classify(row)
        assert row['comparison'] == result
        counts[result['status']] = counts.get(result['status'], 0)+1
    assert actual == expected
    return counts
